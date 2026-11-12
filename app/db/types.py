"""Column types."""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Dialect
from sqlalchemy.types import TypeDecorator


class Rupees(TypeDecorator[int]):
    """Whole rupees in Python, paise in PostgreSQL (BIGINT).

    Storing paise keeps the schema ready for fractional amounts without a migration, while every
    contract value stays integer rupees. Aggregates (`SUM`) inherit the type, so they come back in
    rupees too.
    """

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"money must be whole rupees as int, got {type(value).__name__}")
        return value * 100

    def process_result_value(self, value: Any, dialect: Dialect) -> int | None:
        if value is None:
            return None
        return int(value) // 100


def paise(rupees: int) -> int:
    """For raw SQL and COPY, which bypass the column type."""
    return rupees * 100
