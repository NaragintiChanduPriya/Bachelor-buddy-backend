"""The scheduled jobs. Each is idempotent twice over: a `job_runs` row per period stops a whole
rerun, and every notification carries a dedupe key, so even a forced rerun never notifies twice.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from app.agents.llm import LLMClient
from app.agents.tools import find_food
from app.calc.budget import DANGER_THRESHOLD, WARNING_THRESHOLD
from app.calc.grocery import to_plan_summary
from app.calc.products import PlatformToday, round_to_price_point, summarize_platforms
from app.calc.savings import month_label, saved_so_far
from app.core.clock import Clock, days_in_month, shift_month
from app.core.config import Settings
from app.core.money import format_inr
from app.db.models import (
    JobRun,
    PriceAlert,
    PriceHistory,
    Product,
    SavingsSnapshot,
    User,
)
from app.scheduler.wording import polish
from app.services import budget as budget_service
from app.services import groceries as grocery_service
from app.services import notifications as notification_service
from app.services import users as user_service
from app.services.context import Ctx

logger = logging.getLogger(__name__)


@dataclass
class JobContext:
    sessions: async_sessionmaker[AsyncSession]
    clock: Clock
    settings: Settings
    llm: LLMClient | None = None


@dataclass
class JobOutcome:
    job: str
    run_key: str
    skipped: bool = False
    users: int = 0
    notifications: int = 0
    details: dict[str, Any] = field(default_factory=dict)


JobFn = Callable[[JobContext, JobOutcome], Awaitable[None]]


async def _onboarded_user_ids(jc: JobContext) -> list[int]:
    async with jc.sessions() as session:
        return list(
            await session.scalars(select(User.id).where(User.onboarded.is_(True)).order_by(User.id))
        )


async def _for_each_user(
    jc: JobContext, outcome: JobOutcome, work: Callable[[Ctx], Awaitable[int]]
) -> None:
    """One session per user, so one user's failure never blocks the others."""
    for user_id in await _onboarded_user_ids(jc):
        async with jc.sessions() as session:
            user = await user_service.load_user(session, user_id)
            if user is None or user.preferences is None or not user.preferences.home_area_id:
                continue
            ctx = Ctx(session=session, user=user, clock=jc.clock, settings=jc.settings)
            try:
                outcome.notifications += await work(ctx)
                await session.commit()
                outcome.users += 1
            except Exception:
                await session.rollback()
                logger.exception("job_user_failed", extra={"job": outcome.job, "user_id": user_id})


async def _notify(
    jc: JobContext,
    ctx: Ctx,
    *,
    kind: str,
    agent: str,
    title: str,
    body: str,
    link: str | None,
    dedupe_key: str,
) -> int:
    title, body = await polish(jc.llm, jc.settings, title, body)
    created = await notification_service.create(
        ctx.session,
        user_id=ctx.user.id,
        kind=kind,
        agent=agent,
        title=title,
        body=body,
        link=link,
        dedupe_key=dedupe_key,
        created_at=jc.clock.now(),
    )
    return int(created)


# ------------------------------------------------------------------ jobs


async def monthly_budget(jc: JobContext, outcome: JobOutcome) -> None:
    """1st of the month, 00:05: create the new month's budget from the user's preferences."""
    month = jc.clock.month_key()

    async def work(ctx: Ctx) -> int:
        budget = await budget_service.ensure_budget(ctx.session, ctx.user, month)
        total = sum(c.limit_amount for c in budget.categories if c.category != "savings")
        return await _notify(
            jc, ctx, kind="tip", agent="budget",
            title=f"Your {month_label(month)} budget is ready",
            body=f"{format_inr(total)} to spend across seven categories, with "
            f"{format_inr(ctx.prefs.savings_goal)} set aside for savings first.",
            link="/budget", dedupe_key=f"budget-ready:{month}",
        )  # fmt: skip

    await _for_each_user(jc, outcome, work)


