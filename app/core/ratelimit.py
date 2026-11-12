"""Rate limiting with slowapi (in-memory, per process).

Strict limits apply to the auth endpoints (per client IP) and to chat (per signed-in user),
because chat can spend LLM tokens. Limits come from RATE_LIMIT_AUTH and RATE_LIMIT_CHAT.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.core.errors import error_response
from app.core.security import peek_user_id
from app.schemas.common import ErrorCode


def client_key(request: Request) -> str:
    return f"ip:{get_remote_address(request)}"


def user_or_client_key(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        user_id = peek_user_id(header[7:], request.app.state.settings)
        if user_id is not None:
            return f"user:{user_id}"
    return client_key(request)


limiter = Limiter(key_func=client_key, storage_uri="memory://", headers_enabled=False)


def auth_limit() -> str:
    return get_settings().rate_limit_auth


def chat_limit() -> str:
    return get_settings().rate_limit_chat


async def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    retry_after = 60
    if isinstance(exc, RateLimitExceeded) and exc.limit is not None:
        retry_after = max(1, int(exc.limit.limit.get_expiry()))
    return error_response(
        ErrorCode.RATE_LIMITED,
        "You're going a little fast. Please wait a moment and try again.",
        429,
        {"retryAfterSeconds": retry_after},
        {"Retry-After": str(retry_after)},
    )
