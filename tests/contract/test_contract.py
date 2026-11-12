"""Contract tests: live responses validated against the frontend's own TypeScript types, and every
endpoint in the frontend's API_CONTRACT.md present in this API.

Skipped when the frontend repository is not next to this one (../Bachelor-buddy).
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.config import PROJECT_ROOT
from tests.contract.ts_types import TypeRegistry

FRONTEND = PROJECT_ROOT.parent / "Bachelor-buddy"
TYPES_DIR = FRONTEND / "src" / "types"
CONTRACT = FRONTEND / "API_CONTRACT.md"

pytestmark = pytest.mark.skipif(
    not TYPES_DIR.is_dir(), reason="frontend repo not found next to the backend"
)


@pytest.fixture(scope="module")
def types() -> TypeRegistry:
    return TypeRegistry.load(TYPES_DIR)


def test_the_reader_understands_the_frontend_types(types: TypeRegistry) -> None:
    for name in (
        "User",
        "Budget",
        "FoodListing",
        "ProductDetail",
        "HomeDetail",
        "ChatReply",
        "OffersResponse",
    ):
        assert name in types.interfaces, name
    assert "menu" in types.fields_of("FoodListing")
    assert "id" in types.fields_of("FoodListing")  # inherited from FoodListingSummary
    assert (
        types.validate(
            {
                "id": "food",
                "label": "Food",
                "limit": 1,
                "spent": 0,
                "remaining": 1,
                "percentUsed": 0,
                "status": "ok",
            },
            "BudgetCategory",
        )
        == []
    )
    assert types.validate({"id": "pets"}, "BudgetCategory")  # wrong literal and missing fields
    assert types.validate(
        {"quickCommerce": 1, "supermarket": 1, "kirana": 1}, "Record<StoreType, number>"
    )


def test_every_contract_endpoint_exists(app: FastAPI) -> None:
    """Every '### ✅|🆕 METHOD /path' heading in API_CONTRACT.md is served under /api."""
    if not CONTRACT.is_file():
        pytest.skip("API_CONTRACT.md not found")
    headings = re.findall(
        r"^### (?:✅|🆕) (GET|POST|PUT|PATCH|DELETE) (\S+)",
        CONTRACT.read_text(encoding="utf-8"),
        flags=re.M,
    )
    assert len(headings) >= 30
    served = {
        (method.upper(), re.sub(r"\{[^}]+\}", "{}", path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    missing = [
        f"{method} {path}"
        for method, path in headings
        if (method, "/api" + re.sub(r":\w+", "{}", path)) not in served
    ]
    assert missing == []


def ok_data(response: Any) -> Any:
    body = response.json()
    assert response.status_code == 200, body
    assert set(body) == {"success", "data", "meta", "error"}
    return body


GETS = [
    ("/api/meta/areas", "AreasResponse", False),
    ("/api/me", "User", False),
    ("/api/budget/current", "Budget", False),
    ("/api/expenses?pageSize=50", "ExpenseListResponse", True),
    ("/api/food/nearby?pageSize=50&near=office", "FoodListingSummary[]", True),
    ("/api/food/food_019", "FoodListing", False),
    ("/api/groceries/catalog", "GroceryCatalogItem[]", False),
    ("/api/groceries/list", "GroceryList", False),
    ("/api/groceries/compare", "GroceryComparison", False),
    ("/api/products/search?pageSize=50", "ProductSummary[]", True),
    ("/api/products/prod_001", "ProductDetail", False),
    ("/api/products/prod_009", "ProductDetail", False),
    ("/api/products/prod_055/price-history", "PriceHistory", False),
    ("/api/products/alerts", "PriceAlert[]", False),
    ("/api/offers?eligibleOnly=false", "OffersResponse", False),
    ("/api/homes/search?pageSize=50", "HomeSearchResponse", True),
    ("/api/homes/home_001", "HomeDetail", False),
    ("/api/savings/monthly", "MonthlySavings", False),
    ("/api/savings/history", "SavingsHistory", False),
    ("/api/notifications", "NotificationsResponse", False),
]


@pytest.mark.db
@pytest.mark.parametrize(("path", "type_", "paginated"), GETS, ids=[g[0] for g in GETS])
async def test_get_responses_match_the_frontend_types(
    as_arjun: AsyncClient, types: TypeRegistry, path: str, type_: str, paginated: bool
) -> None:
    body = ok_data(await as_arjun.get(path))
    assert types.validate(body["data"], type_) == []
    if paginated:
        assert types.validate(body["meta"], "PaginationMeta") == []
    else:
        assert body["meta"] is None


@pytest.mark.db
async def test_delivery_comparison_matches(as_arjun: AsyncClient, types: TypeRegistry) -> None:
    listings = ok_data(
        await as_arjun.get("/api/food/nearby", params={"pageSize": 50, "type": "tiffin"})
    )["data"]
    body = ok_data(await as_arjun.get(f"/api/food/{listings[0]['id']}/compare-delivery"))
    assert types.validate(body["data"], "DeliveryComparison") == []


@pytest.mark.db
async def test_write_responses_match_the_frontend_types(
    as_arjun: AsyncClient, types: TypeRegistry
) -> None:
    created = ok_data(
        await as_arjun.post(
            "/api/expenses", json={"category": "misc", "title": "Haircut", "amount": 150}
        )
    )
    assert types.validate(created["data"], "CreateExpenseResponse") == []
    deleted = ok_data(await as_arjun.delete(f"/api/expenses/{created['data']['expense']['id']}"))
    assert types.validate(deleted["data"], "{ id: string; category: BudgetCategory }") == []
    budget = ok_data(
        await as_arjun.put(
            "/api/budget/current",
            json={"categories": [{"id": "food", "limit": 7600}, {"id": "misc", "limit": 1900}]},
        )
    )
    assert types.validate(budget["data"], "Budget") == []
    grocery = ok_data(
        await as_arjun.put(
            "/api/groceries/list", json={"items": [{"itemId": "groc_001", "quantity": 2}]}
        )
    )
    assert types.validate(grocery["data"], "GroceryList") == []
    product = ok_data(await as_arjun.get("/api/products/prod_100"))["data"]
    alert = ok_data(
        await as_arjun.post(
            "/api/products/prod_100/price-alert", json={"targetPrice": product["lowestPrice"] - 50}
        )
    )
    assert types.validate(alert["data"], "PriceAlert") == []
    notifications = ok_data(await as_arjun.patch("/api/notifications/read-all"))
    assert types.validate(notifications["data"], "NotificationsResponse") == []
    prefs = ok_data(
        await as_arjun.put("/api/me/preferences", json={"foodPreference": "eggetarian"})
    )
    assert types.validate(prefs["data"], "User") == []


@pytest.mark.db
@pytest.mark.parametrize(
    "message",
    [
        "I have ₹150 and I'm hungry near office",
        "Formal shoes under ₹1,500 for an interview on Friday",
        "How much did I spend on food this month?",
        "Cheapest way to buy groceries this month",
        "Find a PG under ₹10,000 near Marathahalli",
        "What offers can I use on my cards?",
    ],
)
async def test_chat_replies_match_the_frontend_types(
    as_arjun: AsyncClient, types: TypeRegistry, message: str
) -> None:
    body = ok_data(await as_arjun.post("/api/chat/messages", json={"message": message}))
    assert body["data"]["cards"]
    assert types.validate(body["data"], "ChatReply") == []


@pytest.mark.db
async def test_chat_history_matches_the_frontend_types(
    as_arjun: AsyncClient, types: TypeRegistry
) -> None:
    sent = ok_data(
        await as_arjun.post(
            "/api/chat/messages", json={"message": "Show places to eat near me, cheapest first"}
        )
    )["data"]
    listed = ok_data(await as_arjun.get("/api/chat/conversations"))
    assert types.validate(listed["data"], "ConversationSummary[]") == []
    assert types.validate(listed["meta"], "PaginationMeta") == []
    detail = ok_data(await as_arjun.get(f"/api/chat/conversations/{sent['conversationId']}"))
    assert types.validate(detail["data"], "ConversationDetail") == []
    assert detail["meta"] is None
    deleted = ok_data(await as_arjun.delete(f"/api/chat/conversations/{sent['conversationId']}"))
    assert types.validate(deleted["data"], "DeleteConversationResponse") == []


@pytest.mark.db
async def test_auth_responses_match_the_frontend_types(
    api: AsyncClient, types: TypeRegistry
) -> None:
    """The sign-in flow the frontend implements (src/types/auth.ts)."""
    registered = ok_data(
        await api.post(
            "/api/auth/register",
            json={
                "name": "Contract Check",
                "email": "contract.check@example.com",
                "password": "budget2026",
                "age": 25,
                "occupation": "QA Engineer",
            },
        )
    )["data"]
    assert types.validate(registered, "AuthResponse") == []

    tokens = registered["tokens"]
    refreshed = ok_data(
        await api.post("/api/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    )["data"]
    assert types.validate(refreshed, "AuthTokens") == []

    logged_out = ok_data(
        await api.post("/api/auth/logout", json={"refreshToken": refreshed["refreshToken"]})
    )["data"]
    assert types.validate(logged_out, "LogoutResponse") == []

    wrong = await api.post(
        "/api/auth/login", json={"email": "contract.check@example.com", "password": "wrong-pass1"}
    )
    assert wrong.status_code == 401
    assert types.validate(wrong.json(), "ApiErrorEnvelope") == []


@pytest.mark.db
async def test_error_envelope_matches(as_arjun: AsyncClient, types: TypeRegistry) -> None:
    body = (await as_arjun.get("/api/food/food_999")).json()
    assert types.validate(body, "ApiErrorEnvelope") == []
    bad = (await as_arjun.get("/api/expenses", params={"month": "x"})).json()
    assert types.validate(bad, "ApiErrorEnvelope") == []