async def lunch_suggestion(jc: JobContext, outcome: JobOutcome) -> None:
    """Weekdays 12:15: a lunch near the office that fits what is left in the food budget."""
    today = jc.clock.today()

    async def work(ctx: Ctx) -> int:
        budget = await budget_service.current_budget(ctx.session, ctx.user, jc.clock)
        food = next(c for c in budget.categories if c.id == "food")
        if food.remaining <= 0:
            return 0
        days_left = max(1, budget.days_left_in_month)
        cap = min(200, max(60, food.remaining // days_left))
        pool, _ = await find_food(ctx, near="office", max_price=cap, place_type=None, open_now=True)
        if not pool:
            return 0
        best = pool[0]
        office = ctx.prefs.office_area.name if ctx.prefs.office_area else "your office"
        return await _notify(
            jc, ctx, kind="mealSuggestion", agent="food",
            title=f"Lunch near your office for {format_inr(best.avg_meal_price)}",
            body=f"{best.name} in {office} serves a typical meal for "
            f"{format_inr(best.avg_meal_price)}, {best.distance_from_office_km} km away. You have "
            f"{format_inr(food.remaining)} left for food this month.",
            link=f"/food/{best.id}", dedupe_key=f"lunch:{today.isoformat()}",
        )  # fmt: skip

    await _for_each_user(jc, outcome, work)


async def budget_check(jc: JobContext, outcome: JobOutcome) -> None:
    """Daily 20:00: warn once per month when a category crosses 70% and again at 90%."""
    month = jc.clock.month_key()

    async def work(ctx: Ctx) -> int:
        budget = await budget_service.current_budget(ctx.session, ctx.user, jc.clock)
        created = 0
        for category in budget.categories:
            if category.id == "savings" or category.limit <= 0:
                continue
            level = (
                "90" if category.percent_used >= DANGER_THRESHOLD
                else "70" if category.percent_used >= WARNING_THRESHOLD
                else None
            )  # fmt: skip
            if level is None:
                continue
            daily = max(0, category.remaining) // max(1, budget.days_left_in_month)
            created += await _notify(
                jc, ctx, kind="budgetWarning", agent="budget",
                title=f"{category.label} budget is {category.percent_used}% used",
                body=f"You have spent {format_inr(category.spent)} of {format_inr(category.limit)} "
                f"with {budget.days_left_in_month} days left. About {format_inr(daily)} a day "
                "keeps you inside the limit.",
                link="/budget", dedupe_key=f"budget:{month}:{category.id}:{level}",
            )  # fmt: skip
        return created

    await _for_each_user(jc, outcome, work)


async def price_alert_check(jc: JobContext, outcome: JobOutcome) -> None:
    """Every 6 hours: notify when a tracked product falls to its target price."""
    async with jc.sessions() as session:
        rows = (
            await session.execute(
                select(PriceAlert, Product).join(Product, Product.id == PriceAlert.product_id)
            )
        ).all()
        for alert, product in rows:
            current = product.lowest_price
            if current > alert.target_price or alert.last_notified_price == current:
                continue
            ctx_user = await user_service.load_user(session, alert.user_id)
            if ctx_user is None:
                continue
            ctx = Ctx(session=session, user=ctx_user, clock=jc.clock, settings=jc.settings)
            outcome.notifications += await _notify(
                jc, ctx, kind="priceDrop", agent="shopping",
                title=f"Price drop on the {product.brand} {product.name}",
                body=f"It is now {format_inr(current)} on {product.cheapest_platform}, at or below "
                f"your alert price of {format_inr(alert.target_price)}.",
                link=f"/shop/{product.id}", dedupe_key=f"price:{alert.id}:{current}",
            )  # fmt: skip
            alert.last_notified_price = current
            outcome.users += 1
        await session.commit()


async def grocery_reminder(jc: JobContext, outcome: JobOutcome) -> None:
    """Weekly: the monthly stock-up reminder, with the cheapest store for the user's list."""
    year, week, _ = jc.clock.today().isocalendar()

    async def work(ctx: Ctx) -> int:
        comparison = await grocery_service.comparison(ctx)
        if comparison.item_count == 0:
            return 0
        plan = to_plan_summary(comparison)
        return await _notify(
            jc, ctx, kind="groceryReminder", agent="grocery",
            title="Time for the monthly grocery stock-up",
            body=f"Your {plan.item_count}-item list costs {format_inr(plan.estimated_total)} at the "
            f"cheapest stores ({plan.cheapest_store_label} is the best single store). One bulk "
            f"order saves {format_inr(plan.bulk_saving)} over quick-commerce top-ups.",
            link="/groceries", dedupe_key=f"grocery:{year}-W{week:02d}",
        )  # fmt: skip

    await _for_each_user(jc, outcome, work)


def report_month(clock: Clock) -> str:
    """The month to report: this one on its last day, otherwise the previous (finished) one."""
    if clock.days_left_in_month() == 0:
        return clock.month_key()
    return shift_month(clock.month_key(), -1)


async def savings_report(jc: JobContext, outcome: JobOutcome) -> None:
    """Last day of the month, 21:00: close the month in a savings snapshot and report it."""
    month = report_month(jc.clock)
    outcome.details["month"] = month
    year, number = (int(p) for p in month.split("-"))
    total_days = days_in_month(year, number)

    async def work(ctx: Ctx) -> int:
        budget = await budget_service.get_budget(ctx.session, ctx.user.id, month)
        if budget is None:
            return 0
        limits = budget_service.limits_of(budget)
        spent = await budget_service.spent_by_category(ctx.session, ctx.user.id, month, jc.clock)
        goal = limits.get("savings", 0)
        saved = saved_so_far(goal, limits, spent, total_days, total_days)
        statement = insert(SavingsSnapshot).values(
            user_id=ctx.user.id, month=month, saved=saved, goal=goal, salary=budget.salary,
            total_spent=sum(spent.values()),
        )  # fmt: skip
        await ctx.session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "month"],
                set_={
                    "saved_paise": statement.excluded.saved_paise,
                    "goal_paise": statement.excluded.goal_paise,
                    "salary_paise": statement.excluded.salary_paise,
                    "total_spent_paise": statement.excluded.total_spent_paise,
                },
            )
        )
        verdict = (
            f"past your {format_inr(goal)} goal" if saved >= goal
            else f"{format_inr(goal - saved)} short of your {format_inr(goal)} goal"
        )  # fmt: skip
        return await _notify(
            jc, ctx, kind="savingsReport", agent="savings",
            title=f"You saved {format_inr(saved)} in {month_label(month)}",
            body=f"That is {verdict}. See where it came from on the Savings page.",
            link="/savings", dedupe_key=f"savings:{month}",
        )  # fmt: skip

    await _for_each_user(jc, outcome, work)


