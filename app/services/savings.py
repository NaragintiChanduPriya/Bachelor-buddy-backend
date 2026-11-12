"""Savings: this or a past month against the goal, and the recent history. The formula is
documented in app/calc/savings.py."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.calc.savings import (
    FollowedRecommendation,
    build_monthly_savings,
    build_savings_history,
    month_label,
    recommendation_saving,
    saved_so_far,
)
from app.core.clock import days_in_month, month_bounds, shift_month
from app.core.errors import BadRequestError, NotFoundError
from app.core.ids import format_id
from app.db.models import Budget, Expense, Recommendation, SavingsSnapshot
from app.schemas.savings import MonthlySavings, SavingsHistory, SavingsHistoryPoint
from app.services import budget as budget_service
from app.services.context import Ctx


async def _followed(ctx: Ctx, month: str) -> list[FollowedRecommendation]:
    start, end = month_bounds(month, ctx.clock.zone)
    rows = await ctx.session.scalars(
        select(Recommendation).where(
            Recommendation.user_id == ctx.user.id,
            Recommendation.accepted.is_(True),
            Recommendation.followed_at >= start,
            Recommendation.followed_at < end,
        )
    )
    return [
        FollowedRecommendation(
            id=format_id("rec", r.id),
            title=r.title,
            agent=r.agent,
            saved=recommendation_saving(r.alternative_price, r.chosen_price, r.times),
            followed_at=r.followed_at,
        )
        for r in rows
        if r.followed_at is not None
    ]


async def monthly(ctx: Ctx, month: str) -> MonthlySavings:
    current = ctx.clock.month_key()
    if month > current:
        raise BadRequestError("That month has not started yet.")
    year, number = (int(p) for p in month.split("-"))
    if month == current:
        budget = await budget_service.ensure_budget(ctx.session, ctx.user, month)
        day, total_days = ctx.clock.day_of_month(), ctx.clock.days_in_current_month()
        goal = ctx.prefs.savings_goal
    else:
        found = await budget_service.get_budget(ctx.session, ctx.user.id, month)
        if found is None:
            raise NotFoundError("There is no budget for that month.")
        budget = found
        day = total_days = days_in_month(year, number)
        goal = budget_service.limits_of(budget).get("savings", 0)
    spent = await budget_service.spent_by_category(ctx.session, ctx.user.id, month, ctx.clock)
    return build_monthly_savings(
        month=month,
        salary=budget.salary,
        goal=goal,
        limits=budget_service.limits_of(budget),
        spent=spent,
        day=day,
        days_in_month=total_days,
        recommendations=await _followed(ctx, month),
    )


async def history(ctx: Ctx, months: int) -> SavingsHistory:
    """The `months` finished months before this one. A month-end snapshot wins; otherwise the
    month is computed from its budget and expenses (the same formula with d = D)."""
    current = ctx.clock.month_key()
    wanted = [shift_month(current, -offset) for offset in range(months, 0, -1)]
    first_start, _ = month_bounds(wanted[0], ctx.clock.zone)
    current_start, _ = month_bounds(current, ctx.clock.zone)

    snapshots = {
        s.month: s
        for s in await ctx.session.scalars(
            select(SavingsSnapshot).where(
                SavingsSnapshot.user_id == ctx.user.id, SavingsSnapshot.month.in_(wanted)
            )
        )
    }
    budgets = {
        b.month: b
        for b in (
            await ctx.session.execute(
                select(Budget)
                .options(joinedload(Budget.categories))
                .where(Budget.user_id == ctx.user.id, Budget.month.in_(wanted))
            )
        )
        .unique()
        .scalars()
    }
    local_month = func.to_char(func.timezone(ctx.clock.zone.key, Expense.spent_at), "YYYY-MM")
    spent: dict[str, dict[str, int]] = defaultdict(dict)
    rows = await ctx.session.execute(
        select(local_month, Expense.category, func.sum(Expense.amount))
        .where(
            Expense.user_id == ctx.user.id,
            Expense.spent_at >= first_start,
            Expense.spent_at < current_start,
        )
        .group_by(local_month, Expense.category)
    )
    for month, category, total in rows:
        spent[str(month)][category] = int(total)

    points: list[SavingsHistoryPoint] = []
    for month in wanted:
        snapshot = snapshots.get(month)
        if snapshot is not None:
            saved, goal = snapshot.saved, snapshot.goal
        elif month in budgets:
            limits = budget_service.limits_of(budgets[month])
            year, number = (int(p) for p in month.split("-"))
            total_days = days_in_month(year, number)
            goal = limits.get("savings", 0)
            saved = saved_so_far(goal, limits, spent[month], total_days, total_days)
        else:
            continue
        points.append(
            SavingsHistoryPoint(month=month, month_label=month_label(month), saved=saved, goal=goal)
        )
    return build_savings_history(points)
