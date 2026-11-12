"""Reusable request-field validators with user-facing messages.

Pydantic would otherwise accept "120" or 120.0 for an int, and its default messages are written
for developers. These keep the mock backend's friendlier wording.
"""

from __future__ import annotations

from typing import Any


def whole_number(value: Any, message: str) -> int:
    """Accept an int (or a float with no fractional part); reject bools, strings and fractions."""
    if isinstance(value, bool):
        raise ValueError(message)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(message)


def clean_optional_text(value: Any) -> str | None:
    """Trim; an empty string becomes None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Must be text.")
    stripped = value.strip()
    return stripped or None
