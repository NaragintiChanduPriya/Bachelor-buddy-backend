"""Generator plumbing: per-entity seeded randomness, the generation anchor, and table rows."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.money import js_round

IST = ZoneInfo("Asia/Kolkata")
#: Bump when the generated data changes shape, so `--seed` regenerates instead of skipping.
GENERATOR_VERSION = "1"


class Rng(random.Random):
    """`random.Random` with the helpers the builders need."""

    def money(self, low: int, high: int, step: int = 1) -> int:
        return self.randint(low // step, high // step) * step

    def chance(self, probability: float) -> bool:
        return self.random() < probability

    def rating(self, low: float, high: float) -> float:
        return round(self.uniform(low, high), 1)


def rng_for(seed: int, *key: object) -> Rng:
    """An independent stream per entity, so adding rows never shifts existing ones. String
    seeding is stable across processes (it does not depend on PYTHONHASHSEED)."""
    return Rng(f"{seed}:" + ":".join(str(k) for k in key))


@dataclass(frozen=True)
class Anchor:
    """The instant the data is generated around ("now"), and calendar fields in IST."""

    now: datetime

    @property
    def local(self) -> datetime:
        return self.now.astimezone(IST)

    @property
    def today(self) -> date:
        return self.local.date()

    @property
    def month(self) -> str:
        return f"{self.local.year:04d}-{self.local.month:02d}"

    def at(self, day: date, hour: int = 13, minute: int = 0) -> datetime:
        """A wall-clock time in IST on `day`, as a UTC instant."""
        return datetime.combine(day, time(hour, minute), tzinfo=IST).astimezone(UTC)

    def days_ago(self, days: int, hour: int = 13, minute: int = 0) -> datetime:
        return self.at(self.today - timedelta(days=days), hour, minute)

    def days_ahead(self, days: int, hour: int = 13, minute: int = 0) -> datetime:
        return self.at(self.today + timedelta(days=days), hour, minute)


def paise(rupees: int) -> int:
    return rupees * 100


def offset_point(rng: Rng, lat: float, lng: float, radius_km: float) -> tuple[float, float]:
    """A point uniformly inside a disc around (lat, lng)."""
    distance = radius_km * math.sqrt(rng.random())
    bearing = rng.uniform(0, 2 * math.pi)
    d_lat = distance * math.cos(bearing) / 111.0
    d_lng = distance * math.sin(bearing) / (111.0 * math.cos(math.radians(lat)))
    return round(lat + d_lat, 5), round(lng + d_lng, 5)


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def round_to(value: float, step: int) -> int:
    return js_round(value / step) * step


@dataclass
class Table:
    """Rows for one catalog table, in column order, ready for COPY."""

    name: str
    columns: tuple[str, ...]
    keys: tuple[str, ...]
    rows: list[tuple[Any, ...]] = field(default_factory=list)

    def add(self, *values: Any) -> None:
        if len(values) != len(self.columns):
            raise ValueError(f"{self.name}: expected {len(self.columns)} values, got {len(values)}")
        self.rows.append(values)
