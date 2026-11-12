"""Query-parameter helpers that mirror the mock backend's parsing rules."""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Annotated

from fastapi import Query

from app.core.errors import BadRequestError

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_PAGE_SIZE = 50

Page = Annotated[int, Query(ge=1, description="1-based page number")]
PageSize = Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE_SIZE)]


def optional_choice(value: str | None) -> str | None:
    """Empty and "all" mean "no filter", like the mock's `stringParam`."""
    if value is None:
        return None
    value = value.strip()
    return None if value in {"", "all"} else value


def check_choice(value: str | None, allowed: Collection[str], message: str) -> str | None:
    value = optional_choice(value)
    if value is not None and value not in allowed:
        raise BadRequestError(message.format(value=value))
    return value


def check_month(value: str | None, default: str) -> str:
    if value is None or value == "":
        return default
    if not MONTH_PATTERN.fullmatch(value):
        raise BadRequestError("The month parameter must look like 2026-10.")
    return value


def check_positive(value: float | None, name: str) -> None:
    if value is not None and value <= 0:
        raise BadRequestError(f"{name} must be greater than zero.")
