"""Scheduled jobs against the seeded test database (rolled back after each test)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import FixedClock
from app.core.config import Settings
from app.db.models import (
    JobRun,
    Notification,
    PriceAlert,
    PriceHistory,
    Product,
    ProductPrice,
    SavingsSnapshot,
    User,
)
from app.scheduler.__main__ import jobstore_url
from app.scheduler.jobs import JOBS, JobContext, report_month, run_job

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def jc(
    session_factory: async_sessionmaker[AsyncSession], clock: FixedClock, settings: Settings
) -> JobContext:
    return JobContext(sessions=session_factory, clock=clock, settings=settings)


async def notifications(session: AsyncSession, user_id: int, kind: str) -> list[Notification]:
    return list(
        await session.scalars(
            select(Notification).where(Notification.user_id == user_id, Notification.kind == kind)
        )
    )


def test_every_job_has_a_schedule() -> None:
    assert set(JOBS) == {
        "monthly_budget", "lunch_suggestion", "budget_check", "price_alert_check",
        "grocery_reminder", "savings_report", "price_fluctuation",
    }  # fmt: skip
    assert JOBS["lunch_suggestion"].cron == {"day_of_week": "mon-fri", "hour": "12", "minute": "15"}
    assert JOBS["savings_report"].cron["day"] == "last"


@pytest.mark.parametrize(
    ("now_utc", "expected"),
    [
        (datetime(2026, 11, 15, 7, 0, tzinfo=UTC), "2026-10"),  # mid-month: report last month
        (datetime(2026, 11, 30, 15, 30, tzinfo=UTC), "2026-11"),  # 21:00 IST on the last day
    ],
)
def test_report_month(now_utc: datetime, expected: str) -> None:
    assert report_month(FixedClock(IST, now_utc)) == expected


def test_jobstore_uses_the_sync_driver(settings: Settings) -> None:
    url = jobstore_url(settings)
    assert url.startswith("postgresql+psycopg://")
    assert "ssl=" not in url


@pytest.mark.db
async def test_budget_check_warns_once_per_threshold(
    jc: JobContext, db_session: AsyncSession, arjun: User
) -> None:
    first = await run_job(jc, "budget_check")
    assert first.users == 1 + 3 and first.notifications >= 1
    warnings = await notifications(db_session, arjun.id, "budgetWarning")
    food = [n for n in warnings if n.dedupe_key == "budget:2026-11:food:70"]
    assert len(food) == 1 and food[0].title == "Food budget is 70% used"
    again = await run_job(jc, "budget_check")
    assert again.skipped
    forced = await run_job(jc, "budget_check", force=True)
    assert forced.notifications == 0  # dedupe keys stop duplicates even when forced
    run = await db_session.get(JobRun, ("budget_check", "2026-11-15"), populate_existing=True)
    assert run is not None and run.status == "ok" and run.details["users"] == 4


@pytest.mark.db
async def test_lunch_suggestion_fits_the_food_budget(
    jc: JobContext, db_session: AsyncSession, arjun: User
) -> None:
    outcome = await run_job(jc, "lunch_suggestion")
    assert outcome.notifications >= 1
    (meal,) = [
        n
        for n in await notifications(db_session, arjun.id, "mealSuggestion")
        if n.dedupe_key == "lunch:2026-11-15"
    ]
    assert meal.title.startswith("Lunch near your office for ₹")
    assert "₹2,250 left for food" in meal.body
    assert meal.link and meal.link.startswith("/food/food_")


@pytest.mark.db
async def test_price_alert_check_notifies_once_per_price(
    jc: JobContext, db_session: AsyncSession, arjun: User
) -> None:
    outcome = await run_job(jc, "price_alert_check")
    assert outcome.notifications == 1  # Arjun's one triggered alert
    alert = (
        await db_session.scalars(
            select(PriceAlert).where(
                PriceAlert.user_id == arjun.id, PriceAlert.last_notified_price.is_not(None)
            )
        )
    ).one()
    assert alert.last_notified_price is not None
    forced = await run_job(jc, "price_alert_check", force=True)
    assert forced.notifications == 0


@pytest.mark.db
async def test_grocery_reminder_and_monthly_budget(
    jc: JobContext, db_session: AsyncSession, arjun: User
) -> None:
    await run_job(jc, "grocery_reminder")
    (reminder,) = [
        n
        for n in await notifications(db_session, arjun.id, "groceryReminder")
        if n.dedupe_key == "grocery:2026-W46"
    ]
    assert "22-item list" in reminder.body
    budget = await run_job(jc, "monthly_budget")
    assert budget.notifications == 4
    tips = [
        n
        for n in await notifications(db_session, arjun.id, "tip")
        if n.dedupe_key == "budget-ready:2026-11"
    ]
    assert tips[0].title == "Your November 2026 budget is ready"


@pytest.mark.db
async def test_savings_report_snapshots_the_finished_month(
    jc: JobContext, db_session: AsyncSession, arjun: User
) -> None:
    outcome = await run_job(jc, "savings_report")
    assert outcome.details["month"] == "2026-10"
    snapshot = await db_session.get(SavingsSnapshot, (arjun.id, "2026-10"), populate_existing=True)
    assert snapshot is not None and (snapshot.saved, snapshot.goal, snapshot.total_spent) == (
        7600,
        8000,
        32400,
    )
    (report,) = [
        n
        for n in await notifications(db_session, arjun.id, "savingsReport")
        if n.dedupe_key == "savings:2026-10"
    ]
    assert report.title == "You saved ₹7,600 in October 2026"
    assert "₹400 short" in report.body


@pytest.mark.db
async def test_price_fluctuation_is_deterministic_and_consistent(
    jc: JobContext, db_session: AsyncSession
) -> None:
    first = await run_job(jc, "price_fluctuation")
    assert first.details["products"] == 216
    prices = {
        (pid, platform): price
        for pid, platform, price in (
            await db_session.execute(
                select(ProductPrice.product_id, ProductPrice.platform, ProductPrice.price)
            )
        ).all()
    }
    await run_job(jc, "price_fluctuation", force=True)
    again = {
        (pid, platform): price
        for pid, platform, price in (
            await db_session.execute(
                select(ProductPrice.product_id, ProductPrice.platform, ProductPrice.price)
            )
        ).all()
    }
    assert prices == again  # same seed, same day, same prices
    today = jc.clock.today()
    mismatched = await db_session.scalar(
        select(func.count())
        .select_from(ProductPrice)
        .join(
            PriceHistory,
            (PriceHistory.product_id == ProductPrice.product_id)
            & (PriceHistory.platform == ProductPrice.platform)
            & (PriceHistory.day == today),
        )
        .where(PriceHistory.price != ProductPrice.price)
    )
    assert mismatched == 0
    product = (await db_session.scalars(select(Product).where(Product.id == "prod_001"))).one()
    rows = list(
        await db_session.scalars(select(ProductPrice).where(ProductPrice.product_id == "prod_001"))
    )
    selling = [r for r in rows if r.in_stock] or rows
    assert product.lowest_price == min(r.price for r in selling)


@pytest.mark.db
async def test_month_rollover_carries_the_budget_and_list_forward(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    db_session: AsyncSession,
    arjun: User,
) -> None:
    """On the 1st of a new month the job creates every budget from the previous month."""
    from app.db.models import Budget
    from app.services import budget as budget_service
    from app.services import groceries as grocery_service
    from app.services.context import Ctx

    december = FixedClock(IST, datetime(2026, 11, 30, 18, 35, tzinfo=UTC))  # 1 Dec, 00:05 IST
    jc = JobContext(sessions=session_factory, clock=december, settings=settings)
    outcome = await run_job(jc, "monthly_budget")
    assert outcome.run_key == "2026-12" and outcome.users == 4
    budget = await budget_service.get_budget(db_session, arjun.id, "2026-12")
    assert budget is not None
    november = await budget_service.get_budget(db_session, arjun.id, "2026-11")
    assert november is not None
    assert budget_service.limits_of(budget) == budget_service.limits_of(november)
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Budget).where(Budget.month == "2026-12")
        )
        == 4
    )
    ctx = Ctx(session=db_session, user=arjun, clock=december, settings=settings)
    december_list = await grocery_service.current_list(ctx)
    assert december_list.id == "glist_202612" and december_list.item_count == 22  # carried over
    fresh = await budget_service.current_budget(db_session, arjun, december)
    assert (fresh.month, fresh.total_spent, fresh.days_left_in_month) == ("2026-12", 0, 30)
