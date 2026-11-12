"""Auth, onboarding, preferences and per-user data isolation (against the seeded test DB)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.config import Settings
from tests.conftest import DEMO_EMAIL, make_client

pytestmark = pytest.mark.db

NEW_USER = {
    "name": "Meera Iyer",
    "email": "Meera.Iyer@Example.com",
    "password": "budget2026",
    "age": 26,
    "occupation": "Data Analyst",
}
ONBOARDING = {
    "salary": 52000,
    "savingsGoal": 10000,
    "homeAreaId": "area_btm",
    "officeAreaId": "area_bellandur",
    "techParkId": "park_orbit",
    "foodPreference": "veg",
    "cards": [{"id": "card_sbi_dc", "bank": "SBI", "type": "debit", "label": "SBI Debit Card"}],
}


def data(response: Any) -> Any:
    body = response.json()
    assert body["success"] is True, body
    return body["data"]


def error(response: Any) -> dict[str, Any]:
    body = response.json()
    assert body["success"] is False and body["data"] is None
    return body["error"]  # type: ignore[no-any-return]


async def register(api: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await api.post("/api/auth/register", json={**NEW_USER, **overrides})
    assert response.status_code == 200, response.text
    return data(response)  # type: ignore[no-any-return]


async def test_login_returns_tokens_and_the_user(api: AsyncClient, settings: Settings) -> None:
    assert settings.demo_user_password is not None
    response = await api.post(
        "/api/auth/login",
        json={
            "email": DEMO_EMAIL.upper(),
            "password": settings.demo_user_password.get_secret_value(),
        },
    )
    body = data(response)
    assert body["user"]["email"] == DEMO_EMAIL
    assert body["user"]["onboarded"] is True
    assert body["tokens"]["tokenType"] == "bearer"
    assert body["tokens"]["expiresIn"] == settings.jwt_access_token_expire_minutes * 60


async def test_bad_credentials_get_one_generic_answer(api: AsyncClient) -> None:
    for email in (DEMO_EMAIL, "nobody@example.com"):
        response = await api.post(
            "/api/auth/login", json={"email": email, "password": "wrong-pass1"}
        )
        assert response.status_code == 401
        assert error(response) == {
            "code": "UNAUTHORIZED",
            "message": "Email or password is incorrect.",
            "details": None,
        }


async def test_endpoints_need_a_token(api: AsyncClient) -> None:
    for path in ("/api/me", "/api/budget/current", "/api/expenses", "/api/notifications"):
        response = await api.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert error(response)["code"] == "UNAUTHORIZED"
    # Reference data stays public.
    assert (await api.get("/api/meta/areas")).status_code == 200


async def test_register_validates_and_rejects_duplicates(api: AsyncClient) -> None:
    created = await register(api)
    assert created["user"]["email"] == "meera.iyer@example.com"
    assert created["user"]["onboarded"] is False
    assert created["user"]["avatarInitials"] == "MI"
    assert created["user"]["preferences"]["homeAreaId"] == ""
    duplicate = await api.post("/api/auth/register", json=NEW_USER)
    assert duplicate.status_code == 409 and error(duplicate)["code"] == "CONFLICT"
    weak = await api.post(
        "/api/auth/register", json={**NEW_USER, "email": "x@example.com", "password": "letters"}
    )
    assert weak.status_code == 422
    assert error(weak)["message"] == "Use at least 8 characters for your password."
    young = await api.post(
        "/api/auth/register", json={**NEW_USER, "email": "y@example.com", "age": 12}
    )
    assert error(young)["message"] == "Enter an age between 16 and 100."


async def test_refresh_rotates_and_detects_reuse(api: AsyncClient) -> None:
    tokens = (await register(api))["tokens"]
    first = await api.post("/api/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    rotated = data(first)
    assert rotated["refreshToken"] != tokens["refreshToken"]
    # The old token was rotated away; presenting it again means it leaked.
    reuse = await api.post("/api/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert reuse.status_code == 401
    # ...so the whole family is revoked, including the newest token.
    after = await api.post("/api/auth/refresh", json={"refreshToken": rotated["refreshToken"]})
    assert after.status_code == 401


async def test_logout_revokes_the_refresh_token(api: AsyncClient) -> None:
    tokens = (await register(api))["tokens"]
    assert data(
        await api.post("/api/auth/logout", json={"refreshToken": tokens["refreshToken"]})
    ) == {"loggedOut": True}
    response = await api.post("/api/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert response.status_code == 401
    # Unknown tokens are accepted silently (no information leak).
    assert (await api.post("/api/auth/logout", json={"refreshToken": "x" * 40})).status_code == 200


async def test_onboarding_flow_for_a_new_user(db_app: FastAPI, api: AsyncClient) -> None:
    access = (await register(api))["tokens"]["accessToken"]
    async with await make_client(db_app, {"Authorization": f"Bearer {access}"}) as me:
        blocked = await me.get("/api/budget/current")
        assert blocked.status_code == 409
        assert error(blocked)["details"] == {"onboarded": False}

        bad = await me.post("/api/onboarding", json={**ONBOARDING, "savingsGoal": 60000})
        assert error(bad)["message"] == "Your savings goal must be less than your salary."
        unknown = await me.post("/api/onboarding", json={**ONBOARDING, "homeAreaId": "area_mars"})
        assert error(unknown)["message"] == "Choose a valid home area."
        low = await me.post("/api/onboarding", json={**ONBOARDING, "salary": 4000})
        assert low.status_code == 422

        done = data(await me.post("/api/onboarding", json=ONBOARDING))
        assert done["user"]["onboarded"] is True
        assert done["user"]["preferences"]["homeAreaName"] == "BTM Layout"
        assert done["user"]["preferences"]["techParkName"] == "Orbit Tech Campus"
        assert done["budget"]["totalLimit"] == 52000
        assert done["budget"]["totalSpent"] == 0
        limits = {c["id"]: c["limit"] for c in done["budget"]["categories"]}
        assert limits["savings"] == 10000 and sum(limits.values()) == 52000

        changed = data(await me.put("/api/me/preferences", json={"salary": 60000}))
        assert changed["preferences"]["salary"] == 60000
        assert changed["preferences"]["homeAreaId"] == "area_btm"  # omitted fields kept
        budget = data(await me.get("/api/budget/current"))
        assert budget["totalLimit"] == 60000  # limits regenerated
        cleared = data(await me.put("/api/me/preferences", json={"techParkId": None}))
        assert cleared["preferences"]["techParkId"] is None


async def test_users_never_see_each_others_data(
    db_app: FastAPI, api: AsyncClient, as_arjun: AsyncClient
) -> None:
    arjun_expense = data(
        await as_arjun.post(
            "/api/expenses", json={"category": "food", "title": "Dosa", "amount": 60}
        )
    )["expense"]["id"]
    access = (await register(api))["tokens"]["accessToken"]
    async with await make_client(db_app, {"Authorization": f"Bearer {access}"}) as other:
        await other.post("/api/onboarding", json=ONBOARDING)
        stolen = await other.delete(f"/api/expenses/{arjun_expense}")
        assert stolen.status_code == 404
        assert data(await other.get("/api/expenses"))["filteredTotal"] == 0
        assert data(await other.get("/api/notifications"))["items"] == []
        assert data(await other.get("/api/products/alerts")) == []
    assert (await as_arjun.delete(f"/api/expenses/{arjun_expense}")).status_code == 200


async def test_dev_bypass_is_off_unless_configured(db_app: FastAPI, settings: Settings) -> None:
    assert settings.dev_auth_bypass_email is None
    db_app.state.settings = settings.model_copy(update={"dev_auth_bypass_email": DEMO_EMAIL})
    async with await make_client(db_app) as anonymous:
        assert data(await anonymous.get("/api/me"))["email"] == DEMO_EMAIL


async def test_auth_endpoints_are_rate_limited(db_app: FastAPI, settings: Settings) -> None:
    from app.core.ratelimit import limiter

    limiter.reset()
    limiter.enabled = True
    try:
        async with await make_client(db_app) as http:
            statuses = [
                (
                    await http.post(
                        "/api/auth/login", json={"email": "a@b.co", "password": "x1234567"}
                    )
                ).status_code
                for _ in range(12)
            ]
        assert statuses[:10] == [401] * 10
        assert statuses[10] == 429
    finally:
        limiter.enabled = False
        limiter.reset()
