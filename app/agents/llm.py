"""The LLM client interface and its Groq implementation.

Agents depend only on `LLMClient`, so the provider can be swapped (or faked in tests). Messages
and tools use the OpenAI-compatible chat-completions format, which Groq implements.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import groq

logger = logging.getLogger(__name__)

Message = dict[str, Any]

#: Longest `retry-after` worth waiting for inside one chat request.
MAX_RETRY_AFTER_SECONDS = 20.0
TRANSIENT_ATTEMPTS = 3


class LLMError(Exception):
    """The model could not produce an answer (after retries). Callers fall back to rules."""


class ToolFormatError(LLMError):
    """The model generated a malformed tool call (Groq returns 400 `tool_use_failed`)."""

    def __init__(self, message: str, failed_generation: str | None = None) -> None:
        super().__init__(message)
        self.failed_generation = failed_generation


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""

    def assistant_message(self) -> Message:
        """This response as a message to append to the conversation."""
        message: Message = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        return message


class LLMClient(Protocol):
    async def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse: ...


def _retry_after(error: groq.APIStatusError) -> float | None:
    value = error.response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class GroqClient:
    """Groq chat completions with tool calling.

    - 429: waits for `retry-after` (or backs off) and retries, unless the wait is too long.
    - 5xx, timeouts, connection errors: exponential backoff, 3 attempts.
    - 400 `tool_use_failed`: raised as ToolFormatError so the agent can correct the model.
    """

    def __init__(self, api_key: str, timeout_seconds: float) -> None:
        self._client = groq.AsyncGroq(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    async def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse:
        delay = 0.5
        for attempt in range(1, TRANSIENT_ATTEMPTS + 1):
            try:
                response = await self._client.chat.completions.create(  # type: ignore[call-overload]
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    max_completion_tokens=max_tokens,
                    temperature=0.2,
                )
            except groq.RateLimitError as exc:
                wait = _retry_after(exc) or delay
                if wait > MAX_RETRY_AFTER_SECONDS or attempt == TRANSIENT_ATTEMPTS:
                    raise LLMError(f"rate limited (retry after {wait:.0f}s)") from exc
                logger.warning("groq_rate_limited", extra={"wait_seconds": wait})
                await asyncio.sleep(wait)
            except groq.BadRequestError as exc:
                body = exc.body if isinstance(exc.body, dict) else {}
                error = body.get("error", body) if isinstance(body, dict) else {}
                if isinstance(error, dict) and error.get("code") == "tool_use_failed":
                    raise ToolFormatError(
                        str(error.get("message", "malformed tool call")),
                        str(error.get("failed_generation", ""))[:500] or None,
                    ) from exc
                raise LLMError(f"bad request: {exc.message}") from exc
            except (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError) as exc:
                if attempt == TRANSIENT_ATTEMPTS:
                    raise LLMError(f"Groq unavailable: {type(exc).__name__}") from exc
                logger.warning("groq_transient_error", extra={"error": type(exc).__name__})
                await asyncio.sleep(delay)
            except groq.APIStatusError as exc:
                raise LLMError(f"Groq error {exc.status_code}") from exc
            else:
                choice = response.choices[0].message
                usage = response.usage
                return LLMResponse(
                    content=choice.content,
                    tool_calls=[
                        ToolCall(call.id, call.function.name, call.function.arguments or "{}")
                        for call in (choice.tool_calls or [])
                    ],
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    model=response.model,
                )
            delay *= 2
        raise LLMError("Groq unavailable")  # pragma: no cover - loop always returns or raises


def tool_result_message(call_id: str, payload: object) -> Message:
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(payload, default=str)}
