"""Builds a rules-mode reply in the same shape as an llm-mode one."""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.concierge import AgentResult
from app.agents.evidence import CardRef, Evidence


def build_result(
    ev: Evidence,
    text: str,
    refs: list[CardRef],
    agents: Sequence[str],
    steps: Sequence[str],
    follow_ups: Sequence[str],
) -> AgentResult:
    for agent in agents:
        ev.add_agent(agent)
    return AgentResult(
        text=text,
        cards=ev.build_cards(refs),
        agents_used=ev.agents_used(),
        steps=list(steps),
        suggested_follow_ups=list(follow_ups),
        tool_log=ev.tool_log,
    )


def join_words(parts: Sequence[str]) -> str:
    """ "a", "a and b", "a, b and c"."""
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
