"""The Concierge (llm mode): delegates to specialist agents exposed as tools, then finishes with
`compose_response`, whose cards are rebuilt from the Evidence and whose numbers are checked."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.evidence import CardRef, Evidence
from app.agents.llm import (
    LLMClient,
    LLMError,
    LLMResponse,
    Message,
    ToolFormatError,
    tool_result_message,
)
from app.agents.prompts import CONCIERGE, DIRECT, SPECIALISTS, Specialist, user_context
from app.agents.tools import TOOLS, compact_schema, run_tool
from app.core.config import Settings
from app.schemas.chat import ChatCard
from app.services.context import Ctx

logger = logging.getLogger(__name__)

MAX_CORRECTIONS = 2
SPECIALIST_TURNS = 3


class ComposeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1500)
    cards: list[CardRef] = Field(default_factory=list, max_length=8)
    suggested_follow_ups: list[str] = Field(default_factory=list, max_length=3)


class AskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=600)


COMPOSE_TOOL = {
    "type": "function",
    "function": {
        "name": "compose_response",
        "description": "Send the final reply. Call exactly once, last.",
        "parameters": compact_schema(ComposeArgs.model_json_schema()),
    },
}


@dataclass
class AgentResult:
    text: str
    cards: list[ChatCard]
    agents_used: list[str]
    steps: list[str]
    suggested_follow_ups: list[str]
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str | None = None


@dataclass
class _Usage:
    prompt: int = 0
    completion: int = 0
    model: str = ""

    def add(self, response: LLMResponse) -> None:
        self.prompt += response.prompt_tokens
        self.completion += response.completion_tokens
        self.model = response.model or self.model


def _ask_tool(specialist: Specialist) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": f"ask_{specialist.name}_agent",
            "description": specialist.description,
            "parameters": compact_schema(AskArgs.model_json_schema()),
        },
    }


async def _complete(
    llm: LLMClient,
    *,
    model: str,
    messages: list[Message],
    tools: list[dict[str, Any]],
    settings: Settings,
    usage: _Usage,
    corrections: list[int],
) -> LLMResponse | None:
    """One model turn. A malformed tool call becomes a correction (None = try again)."""
    try:
        response = await llm.complete(
            model=model, messages=messages, tools=tools, max_tokens=settings.agent_max_tokens
        )
    except ToolFormatError as exc:
        corrections[0] += 1
        if corrections[0] > MAX_CORRECTIONS:
            raise LLMError("the model kept producing malformed tool calls") from exc
        messages.append(
            {
                "role": "user",
                "content": f"Your last tool call was malformed ({exc}). Call one tool with valid "
                "JSON arguments that match its schema.",
            }
        )
        return None
    usage.add(response)
    return response


async def _run_specialist(
    ctx: Ctx,
    llm: LLMClient,
    specialist: Specialist,
    question: str,
    evidence: Evidence,
    context: str,
    usage: _Usage,
    corrections: list[int],
) -> dict[str, Any]:
    evidence.add_agent(specialist.name)
    settings = ctx.settings
    model = settings.groq_fast_model or settings.groq_model or ""
    messages: list[Message] = [
        {"role": "system", "content": f"{specialist.prompt}\n\n{context}"},
        {"role": "user", "content": question},
    ]
    tools = [TOOLS[name].schema() for name in specialist.tools]
    findings: list[dict[str, Any]] = []
    for _ in range(SPECIALIST_TURNS + MAX_CORRECTIONS):
        response = await _complete(
            llm,
            model=model,
            messages=messages,
            tools=tools,
            settings=settings,
            usage=usage,
            corrections=corrections,
        )
        if response is None:
            continue
        if not response.tool_calls:
            return {
                "agent": specialist.name,
                "summary": (response.content or "").strip(),
                "data": findings,
            }
        messages.append(response.assistant_message())
        for call in response.tool_calls:
            tool = TOOLS.get(call.name)
            payload = (
                await run_tool(tool, ctx, evidence, call.arguments)
                if tool and tool.name in specialist.tools
                else {"error": f"{call.name} is not one of your tools."}
            )
            findings.append({"tool": call.name, "result": payload})
            messages.append(tool_result_message(call.id, payload))
    return {"agent": specialist.name, "summary": "", "data": findings}


async def run_llm(
    ctx: Ctx,
    llm: LLMClient,
    message: str,
    history: list[Message],
    recent_choices: list[str],
) -> AgentResult:
    settings = ctx.settings
    evidence = Evidence()
    usage = _Usage()
    corrections = [0]
    context = user_context(ctx, recent_choices)
    # The salary, goal and other context figures may be quoted back.
    evidence.record_numbers(context)
    direct = settings.agent_direct_tools
    system = DIRECT if direct else CONCIERGE
    tools: list[dict[str, Any]] = (
        [t.schema() for t in TOOLS.values()]
        if direct
        else [_ask_tool(s) for s in SPECIALISTS.values()]
    )
    tools.append(COMPOSE_TOOL)
    messages: list[Message] = [
        {"role": "system", "content": f"{system}\n\n{context}"},
        *history,
        {"role": "user", "content": message},
    ]
    number_retry_used = False
    model = settings.groq_model or ""

    for _ in range(settings.agent_max_iterations + MAX_CORRECTIONS + 1):
        response = await _complete(
            llm,
            model=model,
            messages=messages,
            tools=tools,
            settings=settings,
            usage=usage,
            corrections=corrections,
        )
        if response is None:
            continue
        if not response.tool_calls:
            text = (response.content or "").strip()
            if not text:
                raise LLMError("empty reply")
            if evidence.unknown_amounts(text):
                raise LLMError("reply quoted amounts no tool returned")
            return _result(text, [], [], evidence, usage)

        messages.append(response.assistant_message())
        final: AgentResult | None = None
        for call in response.tool_calls:
            if call.name == "compose_response":
                payload, final, number_retry_used = _compose(
                    call.arguments, evidence, usage, number_retry_used, corrections
                )
            elif (
                call.name.startswith("ask_")
                and call.name.removeprefix("ask_").removesuffix("_agent") in SPECIALISTS
                and not direct
            ):
                specialist = SPECIALISTS[call.name.removeprefix("ask_").removesuffix("_agent")]
                try:
                    question = AskArgs.model_validate(json.loads(call.arguments or "{}")).question
                except (ValueError, ValidationError):
                    payload = {"error": 'Send {"question": "..."}.'}
                else:
                    payload = await _run_specialist(
                        ctx, llm, specialist, question, evidence, context, usage, corrections
                    )
            elif direct and call.name in TOOLS:
                payload = await run_tool(TOOLS[call.name], ctx, evidence, call.arguments)
            else:
                payload = {"error": f"Unknown tool {call.name}."}
            messages.append(tool_result_message(call.id, payload))
        if final is not None:
            return final
    raise LLMError("no final answer within the turn limit")


def _compose(
    raw: str, evidence: Evidence, usage: _Usage, number_retry_used: bool, corrections: list[int]
) -> tuple[dict[str, Any], AgentResult | None, bool]:
    """Validate the final reply. Returns (tool payload, result or None, number retry used)."""
    try:
        args = ComposeArgs.model_validate(json.loads(raw or "{}"))
    except (ValueError, ValidationError) as exc:
        corrections[0] += 1
        if corrections[0] > MAX_CORRECTIONS:
            raise LLMError("compose_response arguments stayed invalid") from exc
        return (
            {"error": f"Invalid compose_response arguments: {exc}"[:500]},
            None,
            number_retry_used,
        )
    unknown = evidence.unknown_amounts(args.text)
    if unknown:
        if number_retry_used:
            raise LLMError("reply quoted amounts no tool returned")
        amounts = ", ".join(f"₹{a:,}" for a in unknown)
        return (
            {
                "error": f"These amounts are not in any tool result: {amounts}. Rewrite the reply "
                "using only numbers the tools returned, and call compose_response again."
            },
            None,
            True,
        )
    follow_ups = [f.strip()[:80] for f in args.suggested_follow_ups if f.strip()]
    cards = evidence.build_cards(args.cards)
    return (
        {"ok": True},
        _result(args.text.strip(), cards, follow_ups, evidence, usage),
        number_retry_used,
    )


def _result(
    text: str, cards: list[ChatCard], follow_ups: list[str], evidence: Evidence, usage: _Usage
) -> AgentResult:
    return AgentResult(
        text=text,
        cards=cards,
        agents_used=evidence.agents_used(),
        steps=evidence.steps or ["Working out what you need…"],
        suggested_follow_ups=follow_ups,
        tool_log=evidence.tool_log,
        prompt_tokens=usage.prompt,
        completion_tokens=usage.completion,
        model=usage.model or None,
    )
