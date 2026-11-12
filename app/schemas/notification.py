from __future__ import annotations

from app.core.constants import AgentName, NotificationKind
from app.schemas.common import CamelModel, UtcDateTime


class NotificationOut(CamelModel):
    id: str
    kind: NotificationKind
    agent: AgentName
    title: str
    body: str
    link: str | None
    read: bool
    created_at: UtcDateTime


class NotificationsResponse(CamelModel):
    items: list[NotificationOut]
    unread_count: int
    server_now: UtcDateTime