async def price_fluctuation(jc: JobContext, outcome: JobOutcome) -> None:
    """Daily 03:00: small realistic price moves, so history, drops and alerts behave like real
    life. Each move starts from yesterday's recorded price and is seeded per product, platform
    and day, so rerunning a day writes exactly the same prices."""
    today = jc.clock.today()
    seed = jc.settings.seed_value
    async with jc.sessions() as session:
        products = (
            (await session.execute(select(Product).options(joinedload(Product.prices))))
            .unique()
            .scalars()
            .all()
        )
        yesterday = {
            (product_id, platform): price
            for product_id, platform, price in (
                await session.execute(
                    select(
                        PriceHistory.product_id, PriceHistory.platform, PriceHistory.price
                    ).where(PriceHistory.day == today - timedelta(days=1))
                )
            ).all()
        }
        changed = 0
        for product in products:
            rows: list[PlatformToday] = []
            for row in product.prices:
                start = yesterday.get((product.id, row.platform), row.price)
                rng = random.Random(f"{seed}:fluctuate:{product.id}:{row.platform}:{today}")  # noqa: S311
                roll = rng.random()
                if roll < 0.02:  # a one-day flash sale
                    target = row.base_price * rng.uniform(0.8, 0.88)
                elif roll < 0.25:  # drift back towards the normal price
                    target = (start + row.base_price) / 2
                else:
                    target = start * rng.uniform(0.985, 1.015)
                price = round_to_price_point(target)
                if price != row.price:
                    changed += 1
                row.price = price
                rows.append(PlatformToday(row.platform, price, row.in_stock, row.delivery_days))
                statement = insert(PriceHistory).values(
                    product_id=product.id, platform=row.platform, day=today, price=price
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["product_id", "platform", "day"],
                        set_={"price_paise": statement.excluded.price_paise},
                    )
                )
            summary = summarize_platforms(rows, product.mrp)
            product.lowest_price = summary.lowest_price
            product.highest_price = summary.highest_price
            product.discount_percent = summary.discount_percent
            product.cheapest_platform = summary.cheapest_platform
            product.fastest_delivery_days = summary.fastest_delivery_days
        # Keep a rolling window: drop history older than what is stored.
        await session.execute(
            delete(PriceHistory).where(PriceHistory.day < today - timedelta(days=179))
        )
        await session.commit()
        outcome.details.update(products=len(products), changed_prices=changed)


