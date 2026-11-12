"""Per-user activity: recommendations, savings snapshots, notifications, chat and agent runs,
plus job bookkeeping."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import AGENT_NAMES, NOTIFICATION_KINDS
from app.db.base import Base
from app.db.models._common import created_at_column, one_of
from app.db.models.budget import MONTH_CHECK
from app.db.types import Rupees


class Recommendation(Base):
    """Something an agent suggested. Once followed, it is worth
    `(alternative_price - chosen_price) * times`. That explains where savings came from; it is
    not added on top of `saved`, because the cheaper choice already shows up as lower spending."""

    __tablename__ = "recommendations"
    __table_args__ = (
        one_of("agent", AGENT_NAMES),
        CheckConstraint("alternative_price_paise >= chosen_price_paise", name="saves_money"),
        CheckConstraint("times >= 1", name="times_positive"),
        Index("ix_recommendations_user_followed", "user_id", "followed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(160))
    chosen_price: Mapped[int] = mapped_column("chosen_price_paise", Rupees)
    alternative_price: Mapped[int] = mapped_column("alternative_price_paise", Rupees)
    times: Mapped[int] = mapped_column(SmallInteger, default=1)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    suggested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    followed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SavingsSnapshot(Base):
    """A closed month's result, written by the month-end savings job."""

    __tablename__ = "savings_snapshots"
    __table_args__ = (CheckConstraint(f"month {MONTH_CHECK}", name="month_format"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    saved: Mapped[int] = mapped_column("saved_paise", Rupees)
    goal: Mapped[int] = mapped_column("goal_paise", Rupees)
    salary: Mapped[int] = mapped_column("salary_paise", Rupees)
    total_spent: Mapped[int] = mapped_column("total_spent_paise", Rupees)
    created_at: Mapped[datetime] = created_at_column()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        one_of("kind", NOTIFICATION_KINDS),
        one_of("agent", AGENT_NAMES),
        #: Jobs build a dedupe key per event, so a rerun never notifies twice.
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    agent: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(200))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    dedupe_key: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        one_of("role", ("user", "assistant")),
        Index("ix_chat_messages_conversation", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    cards: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    agents_used: Mapped[list[str]] = mapped_column(ARRAY(String(12)), default=list)
    steps: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    suggested_follow_ups: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    """One chat request's trip through the agents, for observability and cost tracking."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        one_of("mode", ("rules", "llm")),
        one_of("status", ("ok", "fallback", "error")),
        Index("ix_agent_runs_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="SET NULL")
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    mode: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(10))
    model: Mapped[str | None] = mapped_column(String(80))
    agents_used: Mapped[list[str]] = mapped_column(ARRAY(String(12)), default=list)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobRun(Base):
    """One run of a scheduled job for one period (`run_key`, e.g. a date or a month)."""

    __tablename__ = "job_runs"

    job_name: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    status: Mapped[str] = mapped_column(String(10))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SeedRun(Base):
    """What the synthetic data generator last loaded, so `--seed` can skip an identical run."""

    __tablename__ = "seed_runs"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    seed_value: Mapped[int] = mapped_column(Integer)
    anchor: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    volumes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    row_counts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
