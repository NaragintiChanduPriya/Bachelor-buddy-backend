"""Structured logging with request IDs.

One handler on the root logger writes one JSON object per line to stdout. The request ID of the
current request (set by `RequestContextMiddleware`) is added to every record automatically.

Never log secrets. As a backstop, any `extra` field whose name looks sensitive (password, token,
secret, authorization, api key, cookie) is replaced with "[redacted]".
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal, TextIO

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SENSITIVE_KEY = re.compile(r"pass(word)?|secret|token|authori[sz]ation|api[_-]?key|cookie", re.I)
REDACTED = "[redacted]"

# Attributes every LogRecord has; anything else on a record came from `extra=`.
# `color_message` is uvicorn's copy of the message with terminal colour codes.
_RECORD_ATTRS = frozenset(
    logging.LogRecord("", logging.INFO, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime", "taskName", "color_message"}


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RECORD_ATTRS or key.startswith("_"):
            continue
        fields[key] = REDACTED if _SENSITIVE_KEY.search(key) else value
    return fields


def _timestamp(record: logging.LogRecord) -> str:
    instant = datetime.fromtimestamp(record.created, UTC)
    return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    """One JSON object per record: ts, level, logger, msg, request_id, extras, exc."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable lines for local debugging (`LOG_FORMAT=text`)."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = request_id_var.get()
        extras = " ".join(f"{k}={v}" for k, v in _extra_fields(record).items())
        line = f"{_timestamp(record)} {record.levelname:<7} {record.name}"
        if request_id:
            line += f" [{request_id}]"
        line += f" {record.getMessage()}"
        if extras:
            line += f" | {extras}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class StdoutHandler(logging.StreamHandler[TextIO]):
    """Writes to whatever `sys.stdout` is at emit time, so a replaced stdout (pytest capture,
    a supervisor redirect) never leaves the handler writing to a closed stream."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


def configure_logging(level: str = "INFO", fmt: Literal["json", "text"] = "json") -> None:
    """Route every logger (including uvicorn's) through one stdout handler."""
    handler = StdoutHandler()
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # The request middleware writes one access line per request, with the request ID.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True

    # SQL echo stays off unless explicitly debugging.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
