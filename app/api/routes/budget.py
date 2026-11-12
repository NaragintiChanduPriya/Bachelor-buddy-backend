"""Budget and expenses."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CtxDep
from app.api.params import Page, PageSize, check_choice, check_month
from app.core.constants import CATEGORY_IDS
from app.schemas.budget import BudgetOut, UpdateBudgetRequest
from app.schemas.common import Envelope, ok
from app.schemas.expense import (
    CreateExpenseRequest,
    CreateExpenseResponse,
    DeleteExpenseResponse,
    ExpenseListResponse,
)
from app.services import budget as budget_service
from app.services import expenses as expense_service

router = APIRouter(tags=["budget"])


@router.get("/budget/current", summary="This month's budget, derived from expenses on every read")
async def current_budget(ctx: CtxDep) -> Envelope[BudgetOut]:
    return ok(await budget_service.current_budget(ctx.session, ctx.user, ctx.clock))


@router.put("/budget/current", summary="Update category limits (the whole set is validated)")
async def update_budget(body: UpdateBudgetRequest, ctx: CtxDep) -> Envelope[BudgetOut]:
    return ok(await budget_service.update_limits(ctx.session, ctx.user, ctx.clock, body))


@router.get("/expenses", tags=["expenses"], summary="Expenses for a month, newest first")
async def list_expenses(
    ctx: CtxDep,
    month: Annotated[str | None, Query(description="YYYY-MM; defaults to this month")] = None,
    category: Annotated[str | None, Query()] = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> Envelope[ExpenseListResponse]:
    chosen = check_month(month, ctx.clock.month_key())
    cat = check_choice(category, CATEGORY_IDS, 'Unknown category "{value}".')
    data, meta = await expense_service.list_expenses(
        ctx, month=chosen, category=cat, page=page, page_size=page_size
    )
    return ok(data, meta)


@router.post("/expenses", tags=["expenses"], summary="Log an expense")
async def create_expense(
    body: CreateExpenseRequest, ctx: CtxDep
) -> Envelope[CreateExpenseResponse]:
    return ok(await expense_service.create_expense(ctx, body))


@router.delete("/expenses/{expense_id}", tags=["expenses"], summary="Delete an expense")
async def delete_expense(expense_id: str, ctx: CtxDep) -> Envelope[DeleteExpenseResponse]:
    return ok(await expense_service.delete_expense(ctx, expense_id))