# ------------------------------------------------------------------ registry and runner


@dataclass(frozen=True)
class JobSpec:
    name: str
    description: str
    #: APScheduler cron fields, in the business time zone.
    cron: dict[str, str]
    run: JobFn
    run_key: Callable[[Clock], str]


def _day(clock: Clock) -> str:
    return clock.today().isoformat()


def _month(clock: Clock) -> str:
    return clock.month_key()


def _week(clock: Clock) -> str:
    year, week, _ = clock.today().isocalendar()
    return f"{year}-W{week:02d}"


def _six_hours(clock: Clock) -> str:
    local = clock.local_now()
    return f"{local:%Y-%m-%d}T{local.hour // 6 * 6:02d}"


JOBS: dict[str, JobSpec] = {
    spec.name: spec
    for spec in (
        JobSpec("monthly_budget", "Create the new month's budget", {"day": "1", "hour": "0", "minute": "5"}, monthly_budget, _month),
        JobSpec("lunch_suggestion", "Suggest a lunch near the office", {"day_of_week": "mon-fri", "hour": "12", "minute": "15"}, lunch_suggestion, _day),
        JobSpec("budget_check", "Warn at 70% and 90% of a category", {"hour": "20", "minute": "0"}, budget_check, _day),
        JobSpec("price_alert_check", "Notify on price drops", {"hour": "*/6", "minute": "0"}, price_alert_check, _six_hours),
        JobSpec("grocery_reminder", "Weekly grocery stock-up reminder", {"day_of_week": "sun", "hour": "10", "minute": "0"}, grocery_reminder, _week),
        JobSpec("savings_report", "Month-end savings report and snapshot", {"day": "last", "hour": "21", "minute": "0"}, savings_report, lambda c: report_month(c)),
        JobSpec("price_fluctuation", "Simulate daily price moves", {"hour": "3", "minute": "0"}, price_fluctuation, _day),
    )
}  # fmt: skip


async def run_job(jc: JobContext, name: str, *, force: bool = False) -> JobOutcome:
    """Run one job now. A period that already ran successfully is skipped unless forced."""
    spec = JOBS[name]
    outcome = JobOutcome(job=name, run_key=spec.run_key(jc.clock))
    async with jc.sessions() as session:
        existing = await session.get(JobRun, (name, outcome.run_key))
        if existing is not None and existing.status == "ok" and not force:
            outcome.skipped = True
            return outcome
        statement = insert(JobRun).values(
            job_name=name, run_key=outcome.run_key, status="running",
            started_at=jc.clock.now(), details={},
        )  # fmt: skip
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["job_name", "run_key"],
                set_={"status": "running", "started_at": statement.excluded.started_at},
            )
        )
        await session.commit()
    status = "ok"
    try:
        await spec.run(jc, outcome)
    except Exception:
        status = "error"
        logger.exception("job_failed", extra={"job": name})
        raise
    finally:
        async with jc.sessions() as session:
            await session.execute(
                update(JobRun)
                .where(JobRun.job_name == name, JobRun.run_key == outcome.run_key)
                .values(
                    status=status,
                    finished_at=jc.clock.now(),
                    details={
                        **outcome.details,
                        "users": outcome.users,
                        "notifications": outcome.notifications,
                    },
                )
            )
            await session.commit()
        logger.info(
            "job_finished",
            extra={
                "job": name,
                "status": status,
                "users": outcome.users,
                "notifications": outcome.notifications,
            },
        )
    return outcome
