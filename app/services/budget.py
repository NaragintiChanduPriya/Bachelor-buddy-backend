"""Budgets: one per user per month, created lazily from the previous month or the salary split."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.calc.budget import build_budget, build_category, generate_limits, validate_limits
from app.core.clock import Clock, month_bounds
from app.core.constants import CATEGORY_IDS
from app.core.errors import ValidationFailedError
from app.db.models import Budget, BudgetCategory, Expense, User
from app.schemas.budget import BudgetCategoryOut, BudgetOut, UpdateBudgetRequest


async def get_budget(session: AsyncSession, user_id: int, month: str) -> Budget | None:
    result = await session.execute(
        select(Budget)
        .options(joinedload(Budget.categories))
        .where(Budget.user_id == user_id, Budget.month == month)
    )
    return result.unique().scalar_one_or_none()


def limits_of(budget: Budget) -> dict[str, int]:
    return {c.category: c.limit_amount for c in budget.categories}


def _set_limits(budget: Budget, limits: Mapping[str, int]) -> None:
    rows = {c.category: c for c in budget.categories}
    for position, category in enumerate(CATEGORY_IDS):
        if category not in limits:
            continue
        if category in rows:
            rows[category].limit_amount = limits[category]
        else:
            budget.categories.append(
                BudgetCategory(category=category, limit_amount=limits[category], position=position)
            )


async def _initial_limits(
    session: AsyncSession, user: User, month: str
) -> tuple[int, dict[str, int]]:
    """Carry the most recent earlier budget forward; otherwise split the salary."""
    prefs = user.preferences
    salary = prefs.salary if prefs else 0
    goal = prefs.savings_goal if prefs else 0
    result = await session.execute(
        select(Budget)
        .options(joinedload(Budget.categories))
        .where(Budget.user_id == user.id, Budget.month < month)
        .order_by(Budget.month.desc())
        .limit(1)
    )
    previous = result.unique().scalar_one_or_none()
    if previous is not None and previous.salary == salary:
        return salary, limits_of(previous)
    return salary, generate_limits(salary, goal)


async def ensure_budget(session: AsyncSession, user: User, month: str) -> Budget:
    """The month's budget, created if missing. Safe under concurrent first requests."""
    budget = await get_budget(session, user.id, month)
    if budget is not None:
        return budget
    salary, limits = await _initial_limits(session, user, month)
    try:
        async with session.begin_nested():
            budget = Budget(user_id=user.id, month=month, salary=salary, categories=[])
            _set_limits(budget, limits)
            session.add(budget)
    except IntegrityError:  # another request created it first
        existing = await get_budget(session, user.id, month)
        if existing is None:
            raise
        return existing
    await session.commit()
    return budget


async def reset_current_limits(
    session: AsyncSession, user: User, clock: Clock, limits: Mapping[str, int]
) -> None:
    """Replace the current month's limits (after onboarding or a salary change). No commit."""
    prefs = user.preferences
    month = clock.month_key()
    budget = await get_budget(session, user.id, month)
    if budget is None:
        budget = Budget(
            user_id=user.id, month=month, salary=prefs.salary if prefs else 0, categories=[]
        )
        session.add(budget)
    budget.salary = prefs.salary if prefs else budget.salary
    _set_limits(budget, limits)


async def spent_by_category(
    session: AsyncSession, user_id: int, month: str, clock: Clock
) -> dict[str, int]:
    start, end = month_bounds(month, clock.zone)
    rows = await session.execute(
        select(Expense.category, func.sum(Expense.amount))
        .where(Expense.user_id == user_id, Expense.spent_at >= start, Expense.spent_at < end)
        .group_by(Expense.category)
    )
    return {category: int(total) for category, total in rows}


async def current_budget(session: AsyncSession, user: User, clock: Clock) -> BudgetOut:
    month = clock.month_key()
    budget = await ensure_budget(session, user, month)
    spent = await spent_by_category(session, user.id, month, clock)
    return build_budget(month, budget.salary, limits_of(budget), spent, clock.days_left_in_month())


async def category_now(
    session: AsyncSession, user: User, clock: Clock, category: str
) -> BudgetCategoryOut:
    """One category of the current month, after a change, so the client can reconcile."""
    month = clock.month_key()
    budget = await ensure_budget(session, user, month)
    spent = await spent_by_category(session, user.id, month, clock)
    return build_category(category, limits_of(budget).get(category, 0), spent.get(category, 0))


async def update_limits(
    session: AsyncSession, user: User, clock: Clock, body: UpdateBudgetRequest
) -> BudgetOut:
    budget = await ensure_budget(session, user, clock.month_key())
    merged = limits_of(budget)
    for entry in body.categories:
        merged[entry.id] = entry.limit
    salary = user.preferences.salary if user.preferences else budget.salary
    check = validate_limits([(c, merged[c]) for c in CATEGORY_IDS if c in merged], salary)
    if not check.valid:
        raise ValidationFailedError(
            check.message or "Those budget limits are not valid.",
            {"total": check.total, "salary": salary},
        )
    _set_limits(budget, merged)
    await session.commit()
    return await current_budget(session, user, clock)
