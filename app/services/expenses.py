"""Expenses: list with filters, log, delete."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.clock import month_bounds
from app.core.constants import CATEGORY_LABELS
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.ids import format_id, parse_id
from app.db.models import Expense
from app.schemas.common import PaginationMeta
from app.schemas.expense import (
    CreateExpenseRequest,
    CreateExpenseResponse,
    DeleteExpenseResponse,
    ExpenseListResponse,
    ExpenseOut,
)
from app.services import budget as budget_service
from app.services.context import Ctx


def to_expense_out(expense: Expense) -> ExpenseOut:
    return ExpenseOut(
        id=format_id("exp", expense.id),
        category=expense.category,  # type: ignore[arg-type]
        category_label=CATEGORY_LABELS[expense.category],
        title=expense.title,
        note=expense.note,
        amount=expense.amount,
        merchant=expense.merchant,
        source=expense.source,  # type: ignore[arg-type]
        spent_at=expense.spent_at,
        created_at=expense.created_at,
    )


async def list_expenses(
    ctx: Ctx, *, month: str, category: str | None, page: int, page_size: int
) -> tuple[ExpenseListResponse, PaginationMeta]:
    """Newest first. `filteredTotal` sums the whole filter, not just the page."""
    start, end = month_bounds(month, ctx.clock.zone)
    conditions = [
        Expense.user_id == ctx.user.id,
        Expense.spent_at >= start,
        Expense.spent_at < end,
    ]
    if category:
        conditions.append(Expense.category == category)
    count, total = (
        await ctx.session.execute(
            select(func.count(), func.coalesce(func.sum(Expense.amount), 0)).where(*conditions)
        )
    ).one()
    rows = await ctx.session.scalars(
        select(Expense)
        .where(*conditions)
        .order_by(Expense.spent_at.desc(), Expense.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return (
        ExpenseListResponse(expenses=[to_expense_out(e) for e in rows], filtered_total=int(total)),
        PaginationMeta(page=page, page_size=page_size, total=int(count)),
    )


async def create_expense(ctx: Ctx, body: CreateExpenseRequest) -> CreateExpenseResponse:
    now = ctx.clock.now()
    spent_at = body.spent_at or now
    if spent_at > now:
        raise ValidationFailedError("You cannot log an expense in the future.")
    expense = Expense(
        user_id=ctx.user.id,
        category=body.category,
        title=body.title,
        note=body.note,
        amount=body.amount,
        merchant=body.merchant,
        source="manual",
        spent_at=spent_at,
        created_at=now,
    )
    ctx.session.add(expense)
    await ctx.session.commit()
    category = await budget_service.category_now(ctx.session, ctx.user, ctx.clock, body.category)
    return CreateExpenseResponse(expense=to_expense_out(expense), category=category)


async def delete_expense(ctx: Ctx, public_id: str) -> DeleteExpenseResponse:
    expense_id = parse_id("exp", public_id)
    expense = None
    if expense_id is not None:
        expense = await ctx.session.scalar(
            select(Expense).where(Expense.id == expense_id, Expense.user_id == ctx.user.id)
        )
    if expense is None:
        raise NotFoundError.resource("Expense")
    category_id = expense.category
    await ctx.session.delete(expense)
    await ctx.session.commit()
    category = await budget_service.category_now(ctx.session, ctx.user, ctx.clock, category_id)
    return DeleteExpenseResponse(id=public_id, category=category)
