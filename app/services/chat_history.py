"""Each user's own chat history: the list of past conversations, one conversation's messages,
and deleting a conversation. Every query is scoped to the signed-in user; another user's
conversation is a 404, exactly like one that doesn't exist."""

from __future__ import annotations

import re

from sqlalchemy import delete, exists, func, select
from sqlalchemy.sql.expression import Exists, ScalarSelect

from app.core.errors import NotFoundError
from app.core.ids import format_id, parse_id
from app.db.models import ChatConversation, ChatMessage
from app.schemas.chat import (
    ChatHistoryMessage,
    ConversationDetail,
    ConversationSummary,
    DeleteConversationResponse,
)
from app.schemas.common import PaginationMeta
from app.services.context import Ctx

TITLE_LENGTH = 60
PREVIEW_LENGTH = 90


def shorten(text: str | None, limit: int) -> str:
    """One line, at most `limit` characters, cut at a word where possible."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    if len(flat) <= limit:
        return flat
    head = flat[: limit - 1]
    # Drop a half-cut last word, but keep one that ends exactly at the cut.
    if flat[limit - 1] != " " and " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ,.;:—-") + "…"


def _first_user_text() -> ScalarSelect[str]:
    return (
        select(ChatMessage.text)
        .where(ChatMessage.conversation_id == ChatConversation.id, ChatMessage.role == "user")
        .order_by(ChatMessage.id)
        .limit(1)
        .correlate(ChatConversation)
        .scalar_subquery()
    )


def _has_messages() -> Exists:
    return exists().where(ChatMessage.conversation_id == ChatConversation.id)


async def list_conversations(
    ctx: Ctx, *, page: int, page_size: int
) -> tuple[list[ConversationSummary], PaginationMeta]:
    """Newest activity first."""
    last_text = (
        select(ChatMessage.text)
        .where(ChatMessage.conversation_id == ChatConversation.id)
        .order_by(ChatMessage.id.desc())
        .limit(1)
        .correlate(ChatConversation)
        .scalar_subquery()
    )
    count = (
        select(func.count())
        .where(ChatMessage.conversation_id == ChatConversation.id)
        .correlate(ChatConversation)
        .scalar_subquery()
    )
    owned = (ChatConversation.user_id == ctx.user.id, _has_messages())
    total = await ctx.session.scalar(
        select(func.count()).select_from(ChatConversation).where(*owned)
    )
    rows = await ctx.session.execute(
        select(
            ChatConversation.id,
            ChatConversation.created_at,
            ChatConversation.updated_at,
            _first_user_text(),
            last_text,
            count,
        )
        .where(*owned)
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        ConversationSummary(
            id=format_id("conv", conversation_id),
            title=shorten(first, TITLE_LENGTH) or "New chat",
            preview=shorten(last, PREVIEW_LENGTH),
            message_count=int(messages),
            created_at=created,
            updated_at=updated,
        )
        for conversation_id, created, updated, first, last, messages in rows
    ]
    return items, PaginationMeta(page=page, page_size=page_size, total=int(total or 0))


async def _owned(ctx: Ctx, public_id: str) -> ChatConversation:
    number = parse_id("conv", public_id)
    conversation = (
        await ctx.session.scalar(
            select(ChatConversation).where(
                ChatConversation.id == number, ChatConversation.user_id == ctx.user.id
            )
        )
        if number is not None
        else None
    )
    if conversation is None:
        raise NotFoundError.resource("Conversation")
    return conversation


async def conversation_detail(ctx: Ctx, public_id: str) -> ConversationDetail:
    conversation = await _owned(ctx, public_id)
    rows = list(
        await ctx.session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation.id)
            .order_by(ChatMessage.id)
        )
    )
    first_user = next((m.text for m in rows if m.role == "user"), "")
    return ConversationDetail(
        id=format_id("conv", conversation.id),
        title=shorten(first_user, TITLE_LENGTH) or "New chat",
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            ChatHistoryMessage(
                id=format_id("msg", m.id),
                role="assistant" if m.role == "assistant" else "user",
                text=m.text,
                cards=list(m.cards or []),
                agents_used=list(m.agents_used or []),  # type: ignore[arg-type]
                steps=list(m.steps or []),
                suggested_follow_ups=list(m.suggested_follow_ups or []),
                created_at=m.created_at,
            )
            for m in rows
        ],
    )


async def delete_conversation(ctx: Ctx, public_id: str) -> DeleteConversationResponse:
    conversation = await _owned(ctx, public_id)
    await ctx.session.execute(
        delete(ChatConversation).where(ChatConversation.id == conversation.id)
    )
    await ctx.session.commit()
    return DeleteConversationResponse(conversation_id=format_id("conv", conversation.id))
