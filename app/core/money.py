"""Money helpers. All money is integer rupees; these keep Python arithmetic identical to the
frontend mock (JavaScript), which the contract's numbers were written against."""

from __future__ import annotations

import math


def js_round(value: float) -> int:
    """JavaScript's `Math.round`: halves round up (towards +infinity).

    Python's `round` uses banker's rounding (round(2.5) == 2), which would make some figures
    differ by a rupee from the contract.
    """
    return math.floor(value + 0.5)


def _group_indian(digits: str) -> str:
    """12345678 -> 1,23,45,678 (last three digits, then pairs)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join([*pairs, tail])


def format_inr(amount: float) -> str:
    """`Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR'})` with no decimals:
    1649 -> "₹1,649", 123450 -> "₹1,23,450", -500 -> "-₹500"."""
    value = js_round(amount)
    sign = "-" if value < 0 else ""
    return f"{sign}₹{_group_indian(str(abs(value)))}"


def percent(part: float, whole: float) -> int:
    """Whole percent of `whole`, rounded like the frontend. A zero whole gives 0."""
    if whole == 0:
        return 0
    return js_round(part / whole * 100)
