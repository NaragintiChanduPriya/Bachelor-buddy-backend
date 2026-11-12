"""Savings and notifications."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CtxDep
from app.api.params import check_month
from app.core.errors import BadRequestError
from app.schemas.common import Envelope, ok
from app.schemas.notification import NotificationsResponse
from app.schemas.savings import MonthlySavings, SavingsHistory
from app.services import notifications as notification_service
from app.services import savings as savings_service

router = APIRouter()


@router.get("/savings/monthly", tags=["savings"], summary="A month against the savings goal")
async def savings_monthly(
    ctx: CtxDep, month: Annotated[str | None, Query()] = None
) -> Envelope[MonthlySavings]:
    return ok(await savings_service.monthly(ctx, check_month(month, ctx.clock.month_key())))


@router.get("/savings/history", tags=["savings"], summary="The last N finished months")
async def savings_history(
    ctx: CtxDep, months: Annotated[float, Query()] = 6
) -> Envelope[SavingsHistory]:
    if not months.is_integer() or not 1 <= months <= 24:
        raise BadRequestError("The months parameter must be a whole number between 1 and 24.")
    return ok(await savings_service.history(ctx, int(months)))


@router.get("/notifications", tags=["notifications"], summary="Agent alerts, newest first")
async def notifications(ctx: CtxDep) -> Envelope[NotificationsResponse]:
    return ok(await notification_service.payload(ctx))


@router.patch("/notifications/read-all", tags=["notifications"], summary="Mark every alert read")
async def read_all(ctx: CtxDep) -> Envelope[NotificationsResponse]:
    return ok(await notification_service.mark_all_read(ctx))


@router.patch(
    "/notifications/{notification_id}/read", tags=["notifications"], summary="Mark one read"
)
async def read_one(notification_id: str, ctx: CtxDep) -> Envelope[NotificationsResponse]:
    return ok(await notification_service.mark_read(ctx, notification_id))
