"""Errors and the handlers that turn every failure into the error envelope.

Services raise an `AppError` subclass with a user-facing message; the handlers below render it.
Framework errors (unknown route, wrong method, request validation) are mapped onto the same
envelope, so the frontend's API client only ever sees one shape.

Validation errors never echo the submitted value back, so a rejected password can't leak into a
response or a log.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ErrorBody, ErrorCode, ErrorEnvelope

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base for every error a service raises on purpose. The message is shown to the user."""

    code: ClassVar[ErrorCode] = ErrorCode.SERVER_ERROR
    status_code: ClassVar[int] = 500

    def __init__(
        self,
        message: str,
        details: Any = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = dict(headers or {})


class NotFoundError(AppError):
    code = ErrorCode.NOT_FOUND
    status_code = 404

    @classmethod
    def resource(cls, what: str) -> NotFoundError:
        """`NotFoundError.resource("Food listing")` -> "Food listing was not found."."""
        return cls(f"{what} was not found.")


class ValidationFailedError(AppError):
    """A request body that parsed but breaks a business rule (422)."""

    code = ErrorCode.VALIDATION_ERROR
    status_code = 422


class BadRequestError(AppError):
    """Malformed or contradictory query or path parameters (400)."""

    code = ErrorCode.BAD_REQUEST
    status_code = 400


class ConflictError(AppError):
    code = ErrorCode.CONFLICT
    status_code = 409


class UnauthorizedError(AppError):
    code = ErrorCode.UNAUTHORIZED
    status_code = 401

    def __init__(self, message: str = "Please sign in again.", details: Any = None) -> None:
        super().__init__(message, details, headers={"WWW-Authenticate": "Bearer"})


class RateLimitedError(AppError):
    code = ErrorCode.RATE_LIMITED
    status_code = 429

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        super().__init__(
            message,
            {"retryAfterSeconds": retry_after_seconds},
            headers={"Retry-After": str(retry_after_seconds)},
        )


class ServiceUnavailableError(AppError):
    """A dependency (the database, the LLM) is down. Retryable, so it keeps SERVER_ERROR."""

    code = ErrorCode.SERVER_ERROR
    status_code = 503


def error_response(
    code: ErrorCode,
    message: str,
    status_code: int,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(
        envelope.model_dump(mode="json", by_alias=True),
        status_code=status_code,
        headers=dict(headers or {}),
    )


def server_error_response() -> JSONResponse:
    return error_response(
        ErrorCode.SERVER_ERROR,
        "Something went wrong on our side. Please try again.",
        500,
    )


# ------------------------------------------------------------------ request validation


def _field_path(loc: Sequence[int | str]) -> str:
    # loc[0] is where the value came from ("body", "query", "path", "header").
    parts = [str(part) for part in loc[1:]]
    return ".".join(parts) if parts else str(loc[0]) if loc else ""


def describe_validation_errors(
    errors: Sequence[Mapping[str, Any]],
) -> tuple[ErrorCode, int, str, dict[str, Any]]:
    """Map pydantic errors to (code, status, message, details) without echoing input values.

    A bad body is a VALIDATION_ERROR (422), as the contract specifies for body validation.
    Bad query, path or header values are a BAD_REQUEST (400).
    """
    fields: list[dict[str, str]] = []
    from_body = False
    for err in errors:
        loc: Sequence[int | str] = err.get("loc", ())
        if loc and loc[0] == "body":
            from_body = True
        raw = str(err.get("msg", "Invalid value"))
        fields.append(
            {
                "field": _field_path(loc),
                # Our validators raise ValueError with a sentence written for the user.
                "message": raw.removeprefix("Value error, "),
                "type": str(err.get("type", "value_error")),
            }
        )

    if any(f["type"] == "json_invalid" for f in fields):
        message = "The request body is not valid JSON."
    elif fields:
        first = fields[0]
        # A custom message is already a full sentence; a generic one needs the field name.
        if first["type"] == "value_error" or first["field"] in {"", "body"}:
            message = first["message"]
        else:
            message = f"{first['field']}: {first['message']}"
        if len(fields) > 1:
            message += f" (and {len(fields) - 1} more)"
    else:
        message = "The request is not valid."

    if from_body:
        return ErrorCode.VALIDATION_ERROR, 422, message, {"fields": fields}
    return ErrorCode.BAD_REQUEST, 400, message, {"fields": fields}


# ------------------------------------------------------------------ handlers


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # registered for AppError only; narrows the type
        raise exc
    if exc.status_code >= 500:
        logger.warning("app_error", extra={"code": exc.code.value, "status": exc.status_code})
    return error_response(exc.code, exc.message, exc.status_code, exc.details, exc.headers)


async def _handle_request_validation(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    code, status_code, message, details = describe_validation_errors(exc.errors())
    return error_response(code, message, status_code, details)


_HTTP_STATUS_MESSAGES: dict[int, tuple[ErrorCode, str]] = {
    401: (ErrorCode.UNAUTHORIZED, "Please sign in again."),
    404: (ErrorCode.NOT_FOUND, "We could not find that."),
    405: (ErrorCode.BAD_REQUEST, "That method is not allowed on this endpoint."),
    429: (ErrorCode.RATE_LIMITED, "Too many requests. Please slow down."),
}


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    status_code = exc.status_code
    if status_code in _HTTP_STATUS_MESSAGES:
        code, message = _HTTP_STATUS_MESSAGES[status_code]
    elif status_code >= 500:
        code, message = ErrorCode.SERVER_ERROR, "Something went wrong on our side."
    else:
        code, message = ErrorCode.BAD_REQUEST, "That request was not valid."
    return error_response(code, message, status_code, None, exc.headers)


def install_exception_handlers(app: FastAPI) -> None:
    """Register the envelope handlers. Unhandled exceptions are caught by the request
    middleware instead, so the 500 response still carries the CORS and request-ID headers."""
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
