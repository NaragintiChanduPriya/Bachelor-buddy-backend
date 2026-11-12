"""Prefixed public IDs (`exp_031`, `notif_003`) for rows whose primary key is an integer.

Catalog rows (areas, listings, products, homes, offers) store their prefixed text ID directly.
"""

from __future__ import annotations


def format_id(prefix: str, number: int) -> str:
    return f"{prefix}_{number:03d}"


def parse_id(prefix: str, value: str) -> int | None:
    """`parse_id("exp", "exp_031") == 31`. Anything malformed, or another prefix, is None."""
    head, sep, tail = value.partition("_")
    if head != prefix or not sep or not tail.isdigit() or len(tail) > 12:
        return None
    return int(tail)
