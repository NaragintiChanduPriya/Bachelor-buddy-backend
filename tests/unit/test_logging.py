from __future__ import annotations

import json
import logging
import sys

from app.core.logging import (
    REDACTED,
    JsonFormatter,
    StdoutHandler,
    TextFormatter,
    configure_logging,
    request_id_var,
)


def make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_one_object_with_request_id() -> None:
    token = request_id_var.set("req-123")
    try:
        line = JsonFormatter().format(make_record(user_id=7, path="/api/me"))
    finally:
        request_id_var.reset(token)
    payload = json.loads(line)
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["request_id"] == "req-123"
    assert payload["user_id"] == 7
    assert payload["path"] == "/api/me"
    assert payload["ts"].endswith("Z")


def test_uvicorn_colour_codes_are_dropped() -> None:
    payload = json.loads(JsonFormatter().format(make_record(color_message="\x1b[36mhi\x1b[0m")))
    assert "color_message" not in payload


def test_sensitive_extra_fields_are_redacted() -> None:
    payload = json.loads(
        JsonFormatter().format(
            make_record(
                password="hunter2",
                refresh_token="abc",
                authorization="Bearer xyz",
                groq_api_key="gsk",
                jwt_secret="s",
            )
        )
    )
    for key in ("password", "refresh_token", "authorization", "groq_api_key", "jwt_secret"):
        assert payload[key] == REDACTED
    assert "hunter2" not in json.dumps(payload)


def test_exceptions_are_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exc"]


def test_text_formatter_is_human_readable() -> None:
    line = TextFormatter().format(make_record(status=200))
    assert "INFO" in line
    assert "hello world" in line
    assert "status=200" in line


def test_configure_logging_installs_one_handler_and_silences_uvicorn_access() -> None:
    configure_logging("INFO", "json")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], StdoutHandler)
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert logging.getLogger("uvicorn.access").disabled
