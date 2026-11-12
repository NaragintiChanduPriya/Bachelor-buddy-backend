"""Every failure path renders the same error envelope the frontend's API client expects."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI, Query
from httpx import AsyncClient
from pydantic import Field

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.errors import (
    ConflictError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
)
from app.factory import create_app
from app.schemas.common import CamelModel, Envelope, ok
from tests.conftest import FRONTEND_ORIGIN, make_client

SUBMITTED_SECRET = "hunter2-do-not-echo"


class CreateBody(CamelModel):
    amount: int = Field(gt=0)
    password: str = Field(min_length=30)


def build_app(settings: Settings, clock: FixedClock) -> FastAPI:
    app = create_app(settings, clock=clock)
    router = APIRouter()

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    @router.get("/missing")
    async def missing() -> None:
        raise NotFoundError.resource("Food listing")

    @router.get("/conflict")
    async def conflict() -> None:
        raise ConflictError("You already have an alert for this product.")

    @router.get("/limited")
    async def limited() -> None:
        raise RateLimitedError("Slow down a little.", retry_after_seconds=30)

    @router.get("/unauthorized")
    async def unauthorized() -> None:
        raise UnauthorizedError()

    @router.get("/items")
    async def list_items(page: int = Query(1, ge=1)) -> Envelope[int]:
        return ok(page)

    @router.post("/items")
    async def create_item(body: CreateBody) -> Envelope[int]:
        return ok(body.amount)

    app.include_router(router, prefix="/api/test")
    return app


@pytest.fixture
async def http(settings: Settings, clock: FixedClock) -> AsyncIterator[AsyncClient]:
    async with await make_client(build_app(settings, clock)) as client:
        yield client


def error_of(body: dict[str, object]) -> dict[str, object]:
    assert body["success"] is False
    assert body["data"] is None
    assert body["meta"] is None
    error = body["error"]
    assert isinstance(error, dict)
    return error


async def test_unknown_route_is_not_found(http: AsyncClient) -> None:
    response = await http.get("/api/nope")
    assert response.status_code == 404
    assert error_of(response.json())["code"] == "NOT_FOUND"


async def test_wrong_method_is_a_bad_request(http: AsyncClient) -> None:
    response = await http.delete("/health")
    assert response.status_code == 405
    assert error_of(response.json())["code"] == "BAD_REQUEST"


async def test_not_found_error_message(http: AsyncClient) -> None:
    response = await http.get("/api/test/missing")
    assert response.status_code == 404
    assert error_of(response.json()) == {
        "code": "NOT_FOUND",
        "message": "Food listing was not found.",
        "details": None,
    }


async def test_conflict(http: AsyncClient) -> None:
    response = await http.get("/api/test/conflict")
    assert response.status_code == 409
    assert error_of(response.json())["code"] == "CONFLICT"


async def test_rate_limited_sets_retry_after(http: AsyncClient) -> None:
    response = await http.get("/api/test/limited")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    error = error_of(response.json())
    assert error["code"] == "RATE_LIMITED"
    assert error["details"] == {"retryAfterSeconds": 30}


async def test_unauthorized_asks_for_a_bearer_token(http: AsyncClient) -> None:
    response = await http.get("/api/test/unauthorized")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert error_of(response.json())["code"] == "UNAUTHORIZED"


async def test_bad_query_parameter_is_a_400(http: AsyncClient) -> None:
    response = await http.get("/api/test/items", params={"page": 0})
    assert response.status_code == 400
    error = error_of(response.json())
    assert error["code"] == "BAD_REQUEST"
    assert isinstance(error["details"], dict)
    assert error["details"]["fields"][0]["field"] == "page"


async def test_bad_body_is_a_422_and_never_echoes_the_input(http: AsyncClient) -> None:
    response = await http.post("/api/test/items", json={"amount": -5, "password": SUBMITTED_SECRET})
    assert response.status_code == 422
    error = error_of(response.json())
    assert error["code"] == "VALIDATION_ERROR"
    assert isinstance(error["details"], dict)
    assert {f["field"] for f in error["details"]["fields"]} == {"amount", "password"}
    assert SUBMITTED_SECRET not in response.text


async def test_malformed_json_body(http: AsyncClient) -> None:
    response = await http.post(
        "/api/test/items",
        content=b'{"amount": 5,',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert error_of(response.json())["message"] == "The request body is not valid JSON."


async def test_valid_body_passes_through_camel_case(http: AsyncClient) -> None:
    response = await http.post("/api/test/items", json={"amount": 120, "password": "x" * 30})
    assert response.status_code == 200
    assert response.json() == {"success": True, "data": 120, "meta": None, "error": None}


async def test_unhandled_exception_is_a_generic_500_with_cors_and_request_id(
    http: AsyncClient,
) -> None:
    response = await http.get("/api/test/boom", headers={"Origin": FRONTEND_ORIGIN})
    assert response.status_code == 500
    error = error_of(response.json())
    assert error["code"] == "SERVER_ERROR"
    assert "internal detail" not in response.text
    assert "Traceback" not in response.text
    assert response.headers["x-request-id"]
    # Without this header the browser would hide the response and show a network error.
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


async def test_cors_preflight_allows_the_frontend_origin(http: AsyncClient) -> None:
    response = await http.options(
        "/api/test/items",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed


async def test_cors_rejects_other_origins(http: AsyncClient) -> None:
    response = await http.options(
        "/api/test/items",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
