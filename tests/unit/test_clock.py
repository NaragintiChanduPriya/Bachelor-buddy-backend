from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.clock import DemoClock, FixedClock, SystemClock, build_clock
from tests.conftest import load_test_settings

IST = ZoneInfo("Asia/Kolkata")


def demo_at(wall_utc: datetime) -> DemoClock:
    return DemoClock(IST, wall=FixedClock(IST, wall_utc))


def test_demo_clock_is_the_15th_at_1230_ist() -> None:
    clock = demo_at(datetime(2026, 11, 9, 10, 0, tzinfo=UTC))
    assert clock.now() == datetime(2026, 11, 15, 7, 0, tzinfo=UTC)  # 12:30 IST
    local = clock.local_now()
    assert (local.day, local.hour, local.minute) == (15, 12, 30)
    assert clock.today() == date(2026, 11, 15)
    assert clock.month_key() == "2026-11"


def test_demo_clock_reads_the_month_in_ist_not_utc() -> None:
    # 19:00 UTC on 31 Oct is 00:30 IST on 1 Nov, so the demo month is November.
    assert demo_at(datetime(2026, 10, 31, 19, 0, tzinfo=UTC)).month_key() == "2026-11"
    # 18:00 UTC on 31 Oct is 23:30 IST on 31 Oct, still October.
    assert demo_at(datetime(2026, 10, 31, 18, 0, tzinfo=UTC)).month_key() == "2026-10"


def test_demo_clock_rolls_over_with_the_real_month() -> None:
    wall = FixedClock(IST, datetime(2026, 12, 2, 6, 0, tzinfo=UTC))
    assert DemoClock(IST, wall=wall).now() == datetime(2026, 12, 15, 7, 0, tzinfo=UTC)


def test_system_clock_is_aware_utc() -> None:
    now = SystemClock(IST).now()
    assert now.tzinfo is UTC


def test_fixed_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(IST, datetime(2026, 11, 15, 7, 0))  # noqa: DTZ001 - deliberately naive


def test_fixed_clock_normalises_to_utc() -> None:
    clock = FixedClock(IST, datetime(2026, 11, 15, 12, 30, tzinfo=IST))
    assert clock.now() == datetime(2026, 11, 15, 7, 0, tzinfo=UTC)
    assert clock.now().tzinfo is UTC


def test_build_clock_follows_clock_mode() -> None:
    settings = load_test_settings()
    assert isinstance(build_clock(settings.model_copy(update={"clock_mode": "demo"})), DemoClock)
    assert isinstance(build_clock(settings.model_copy(update={"clock_mode": "real"})), SystemClock)
    pinned = datetime(2026, 11, 15, 7, 0, tzinfo=UTC)
    fixed = build_clock(
        settings.model_copy(update={"clock_mode": "fixed", "clock_fixed_at": pinned})
    )
    assert isinstance(fixed, FixedClock) and fixed.now() == pinned


def test_settings_guard_the_clock() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    base = load_test_settings().model_dump()
    with pytest.raises(ValidationError, match="CLOCK_FIXED_AT"):
        Settings(**{**base, "clock_mode": "fixed", "clock_fixed_at": None})
    with pytest.raises(ValidationError, match="CLOCK_MODE=real"):
        Settings(**{**base, "app_env": "production", "clock_mode": "demo"})
