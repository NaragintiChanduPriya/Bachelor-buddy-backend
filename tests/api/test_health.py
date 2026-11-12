from __future__ import annotations

import asyncio
import re

from httpx import AsyncClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.db.session import Database
from app.factory import create_app
from tests.conftest import make_client


class HealthyDatabase(Database):
    async def ping(self) -> None:
        return None


class DownDatabase(Database):
    async def ping(self) -> None:
        raise ConnectionRefusedError("connection refused")


class HangingDatabase(Database):
    async def ping(self) -> None:
        await asyncio.sleep(60)


async def test_health_returns_the_envelope(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["meta"] is None
    assert body["data"]["status"] == "ok"
    assert body["data"]["version"] == "0.1.0"
    assert body["data"]["serverNow"] == "2026-11-15T07:00:00.000Z"


async def test_every_response_carries_request_id_and_security_headers(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in response.headers  # HSTS only in production


async def test_a_valid_incoming_request_id_is_kept(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "trace-abc_123.4"})
    assert response.headers["x-request-id"] == "trace-abc_123.4"


async def test_an_unsafe_incoming_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "bad id\twith spaces" * 5})
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


async def test_ready_when_the_database_answers(settings: Settings, clock: FixedClock) -> None:
    db = HealthyDatabase(settings.database_url.get_secret_value())
    async with await make_client(create_app(settings, database=db, clock=clock)) as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ready", "checks": {"database": "ok"}}


async def test_not_ready_when_the_database_is_down(settings: Settings, clock: FixedClock) -> None:
    db = DownDatabase(settings.database_url.get_secret_value())
    async with await make_client(create_app(settings, database=db, clock=clock)) as client:
        response = await client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"] == {
        "code": "SERVER_ERROR",
        "message": "The database is not reachable.",
        "details": {"database": "unavailable"},
    }


async def test_not_ready_when_the_database_hangs(settings: Settings, clock: FixedClock) -> None:
    fast = settings.model_copy(update={"db_ready_timeout_seconds": 0.05})
    db = HangingDatabase(settings.database_url.get_secret_value())
    async with await make_client(create_app(fast, database=db, clock=clock)) as client:
        response = await client.get("/ready")
    assert response.status_code == 503


async def test_hsts_is_sent_in_production(settings: Settings, clock: FixedClock) -> None:
    prod = settings.model_copy(update={"app_env": "production"})
    async with await make_client(create_app(prod, clock=clock)) as client:
        response = await client.get("/health")
    assert response.headers["strict-transport-security"].startswith("max-age=")


async def test_docs_load_without_the_strict_api_policy(client: AsyncClient) -> None:
    docs = await client.get("/docs")
    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers  # Swagger UI needs its scripts
    schema = (await client.get("/openapi.json")).json()
    assert schema["info"]["title"] == "BachelorBuddy API"
    assert {"/health", "/ready"} <= set(schema["paths"])
