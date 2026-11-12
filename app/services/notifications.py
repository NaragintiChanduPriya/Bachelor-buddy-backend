"""Agent notifications."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.ids import format_id, parse_id
from app.db.models import Notification
from app.schemas.notification import NotificationOut, NotificationsResponse
from app.services.context import Ctx

#: The newest notifications returned; the unread count covers all of them.
MAX_ITEMS = 100


def to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=format_id("notif", n.id),
        kind=n.kind,  # type: ignore[arg-type]
        agent=n.agent,  # type: ignore[arg-type]
        title=n.title,
        body=n.body,
        link=n.link,
        read=n.read,
        created_at=n.created_at,
    )


async def payload(ctx: Ctx) -> NotificationsResponse:
    rows = await ctx.session.scalars(
        select(Notification)
        .where(Notification.user_id == ctx.user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(MAX_ITEMS)
    )
    unread = await ctx.session.scalar(
        select(func.count()).where(
            Notification.user_id == ctx.user.id, Notification.read.is_(False)
        )
    )
    return NotificationsResponse(
        items=[to_out(n) for n in rows],
        unread_count=int(unread or 0),
        server_now=ctx.clock.now(),
    )


async def mark_read(ctx: Ctx, public_id: str) -> NotificationsResponse:
    notification_id = parse_id("notif", public_id)
    result = None
    if notification_id is not None:
        result = await ctx.session.scalar(
            update(Notification)
            .where(Notification.id == notification_id, Notification.user_id == ctx.user.id)
            .values(read=True)
            .returning(Notification.id)
        )
    if result is None:
        raise NotFoundError.resource("Notification")
    await ctx.session.commit()
    return await payload(ctx)


async def mark_all_read(ctx: Ctx) -> NotificationsResponse:
    await ctx.session.execute(
        update(Notification)
        .where(Notification.user_id == ctx.user.id, Notification.read.is_(False))
        .values(read=True)
    )
    await ctx.session.commit()
    return await payload(ctx)


async def create(
    session: AsyncSession,
    *,
    user_id: int,
    kind: str,
    agent: str,
    title: str,
    body: str,
    link: str | None,
    dedupe_key: str,
    created_at: datetime,
) -> bool:
    """Insert unless this event was already notified. Returns True when a row was written.
    The caller commits."""
    statement = (
        insert(Notification)
        .values(
            user_id=user_id,
            kind=kind,
            agent=agent,
            title=title,
            body=body,
            link=link,
            dedupe_key=dedupe_key,
            created_at=created_at,
            read=False,
        )
        .on_conflict_do_nothing(constraint="uq_notifications_user_dedupe")
        .returning(Notification.id)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None
