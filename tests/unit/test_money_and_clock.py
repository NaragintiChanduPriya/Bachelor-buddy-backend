from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.clock import days_in_month, local_datetime, month_bounds, month_key_of, shift_month
from app.core.ids import format_id, parse_id
from app.core.money import format_inr, js_round, percent

IST = ZoneInfo("Asia/Kolkata")


@pytest.mark.parametrize(
    ("value", "expected"), [(2.5, 3), (3.5, 4), (-2.5, -2), (2.4999, 2), (0.5, 1), (104.5, 105)]
)
def test_js_round_rounds_halves_up_like_javascript(value: float, expected: int) -> None:
    assert js_round(value) == expected


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (0, "₹0"),
        (999, "₹999"),
        (1649, "₹1,649"),
        (123450, "₹1,23,450"),
        (12345678, "₹1,23,45,678"),
        (-500, "-₹500"),
        (1499.5, "₹1,500"),
    ],
)
def test_format_inr_uses_indian_grouping(amount: float, text: str) -> None:
    assert format_inr(amount) == text


def test_percent() -> None:
    assert percent(5250, 7500) == 70
    assert percent(1, 0) == 0


def test_prefixed_ids_round_trip() -> None:
    assert format_id("exp", 31) == "exp_031"
    assert format_id("conv", 1041) == "conv_1041"
    assert parse_id("exp", "exp_031") == 31
    for bad in ("notif_031", "exp-031", "exp_", "exp_abc", "exp_1x", "exp_" + "9" * 20):
        assert parse_id("exp", bad) is None


def test_month_helpers_work_in_ist() -> None:
    start, end = month_bounds("2026-11", IST)
    assert start == datetime(2026, 10, 31, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 11, 30, 18, 30, tzinfo=UTC)
    assert shift_month("2026-01", -1) == "2025-12"
    assert shift_month("2026-12", 1) == "2027-01"
    assert days_in_month(2028, 2) == 29
    assert month_key_of(datetime(2026, 10, 31, 19, 0, tzinfo=UTC), IST) == "2026-11"
    assert local_datetime(date(2026, 11, 17), 20, 0, IST) == datetime(
        2026, 11, 17, 14, 30, tzinfo=UTC
    )
