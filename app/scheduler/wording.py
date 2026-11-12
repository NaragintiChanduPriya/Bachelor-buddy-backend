"""Notification wording. Templates always work; in llm mode the fast model may polish them, but a
rewrite that changes or drops any rupee amount is thrown away."""

from __future__ import annotations

import json
import logging
import re

from app.agents.llm import LLMClient, LLMError
from app.core.config import Settings

logger = logging.getLogger(__name__)

AMOUNT = re.compile(r"₹[\d,]+")
PROMPT = (
    "Rewrite this app notification to be warm and concise. Keep every ₹ amount, number and name "
    'exactly. Reply with JSON only: {"title": "...", "body": "..."}. Title under 70 characters, '
    "body under 200."
)


async def polish(
    llm: LLMClient | None, settings: Settings, title: str, body: str
) -> tuple[str, str]:
    if llm is None or settings.agent_mode != "llm" or not settings.llm_available:
        return title, body
    try:
        response = await llm.complete(
            model=settings.groq_fast_model or settings.groq_model or "",
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": json.dumps({"title": title, "body": body})},
            ],
            tools=[],
            max_tokens=200,
        )
        data = json.loads(response.content or "{}")
        new_title, new_body = str(data["title"]).strip(), str(data["body"]).strip()
    except (LLMError, ValueError, KeyError, TypeError):
        return title, body
    before = sorted(AMOUNT.findall(title + body))
    after = sorted(AMOUNT.findall(new_title + new_body))
    if before != after or not new_title or not new_body or len(new_title) > 160:
        logger.info("notification_polish_rejected")
        return title, body
    return new_title, new_body
