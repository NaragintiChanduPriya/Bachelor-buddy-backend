"""POST /chat/messages (rate limited per signed-in user: it can spend LLM tokens) and the
user's own chat history: list, open and delete past conversations."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.agents.llm import LLMClient
from app.agents.service import handle_message
from app.api.deps import CtxDep
from app.api.params import Page, PageSize
from app.core.ratelimit import chat_limit, limiter, user_or_client_key
from app.schemas.chat import (
    ChatMessageRequest,
    ChatReply,
    ConversationDetail,
    ConversationSummary,
    DeleteConversationResponse,
)
from app.schemas.common import Envelope, ok
from app.services import chat_history

router = APIRouter(tags=["chat"])


@router.post("/chat/messages", summary="Ask Buddy (the Concierge agent)")
@limiter.limit(chat_limit, key_func=user_or_client_key)
async def chat_message(
    request: Request, body: ChatMessageRequest, ctx: CtxDep
) -> Envelope[ChatReply]:
    llm: LLMClient | None = request.app.state.llm
    return ok(await handle_message(ctx, body, llm))


@router.get("/chat/conversations", summary="The user's past conversations, newest first")
async def list_conversations(
    ctx: CtxDep, page: Page = 1, page_size: PageSize = 20
) -> Envelope[list[ConversationSummary]]:
    items, meta = await chat_history.list_conversations(ctx, page=page, page_size=page_size)
    return ok(items, meta)


@router.get("/chat/conversations/{conversation_id}", summary="One conversation's messages")
async def get_conversation(conversation_id: str, ctx: CtxDep) -> Envelope[ConversationDetail]:
    return ok(await chat_history.conversation_detail(ctx, conversation_id))


@router.delete("/chat/conversations/{conversation_id}", summary="Delete a conversation")
async def delete_conversation(
    conversation_id: str, ctx: CtxDep
) -> Envelope[DeleteConversationResponse]:
    return ok(await chat_history.delete_conversation(ctx, conversation_id))
