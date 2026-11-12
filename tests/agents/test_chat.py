"""POST /chat/messages in rules mode, and the Concierge with a scripted fake LLM."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.evidence import Evidence
from app.agents.llm import LLMError, LLMResponse, Message, ToolCall, ToolFormatError
from app.agents.rules import match_intent
from app.agents.tools import (
    ExpensesArgs,
    FoodSearchArgs,
    get_recent_expenses,
    search_nearby_food,
)
from app.core.clock import FixedClock
from app.core.config import Settings
from app.db.models import AgentRun, User
from app.services.context import Ctx
from tests.conftest import bearer, make_client

pytestmark = pytest.mark.db

DEMO_REQUESTS = {
    "I have ₹150 and I'm hungry near office": ("food", {"concierge", "budget", "food"}),
    "Formal shoes under ₹1,500 for an interview on Friday": (
        "product",
        {"concierge", "budget", "shopping", "deals"},
    ),
    "How much did I spend on food this month?": ("budgetSummary", {"concierge", "budget", "food"}),
    "Cheapest way to buy groceries this month": ("groceryPlan", {"concierge", "budget", "grocery"}),
    "Find a PG under ₹10,000 near Marathahalli": ("home", {"concierge", "budget", "home"}),
}


async def chat(
    app: FastAPI, user: User, settings: Settings, message: str, conversation: str | None = None
) -> dict[str, Any]:
    async with await make_client(app, bearer(user.id, settings)) as http:
        response = await http.post(
            "/api/chat/messages", json={"message": message, "conversationId": conversation}
        )
    body = response.json()
    assert response.status_code == 200, body
    return body["data"]  # type: ignore[no-any-return]


@pytest.mark.parametrize("message", list(DEMO_REQUESTS))
async def test_rules_mode_answers_the_demo_requests(
    db_app: FastAPI, arjun: User, settings: Settings, message: str
) -> None:
    card_type, agents = DEMO_REQUESTS[message]
    reply = await chat(db_app, arjun, settings, message)
    assert reply["cards"] and reply["cards"][0]["type"] == card_type
    assert set(reply["agentsUsed"]) == agents
    assert reply["steps"] and reply["suggestedFollowUps"]
    assert reply["messageId"].startswith("msg_") and reply["conversationId"].startswith("conv_")
    assert reply["createdAt"] == "2026-11-15T07:00:00.000Z"
    assert "₹" in reply["text"]


async def test_rules_numbers_match_the_pages(
    db_app: FastAPI, arjun: User, settings: Settings
) -> None:
    reply = await chat(db_app, arjun, settings, "How much did I spend on food this month?")
    assert reply["text"].startswith(
        "You have spent ₹5,250 on food this month, which is 70% of your ₹7,500 budget"
    )
    assert [row["id"] for row in reply["cards"][0]["budget"]] == ["food", "groceries"]
    shoes = await chat(
        db_app, arjun, settings, "Formal shoes under ₹1,500 for an interview on Friday"
    )
    product = shoes["cards"][0]["product"]
    assert product["category"] == "formalShoes" and product["lowestPrice"] <= 1500


HOTELS = "give me hotels list nearby me in the order of lowest to highest prices"


async def test_a_hotels_list_comes_back_in_the_order_asked(
    db_app: FastAPI, arjun: User, settings: Settings
) -> None:
    reply = await chat(db_app, arjun, settings, HOTELS)
    assert reply["cards"] and all(card["type"] == "food" for card in reply["cards"])
    listings = [card["listing"] for card in reply["cards"]]
    prices = [item["avgMealPrice"] for item in listings]
    assert len(prices) == 6 and prices == sorted(prices)
    # Sunday 12:30 on the test clock, so "near me" is home. Vegetarian, as Arjun prefers.
    assert reply["text"].startswith(
        "Here are 6 places to eat within walking distance of your home in HSR Layout, "
        "cheapest first:\n1. "
    )
    assert all(item["veg"] for item in listings) and listings[0]["name"] in reply["text"]

    priciest = await chat(
        db_app, arjun, settings, "top 5 restaurants near office highest to lowest"
    )
    prices = [card["listing"]["avgMealPrice"] for card in priciest["cards"]]
    assert len(prices) == 5 and prices == sorted(prices, reverse=True)
    assert "your office in Bellandur" in priciest["text"]


async def test_follow_ups_use_the_previous_reply(
    db_app: FastAPI, arjun: User, settings: Settings
) -> None:
    listed = await chat(db_app, arjun, settings, HOTELS)
    shown = [card["listing"]["id"] for card in listed["cards"]]
    follow = await chat(
        db_app, arjun, settings, "Is delivery cheaper than going there?", listed["conversationId"]
    )
    compared = [card["listing"]["id"] for card in follow["cards"]]
    assert compared and set(compared) <= set(shown)
    assert "Going there is cheaper" in follow["text"] or "doesn't deliver" in follow["text"]


async def test_every_suggested_follow_up_is_understood(
    db_app: FastAPI, arjun: User, settings: Settings
) -> None:
    messages = [
        *DEMO_REQUESTS,
        HOTELS,
        "Where is my money going?",
        "What offers can I use on my cards?",
        "How much have I saved this month?",
        "tell me a joke",
        "hi",
        "what is my selected location",
        "how much did I spend on rent this month",
        "show my recent expenses",
        "Show my notifications",
        "what is on my grocery list",
        "how much did I save last month",
    ]
    chips: set[str] = set()
    for message in messages:
        chips.update((await chat(db_app, arjun, settings, message))["suggestedFollowUps"])
    assert chips
    assert [chip for chip in chips if match_intent(chip) is None] == []


async def test_questions_about_the_user_are_answered_from_their_data(
    db_app: FastAPI, arjun: User, settings: Settings
) -> None:
    where = await chat(db_app, arjun, settings, "what is my selected location")
    assert where["text"].startswith("You live in HSR Layout and work in Bellandur")
    assert where["agentsUsed"] == ["concierge"]
    me = await chat(db_app, arjun, settings, "who am i")
    assert me["text"].startswith("You are Arjun, 24, working as a Software Engineer")
    hello = await chat(db_app, arjun, settings, "hi")
    assert hello["text"].startswith("Hi Arjun!")
    rent = await chat(db_app, arjun, settings, "how much did I spend on rent this month")
    assert "on rent this month" in rent["text"]
    assert [row["id"] for row in rent["cards"][0]["budget"]] == ["rent"]
    alerts = await chat(db_app, arjun, settings, "Show my notifications")
    assert "unread" in alerts["text"] or "caught up" in alerts["text"]


async def test_the_agent_logs_an_expense_only_when_told(
    db_app: FastAPI, arjun: User, settings: Settings
) -> None:
    before = await chat(db_app, arjun, settings, "how much did I spend on food?")
    logged = await chat(db_app, arjun, settings, "I spent 120 on lunch at the mess")
    assert logged["text"].startswith("Done — I logged ₹120 for Lunch at the mess under food.")
    assert [row["id"] for row in logged["cards"][0]["budget"]] == ["food"]
    after = await chat(db_app, arjun, settings, "how much did I spend on food?")
    assert before["text"].startswith("You have spent ₹5,250 on food")
    assert after["text"].startswith("You have spent ₹5,370 on food")
    recent = await chat(db_app, arjun, settings, "show my recent expenses")
    assert recent["text"].startswith(
        "Your latest expenses this month:\n1. Lunch at the mess — ₹120"
    )


async def test_the_expenses_tool_lists_the_biggest(
    db_session: AsyncSession, arjun: User, settings: Settings, clock: FixedClock
) -> None:
    ctx = Ctx(session=db_session, user=arjun, clock=clock, settings=settings)
    result = await get_recent_expenses(ctx, Evidence(), ExpensesArgs(order="biggest", limit=5))
    amounts = [row["amount"] for row in result["expenses"]]
    assert result["period"] == "this month" and result["total"] == 25020
    assert len(amounts) == 5 and amounts == sorted(amounts, reverse=True)


async def test_the_food_tool_sorts_as_asked(
    db_session: AsyncSession, arjun: User, settings: Settings, clock: FixedClock
) -> None:
    ctx = Ctx(session=db_session, user=arjun, clock=clock, settings=settings)
    args = FoodSearchArgs(near="home", sort="priceDesc", limit=4, open_now=False)
    result = await search_nearby_food(ctx, Evidence(), args)
    prices = [listing["avgMealPrice"] for listing in result["listings"]]
    assert len(prices) == 4 and prices == sorted(prices, reverse=True)


async def test_conversations_continue_and_runs_are_logged(
    db_app: FastAPI, arjun: User, settings: Settings, db_session: AsyncSession
) -> None:
    first = await chat(db_app, arjun, settings, "tell me a joke")
    assert first["agentsUsed"] == ["concierge"] and first["cards"] == []
    second = await chat(
        db_app, arjun, settings, "How much have I saved this month?", first["conversationId"]
    )
    assert second["conversationId"] == first["conversationId"]
    stale = await chat(db_app, arjun, settings, "hello", "conv_999999")
    assert stale["conversationId"] != "conv_999999"
    runs = list(await db_session.scalars(select(AgentRun).where(AgentRun.user_id == arjun.id)))
    assert len(runs) == 3 and all(r.mode == "rules" and r.status == "ok" for r in runs)


async def test_message_validation(db_app: FastAPI, arjun: User, settings: Settings) -> None:
    async with await make_client(db_app, bearer(arjun.id, settings)) as http:
        empty = await http.post("/api/chat/messages", json={"message": "   "})
        long = await http.post("/api/chat/messages", json={"message": "x" * 501})
    assert empty.json()["error"]["message"] == "Type a message first."
    assert (
        long.json()["error"]["message"] == "That message is too long. Keep it under 500 characters."
    )


# ------------------------------------------------------------------ llm mode with a fake model


Step = Callable[[list[Message]], LLMResponse] | LLMResponse | Exception


class FakeLLM:
    """Plays back scripted turns; a step can inspect the conversation so far."""

    def __init__(self, steps: list[Step]) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, *, model: str, messages: list[Message], tools: list[dict[str, Any]], max_tokens: int
    ) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "messages": [dict(m) for m in messages],
                "tools": [t["function"]["name"] for t in tools],
            }
        )
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        response = step(messages) if callable(step) else step
        response.prompt_tokens, response.completion_tokens = 100, 20
        return response


def call(name: str, arguments: dict[str, Any] | str, call_id: str = "c1") -> LLMResponse:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return LLMResponse(content=None, tool_calls=[ToolCall(call_id, name, raw)], model="fake-model")


def last_tool_result(messages: list[Message]) -> dict[str, Any]:
    return json.loads(next(m for m in reversed(messages) if m["role"] == "tool")["content"])  # type: ignore[no-any-return]


@pytest.fixture
def llm_app(db_app: FastAPI, settings: Settings) -> FastAPI:
    db_app.state.settings = settings.model_copy(
        update={
            "agent_mode": "llm",
            "groq_api_key": SecretStr("gsk_test"),
            "groq_model": "main",
            "groq_fast_model": "fast",
        }
    )
    return db_app


def compose_from_food(messages: list[Message]) -> LLMResponse:
    """The concierge composes using what the food agent actually returned."""
    found = last_tool_result(messages)
    listing = found["data"][-1]["result"]["listings"][0]  # the corrected call
    return call(
        "compose_response",
        {
            "text": f"{listing['name']} serves a meal for ₹{listing['avgMealPrice']:,}.",
            "cards": [{"type": "food", "id": listing["id"]}, {"type": "food", "id": "food_999"}],
            "suggested_follow_ups": ["Is delivery cheaper?"],
        },
    )


async def test_concierge_delegates_validates_and_builds_cards(
    llm_app: FastAPI, arjun: User, settings: Settings, db_session: AsyncSession
) -> None:
    fake = FakeLLM(
        [
            call("ask_food_agent", {"question": "Cheap lunch near office under 150"}),
            # The food agent first sends a bad argument, gets the validation error, retries.
            call("search_nearby_food", {"near": "moon"}),
            lambda m: (
                call("search_nearby_food", {"near": "office", "max_price": 150})
                if "Invalid arguments" in last_tool_result(m)["error"]
                else LLMResponse(content="unexpected")
            ),
            LLMResponse(content="Found cheap places near the office.", model="fake-fast"),
            compose_from_food,
        ]
    )
    llm_app.state.llm = fake
    reply = await chat(llm_app, arjun, settings, "I have 150 and I'm hungry near office")
    assert reply["agentsUsed"] == ["concierge", "food"]
    assert [c["type"] for c in reply["cards"]] == ["food"]  # the invented food_999 was dropped
    assert reply["text"].endswith(f"₹{reply['cards'][0]['listing']['avgMealPrice']:,}.")
    assert reply["suggestedFollowUps"] == ["Is delivery cheaper?"]
    assert reply["steps"] == ["Finding meals nearby…"]
    assert [c["model"] for c in fake.calls] == ["main", "fast", "fast", "fast", "main"]
    assert (
        "compose_response" in fake.calls[0]["tools"] and "ask_food_agent" in fake.calls[0]["tools"]
    )
    run = (await db_session.scalars(select(AgentRun).where(AgentRun.user_id == arjun.id))).one()
    assert (run.mode, run.status, run.prompt_tokens, run.completion_tokens) == (
        "llm",
        "ok",
        500,
        100,
    )
    assert [t["tool"] for t in run.tool_calls] == ["search_nearby_food", "search_nearby_food"]
    assert run.tool_calls[0]["ok"] is False and run.tool_calls[1]["ok"] is True


async def test_invented_amounts_force_one_rewrite(
    llm_app: FastAPI, arjun: User, settings: Settings
) -> None:
    fake = FakeLLM(
        [
            call("ask_budget_agent", {"question": "food spend"}),
            call("get_category_spending", {"category": "food"}),
            LLMResponse(content="₹5,250 spent on food."),
            call("compose_response", {"text": "You spent ₹5,250, only ₹12 a day!"}),
            lambda m: (
                call(
                    "compose_response",
                    {"text": "You have spent ₹5,250 on food and have ₹2,250 left."},
                )
                if "not in any tool result" in last_tool_result(m)["error"]
                else LLMResponse(content="unexpected")
            ),
        ]
    )
    llm_app.state.llm = fake
    reply = await chat(llm_app, arjun, settings, "How much did I spend on food?")
    assert reply["text"] == "You have spent ₹5,250 on food and have ₹2,250 left."


async def test_malformed_tool_calls_are_corrected(
    llm_app: FastAPI, arjun: User, settings: Settings
) -> None:
    fake = FakeLLM(
        [
            ToolFormatError("tool call validation failed", '{"name": "ask_deals_agent"'),
            call("compose_response", {"text": "Ask me about offers on your cards any time."}),
        ]
    )
    llm_app.state.llm = fake
    reply = await chat(llm_app, arjun, settings, "hi")
    assert reply["text"] == "Ask me about offers on your cards any time."
    assert "malformed" in fake.calls[1]["messages"][-1]["content"]


@pytest.mark.parametrize(
    "steps",
    [
        [LLMError("rate limited (retry after 60s)")],
        [
            call("compose_response", {"text": "Shoes for ₹99!"}),
            call("compose_response", {"text": "Still ₹99!"}),
        ],
        [ToolFormatError("bad")] * 3,
    ],
)
async def test_failures_fall_back_to_rules(
    llm_app: FastAPI, arjun: User, settings: Settings, db_session: AsyncSession, steps: list[Step]
) -> None:
    llm_app.state.llm = FakeLLM(steps)
    reply = await chat(llm_app, arjun, settings, "How much did I spend on food this month?")
    assert reply["text"].startswith("You have spent ₹5,250 on food this month")  # the rules answer
    run = (await db_session.scalars(select(AgentRun).where(AgentRun.user_id == arjun.id))).one()
    assert (run.mode, run.status) == ("llm", "fallback") and run.error


async def test_llm_mode_without_a_key_uses_rules(
    db_app: FastAPI, arjun: User, settings: Settings, db_session: AsyncSession
) -> None:
    db_app.state.settings = settings.model_copy(update={"agent_mode": "llm", "groq_api_key": None})
    db_app.state.llm = None
    reply = await chat(db_app, arjun, settings, "Cheapest way to buy groceries this month")
    assert reply["cards"][0]["type"] == "groceryPlan"
    run = (await db_session.scalars(select(AgentRun).where(AgentRun.user_id == arjun.id))).one()
    assert run.status == "fallback" and "GROQ_API_KEY" in (run.error or "")


async def test_direct_tools_mode_skips_specialist_calls(
    llm_app: FastAPI, arjun: User, settings: Settings
) -> None:
    llm_app.state.settings = llm_app.state.settings.model_copy(update={"agent_direct_tools": True})
    fake = FakeLLM(
        [
            call("find_offers", {}),
            lambda m: call(
                "compose_response",
                {
                    "text": "Here are your offers.",
                    "cards": [{"type": "offer", "id": last_tool_result(m)["offers"][0]["id"]}],
                },
            ),
        ]
    )
    llm_app.state.llm = fake
    reply = await chat(llm_app, arjun, settings, "offers?")
    assert reply["agentsUsed"] == ["concierge", "deals"]
    assert reply["cards"][0]["type"] == "offer"
    assert len(fake.calls) == 2 and "find_offers" in fake.calls[0]["tools"]
