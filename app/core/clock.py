"""The server's notion of "now".

Every service asks a `Clock` instead of calling `datetime.now()`, so the whole backend agrees
on one instant and tests can pin it.

`CLOCK_MODE=demo` reproduces the frontend mock clock (`src/mocks/clock.ts`): the 15th of the
current real month at 12:30 in the business time zone (12:30 IST = 07:00 UTC). The month is read
in the business time zone, so a late-night UTC run never slips into the wrong month. Unlike the
mock, the value is recomputed on every call, so a long-running server rolls into the next month.

`CLOCK_MODE=real` uses the wall clock (the default, and the only mode production allows).
`CLOCK_MODE=fixed` pins the instant in `CLOCK_FIXED_AT`, for end-to-end tests against a database
seeded at that instant.

All instants are timezone-aware and in UTC. Convert to the business zone only to read calendar
fields (day of month, month key, hour).
"""

from __future__ import annotations

import calendar
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import Settings

DEMO_DAY_OF_MONTH = 15
DEMO_TIME = time(12, 30)


class Clock(ABC):
    """Source of the current instant, plus calendar helpers in the business time zone."""

    def __init__(self, zone: ZoneInfo) -> None:
        self.zone = zone

    @abstractmethod
    def now(self) -> datetime:
        """The current instant, timezone-aware, in UTC."""

    def local_now(self) -> datetime:
        """The current instant in the business time zone."""
        return self.now().astimezone(self.zone)

    def today(self) -> date:
        """Today's date in the business time zone."""
        return self.local_now().date()

    def month_key(self) -> str:
        """The current month as `YYYY-MM`, in the business time zone."""
        local = self.local_now()
        return f"{local.year:04d}-{local.month:02d}"

    def day_of_month(self) -> int:
        return self.local_now().day

    def days_in_current_month(self) -> int:
        local = self.local_now()
        return calendar.monthrange(local.year, local.month)[1]

    def days_left_in_month(self) -> int:
        """Days remaining after today (today itself is not counted)."""
        return self.days_in_current_month() - self.day_of_month()


class SystemClock(Clock):
    """The wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class DemoClock(Clock):
    """The 15th of the current real month at 12:30 business time, like the frontend mock."""

    def __init__(self, zone: ZoneInfo, wall: Clock | None = None) -> None:
        super().__init__(zone)
        self._wall = wall or SystemClock(zone)

    def now(self) -> datetime:
        real = self._wall.now().astimezone(self.zone)
        demo_local = datetime.combine(
            date(real.year, real.month, DEMO_DAY_OF_MONTH), DEMO_TIME, tzinfo=self.zone
        )
        return demo_local.astimezone(UTC)


class FixedClock(Clock):
    """Always the same instant. For tests and for replaying a scheduled job at a given time."""

    def __init__(self, zone: ZoneInfo, instant: datetime) -> None:
        super().__init__(zone)
        if instant.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant


def month_key_of(instant: datetime, zone: ZoneInfo) -> str:
    local = instant.astimezone(zone)
    return f"{local.year:04d}-{local.month:02d}"


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def shift_month(month: str, delta: int) -> str:
    """`shift_month("2026-01", -1) == "2025-12"`."""
    year, number = (int(part) for part in month.split("-"))
    index = year * 12 + (number - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_bounds(month: str, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) of a `YYYY-MM` month in the business zone, as UTC instants."""
    year, number = (int(part) for part in month.split("-"))
    start = datetime(year, number, 1, tzinfo=zone)
    next_year, next_number = (int(part) for part in shift_month(month, 1).split("-"))
    end = datetime(next_year, next_number, 1, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def local_datetime(day: date, hour: int, minute: int, zone: ZoneInfo) -> datetime:
    """A wall-clock time on a day in the business zone, as a UTC instant."""
    return datetime.combine(day, time(hour, minute), tzinfo=zone).astimezone(UTC)


def build_clock(settings: Settings) -> Clock:
    """The clock selected by `CLOCK_MODE`."""
    if settings.clock_mode == "demo":
        return DemoClock(settings.zone)
    if settings.clock_mode == "fixed" and settings.clock_fixed_at is not None:
        return FixedClock(settings.zone, settings.clock_fixed_at)
    return SystemClock(settings.zone)
