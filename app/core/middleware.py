"""Request context middleware: request IDs, access logs, security headers, last-resort 500s.

Written as plain ASGI (not `BaseHTTPMiddleware`) so the request-ID context variable is visible
to everything downstream and streaming responses aren't buffered.

It sits inside `CORSMiddleware`, so even the 500 it produces for an unhandled exception carries
CORS headers. Without them the browser would hide the response and the frontend would report a
network error instead of a server error.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response, server_error_response
from app.core.logging import request_id_var
from app.schemas.common import ErrorCode

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
#: The largest legitimate body (an 80-line grocery list) is a few KB.
MAX_BODY_BYTES = 64 * 1024
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: Paths that are polled constantly; their access lines go to DEBUG.
_QUIET_PATHS = frozenset({"/health", "/ready"})
#: Swagger UI loads its own scripts and styles, so it can't take the strict API policy.
_DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/openapi.json"})

_BASE_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
)
_API_CSP = "default-src 'none'; frame-ancestors 'none'"
_HSTS = "max-age=63072000; includeSubDomains"


def _incoming_request_id(scope: Scope) -> str:
    supplied = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if supplied and _VALID_REQUEST_ID.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope)
        token = request_id_var.set(request_id)
        declared = Headers(scope=scope).get("content-length")
        too_large = declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES
        path: str = scope.get("path", "")
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                for name, value in _BASE_SECURITY_HEADERS:
                    headers.setdefault(name, value)
                if path not in _DOCS_PATHS:
                    headers.setdefault("Content-Security-Policy", _API_CSP)
                    headers.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", _HSTS)
            await send(message)

        try:
            if too_large:
                await error_response(ErrorCode.BAD_REQUEST, "That request is too large.", 413)(
                    scope, receive, send_with_headers
                )
                return
            await self.app(scope, receive, send_with_headers)
        except Exception:
            logger.exception("unhandled_error", extra={"method": scope.get("method"), "path": path})
            if response_started:
                raise
            await server_error_response()(scope, receive, send_with_headers)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO
            logger.log(
                level,
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": path,
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
