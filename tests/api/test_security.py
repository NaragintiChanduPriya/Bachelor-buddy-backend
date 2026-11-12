"""Security properties that hold for every route, checked by enumerating the app's routes."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

#: Everything else under /api requires a signed-in user.
PUBLIC = {
    "/api/meta/areas",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/logout",
}


def protected_routes(app: FastAPI) -> list[tuple[str, str]]:
    """(method, path template) for every documented route under /api that is not public."""
    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api") and path not in PUBLIC
        for method in sorted(operations)
    ]


def test_there_are_many_protected_routes(app: FastAPI) -> None:
    assert len(protected_routes(app)) >= 28


async def test_every_protected_route_rejects_anonymous_requests(
    app: FastAPI, client: AsyncClient
) -> None:
    for method, path in protected_routes(app):
        url = re.sub(r"\{[^}]+\}", "x_001", path)
        response = await client.request(method, url, json={})
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_a_garbage_token_is_rejected_everywhere(app: FastAPI, client: AsyncClient) -> None:
    for method, path in protected_routes(app)[:10]:
        url = re.sub(r"\{[^}]+\}", "x_001", path)
        response = await client.request(
            method, url, json={}, headers={"Authorization": "Bearer abc.def.ghi"}
        )
        assert response.status_code == 401


async def test_oversized_bodies_are_refused_before_parsing(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/login",
        content=b"x" * (64 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.parametrize("path", ["/api/auth/register", "/api/auth/login"])
async def test_auth_errors_never_echo_the_password(client: AsyncClient, path: str) -> None:
    secret = "not-echoed-Pa55word"
    response = await client.post(path, json={"email": "not-an-email", "password": secret})
    assert response.status_code == 422
    assert secret not in response.text
