"""POST /chat/messages: conversations, history, mode selection, fallback and run logging."""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select

from app.agents.concierge import AgentResult, run_llm
from app.agents.llm import LLMClient, LLMError, Message
from app.agents.rules import run_rules
from app.core.ids import format_id, parse_id
from app.db.models import AgentRun, ChatConversation, ChatMessage, Recommendation
from app.schemas.chat import ChatMessageRequest, ChatReply
from app.services.context import Ctx

logger = logging.getLogger(__name__)


async def _conversation(ctx: Ctx, public_id: str | None) -> ChatConversation:
    """The user's conversation, or a new one. An unknown or foreign id starts fresh rather than
    failing, so a stale id held by the client never breaks chat."""
    conversation_id = parse_id("conv", public_id) if public_id else None
    if conversation_id is not None:
        found = await ctx.session.scalar(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id, ChatConversation.user_id == ctx.user.id
            )
        )
        if found is not None:
            return found
    now = ctx.clock.now()
    conversation = ChatConversation(user_id=ctx.user.id, created_at=now, updated_at=now)
    ctx.session.add(conversation)
    await ctx.session.flush()
    return conversation


async def _history(ctx: Ctx, conversation_id: int) -> list[Message]:
    limit = ctx.settings.agent_history_messages
    if limit == 0:
        return []
    rows = list(
        await ctx.session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
    )
    return [{"role": m.role, "content": _with_card_ids(m)} for m in reversed(rows)]


#: Which key holds the item in each card type that shows one.
_CARD_ITEM_KEYS = {"food": "listing", "product": "product", "home": "home", "offer": "offer"}


def _card_ids(cards: list[dict[str, Any]] | None, card_type: str | None = None) -> list[str]:
    ids = []
    for card in cards or []:
        key = _CARD_ITEM_KEYS.get(card.get("type", ""))
        if key and (card_type is None or card["type"] == card_type):
            ids.append(str(card[key]["id"]))
    return ids


def _with_card_ids(message: ChatMessage) -> str:
    """Assistant turns name the cards they showed, so the model can resolve "there" or "it"."""
    ids = _card_ids(message.cards) if message.role == "assistant" else []
    return message.text + (f"\n(Cards shown: {', '.join(ids)})" if ids else "")


async def _recent_food_ids(ctx: Ctx, conversation_id: int) -> list[str]:
    """The places the previous reply showed, for follow-ups like "is delivery cheaper there?"."""
    cards = await ctx.session.scalar(
        select(ChatMessage.cards)
        .where(ChatMessage.conversation_id == conversation_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )
    return _card_ids(cards, "food")


async def _recent_choices(ctx: Ctx) -> list[str]:
    """A short memory: the last few suggestions the user followed."""
    rows = await ctx.session.scalars(
        select(Recommendation.title)
        .where(Recommendation.user_id == ctx.user.id, Recommendation.accepted.is_(True))
        .order_by(Recommendation.followed_at.desc().nulls_last())
        .limit(3)
    )
    return list(rows)


async def handle_message(ctx: Ctx, body: ChatMessageRequest, llm: LLMClient | None) -> ChatReply:
    conversation = await _conversation(ctx, body.conversation_id)
    history = await _history(ctx, conversation.id)
    recent_food = await _recent_food_ids(ctx, conversation.id)
    now = ctx.clock.now()
    ctx.session.add(
        ChatMessage(conversation_id=conversation.id, role="user", text=body.message, created_at=now)
    )
    await ctx.session.flush()

    started = time.perf_counter()
    mode, status, error = "rules", "ok", None
    result: AgentResult
    if ctx.settings.agent_mode == "llm":
        mode = "llm"
        if llm is None or not ctx.settings.llm_available:
            status, error = "fallback", "GROQ_API_KEY or GROQ_MODEL is not set"
            result = await run_rules(ctx, body.message, recent_food)
        else:
            try:
                result = await run_llm(ctx, llm, body.message, history, await _recent_choices(ctx))
            except LLMError as exc:
                # Nothing to undo: the only write an LLM run can make is an expense the user
                # explicitly asked to log, which should stand.
                logger.warning("agent_fallback", extra={"error": str(exc)})
                status, error = "fallback", str(exc)
                result = await run_rules(ctx, body.message, recent_food)
    else:
        result = await run_rules(ctx, body.message, recent_food)

    reply_at = ctx.clock.now()
    assistant = ChatMessage(
        conversation_id=conversation.id,
        role="assistant",
        text=result.text,
        cards=[card.model_dump(mode="json", by_alias=True) for card in result.cards],
        agents_used=result.agents_used,
        steps=result.steps,
        suggested_follow_ups=result.suggested_follow_ups,
        created_at=reply_at,
    )
    ctx.session.add(assistant)
    conversation.updated_at = reply_at
    await ctx.session.flush()
    ctx.session.add(
        AgentRun(
            user_id=ctx.user.id,
            conversation_id=conversation.id,
            message_id=assistant.id,
            mode=mode,
            status=status,
            model=result.model,
            agents_used=result.agents_used,
            tool_calls=result.tool_log,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=round((time.perf_counter() - started) * 1000),
            error=error,
            created_at=reply_at,
        )
    )
    await ctx.session.commit()
    return ChatReply(
        message_id=format_id("msg", assistant.id),
        conversation_id=format_id("conv", conversation.id),
        text=result.text,
        cards=result.cards,
        agents_used=result.agents_used,  # type: ignore[arg-type]
        steps=result.steps,
        suggested_follow_ups=result.suggested_follow_ups,
        created_at=reply_at,
    )
