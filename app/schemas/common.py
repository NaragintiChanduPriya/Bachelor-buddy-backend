"""Shared schema building blocks: camelCase models, UTC timestamps and the response envelope.

Every response has the shape the frontend's `src/types/api.ts` expects:

    { "success": true,  "data": ..., "meta": {page, pageSize, total} | null, "error": null }
    { "success": false, "data": null, "meta": null, "error": {code, message, details} }
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Snake_case in Python, camelCase on the wire. Accepts either on input."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        from_attributes=True,
    )


def to_iso_utc(value: datetime) -> str:
    """`2026-11-15T07:00:00.000Z`: UTC, millisecond precision, `Z` suffix, like `toISOString()`."""
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


#: A timezone-aware instant, serialized exactly like JavaScript's `Date.toISOString()`.
#: Naive datetimes are rejected on input, so a missing offset can never be guessed.
UtcDateTime = Annotated[
    AwareDatetime, PlainSerializer(to_iso_utc, return_type=str, when_used="json")
]


class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    BAD_REQUEST = "BAD_REQUEST"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"


class PaginationMeta(CamelModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


class ErrorBody(CamelModel):
    code: ErrorCode
    message: str
    details: Any = None


class Envelope[T](CamelModel):
    """A successful response."""

    success: Literal[True] = True
    data: T
    meta: PaginationMeta | None = None
    error: None = None


class ErrorEnvelope(CamelModel):
    """A failed response."""

    success: Literal[False] = False
    data: None = None
    meta: None = None
    error: ErrorBody


def ok[T](data: T, meta: PaginationMeta | None = None) -> Envelope[T]:
    """Wrap a payload in the success envelope."""
    return Envelope[T](data=data, meta=meta)
