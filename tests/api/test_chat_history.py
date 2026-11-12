"""GET/DELETE /chat/conversations: each user's own chat history, scoped and paginated."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.services.chat_history import shorten

pytestmark = pytest.mark.db


def data(response: Any) -> Any:
    body = response.json()
    assert response.status_code == 200 and body["success"] is True, body
    return body


async def say(http: AsyncClient, message: str, conversation: str | None = None) -> str:
    body = data(
        await http.post(
            "/api/chat/messages", json={"message": message, "conversationId": conversation}
        )
    )
    return str(body["data"]["conversationId"])


async def test_history_lists_open_and_delete(as_arjun: AsyncClient) -> None:
    first = await say(
        as_arjun, "give me hotels list nearby me in the order of lowest to highest prices"
    )
    await say(as_arjun, "Is delivery cheaper than going there?", first)
    second = await say(as_arjun, "what is my selected location")

    listed = data(await as_arjun.get("/api/chat/conversations"))
    ids = [c["id"] for c in listed["data"]]
    assert ids[:2] == [second, first]  # newest activity first
    assert listed["meta"]["total"] >= 2
    top = listed["data"][1]
    assert top["title"] == "give me hotels list nearby me in the order of lowest to…"
    assert top["messageCount"] == 4
    assert top["preview"]  # the latest reply, shortened

    detail = data(await as_arjun.get(f"/api/chat/conversations/{first}"))["data"]
    assert detail["id"] == first
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    reply = detail["messages"][1]
    assert reply["cards"] and reply["cards"][0]["type"] == "food"
    assert reply["agentsUsed"] and reply["suggestedFollowUps"]
    assert detail["messages"][0]["cards"] == []

    page = data(await as_arjun.get("/api/chat/conversations", params={"pageSize": 1, "page": 2}))
    assert [c["id"] for c in page["data"]] == [first]
    assert page["meta"] == {"page": 2, "pageSize": 1, "total": listed["meta"]["total"]}

    deleted = data(await as_arjun.delete(f"/api/chat/conversations/{first}"))["data"]
    assert deleted == {"deleted": True, "conversationId": first}
    gone = await as_arjun.get(f"/api/chat/conversations/{first}")
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "NOT_FOUND"
    after = data(await as_arjun.get("/api/chat/conversations"))
    assert first not in [c["id"] for c in after["data"]]


async def test_a_conversation_belongs_to_one_user(as_arjun: AsyncClient, api: AsyncClient) -> None:
    mine = await say(as_arjun, "what is my salary")
    registered = data(
        await api.post(
            "/api/auth/register",
            json={
                "name": "Other Person",
                "email": "other.person@example.com",
                "password": "budget2026",
                "age": 27,
                "occupation": "Designer",
            },
        )
    )["data"]
    other = {"Authorization": f"Bearer {registered['tokens']['accessToken']}"}
    data(
        await api.post(
            "/api/onboarding",
            headers=other,
            json={
                "salary": 30000,
                "savingsGoal": 5000,
                "homeAreaId": "area_btm",
                "officeAreaId": "area_btm",
                "techParkId": None,
                "foodPreference": "veg",
                "cards": [],
            },
        )
    )

    assert (await api.get(f"/api/chat/conversations/{mine}", headers=other)).status_code == 404
    assert (await api.delete(f"/api/chat/conversations/{mine}", headers=other)).status_code == 404
    theirs = data(await api.get("/api/chat/conversations", headers=other))
    assert theirs["data"] == [] and theirs["meta"]["total"] == 0
    # Still there for its owner.
    assert (await as_arjun.get(f"/api/chat/conversations/{mine}")).status_code == 200


@pytest.mark.parametrize("bad", ["conv_999999", "abc", "exp_001", "conv_"])
async def test_unknown_conversations_are_not_found(as_arjun: AsyncClient, bad: str) -> None:
    response = await as_arjun.get(f"/api/chat/conversations/{bad}")
    assert response.status_code == 404


def test_titles_are_one_short_line() -> None:
    assert shorten("  hello\n  there ", 60) == "hello there"
    assert shorten("word " * 30, 20) == "word word word word…"
    assert len(shorten("x" * 200, 60)) == 60
