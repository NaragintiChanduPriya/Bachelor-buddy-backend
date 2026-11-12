from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.errors import describe_validation_errors
from app.schemas.common import (
    CamelModel,
    ErrorBody,
    ErrorCode,
    ErrorEnvelope,
    PaginationMeta,
    UtcDateTime,
    ok,
    to_iso_utc,
)

IST = ZoneInfo("Asia/Kolkata")


class Sample(CamelModel):
    page_size: int
    spent_at: UtcDateTime


def test_camel_case_on_the_wire_and_either_case_on_input() -> None:
    by_alias = Sample.model_validate({"pageSize": 3, "spentAt": "2026-11-15T07:00:00.000Z"})
    by_name = Sample.model_validate({"page_size": 3, "spent_at": "2026-11-15T07:00:00Z"})
    assert by_alias == by_name
    assert by_alias.model_dump(mode="json") == {
        "pageSize": 3,
        "spentAt": "2026-11-15T07:00:00.000Z",
    }


def test_iso_format_matches_javascript_to_iso_string() -> None:
    assert to_iso_utc(datetime(2026, 11, 15, 12, 30, tzinfo=IST)) == "2026-11-15T07:00:00.000Z"
    assert to_iso_utc(datetime(2026, 11, 15, 7, 0, 0, 123456, tzinfo=UTC)) == (
        "2026-11-15T07:00:00.123Z"
    )


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Sample.model_validate({"pageSize": 1, "spentAt": "2026-11-15T07:00:00"})


def test_success_envelope_shape() -> None:
    assert ok({"a": 1}).model_dump(mode="json") == {
        "success": True,
        "data": {"a": 1},
        "meta": None,
        "error": None,
    }
    paged = ok([1, 2], PaginationMeta(page=2, page_size=12, total=40))
    assert paged.model_dump(mode="json")["meta"] == {"page": 2, "pageSize": 12, "total": 40}


def test_error_envelope_shape() -> None:
    envelope = ErrorEnvelope(
        error=ErrorBody(code=ErrorCode.NOT_FOUND, message="Food listing was not found.")
    )
    assert envelope.model_dump(mode="json") == {
        "success": False,
        "data": None,
        "meta": None,
        "error": {"code": "NOT_FOUND", "message": "Food listing was not found.", "details": None},
    }


def test_body_validation_errors_are_422_without_echoing_input() -> None:
    code, status, message, details = describe_validation_errors(
        [
            {
                "loc": ("body", "amount"),
                "msg": "Input should be greater than 0",
                "type": "greater_than",
                "input": -5,
            },
            {"loc": ("body", "password"), "msg": "Too short", "type": "too_short", "input": "pw"},
        ]
    )
    assert (code, status) == (ErrorCode.VALIDATION_ERROR, 422)
    assert message == "amount: Input should be greater than 0 (and 1 more)"
    assert details == {
        "fields": [
            {
                "field": "amount",
                "message": "Input should be greater than 0",
                "type": "greater_than",
            },
            {"field": "password", "message": "Too short", "type": "too_short"},
        ]
    }
    assert "input" not in str(details)


def test_query_validation_errors_are_400() -> None:
    code, status, _, details = describe_validation_errors(
        [{"loc": ("query", "pageSize"), "msg": "Input should be a valid integer", "type": "int"}]
    )
    assert (code, status) == (ErrorCode.BAD_REQUEST, 400)
    assert details["fields"][0]["field"] == "pageSize"


def test_malformed_json_gets_a_plain_message() -> None:
    _, status, message, _ = describe_validation_errors(
        [{"loc": ("body", 12), "msg": "JSON decode error", "type": "json_invalid"}]
    )
    assert status == 422
    assert message == "The request body is not valid JSON."
