"""Helpers shared by the model modules."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


def one_of(column: str, values: Iterable[str], name: str | None = None) -> CheckConstraint:
    """`CHECK (column IN (...))`. Text columns plus checks are easier to evolve than PG enums."""
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name or f"{column}_valid")


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())
