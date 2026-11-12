"""Price analysis behind "buy now or wait" (port of src/mocks/calc/products.ts).

Every function takes a daily price series, oldest first, today last.

Verdict rules (the series is the cheapest in-stock price per day over the last 90 days):
1. Today within 3% of the 90-day low -> buy now.
2. Otherwise, a sale has ended and today sits above 97% of the average -> wait, quoting the last
   sale price, how often sales recur and when the next one is likely.
3. Otherwise, today more than 6% above the 90-day average (seasonal demand) -> wait.
4. Otherwise the price is steady -> buy now.
A day is a sale day when its price is at least 10% under the period average; consecutive sale
days make one sale.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.money import format_inr, js_round

SALE_DEPTH = 0.9
AT_LOW_TOLERANCE = 1.03
INFLATED_THRESHOLD = 1.06


def round_to_price_point(value: float) -> int:
    """Retail price ending in 9: 1,649 / 1,299 / 349."""
    return max(9, js_round(value / 10) * 10 - 1)


def daily_lowest(series: Sequence[Sequence[int]]) -> list[int]:
    if not series:
        return []
    length = min(len(s) for s in series)
    return [min(s[day] for s in series) for day in range(length)]


@dataclass(frozen=True)
class PriceStats:
    lowest: int
    highest: int
    average: int
    current: int


def price_stats(series: Sequence[int]) -> PriceStats:
    if not series:
        return PriceStats(0, 0, 0, 0)
    return PriceStats(
        lowest=min(series),
        highest=max(series),
        average=js_round(sum(series) / len(series)),
        current=series[-1],
    )


@dataclass(frozen=True)
class SaleEvent:
    start_days_ago: int
    end_days_ago: int
    lowest: int


def detect_sale_events(series: Sequence[int], average: int) -> list[SaleEvent]:
    events: list[SaleEvent] = []
    last = len(series) - 1
    start: int | None = None
    lowest = 0
    for day, price in enumerate(series):
        on_sale = price <= average * SALE_DEPTH
        if on_sale:
            if start is None:
                start, lowest = day, price
            else:
                lowest = min(lowest, price)
        if (not on_sale or day == last) and start is not None:
            end = day if on_sale else day - 1
            events.append(SaleEvent(last - start, last - end, lowest))
            start = None
    return events


def sale_cadence_days(events: Sequence[SaleEvent]) -> int | None:
    if len(events) < 2:
        return None
    gaps = [events[i].start_days_ago - events[i + 1].start_days_ago for i in range(len(events) - 1)]
    return js_round(sum(gaps) / len(gaps))


@dataclass(frozen=True)
class Verdict:
    verdict: str
    reason: str


def build_verdict(series: Sequence[int]) -> Verdict:
    stats = price_stats(series)
    current, lowest, highest, average = stats.current, stats.lowest, stats.highest, stats.average
    events = detect_sale_events(series, average)
    ongoing = next((e for e in events if e.end_days_ago == 0), None)
    finished = [e for e in events if e.end_days_ago > 0]

    if current <= lowest * AT_LOW_TOLERANCE:
        if ongoing and finished:
            return Verdict(
                "buyNow",
                f"The sale is on: {format_inr(current)} matches the lowest price in 90 days, and "
                "sales like this end within a few days. Buy now.",
            )
        if current == lowest:
            dropped: int | None = None
            if ongoing:
                index = len(series) - 1 - ongoing.start_days_ago - 1
                dropped = series[index] if 0 <= index < len(series) else None
            if dropped:
                return Verdict(
                    "buyNow",
                    f"{format_inr(current)} is the lowest price in 90 days, down from "
                    f"{format_inr(dropped)} — buy now.",
                )
            return Verdict(
                "buyNow", f"{format_inr(current)} is the lowest price in 90 days — buy now."
            )
        return Verdict(
            "buyNow",
            f"{format_inr(current)} is within {format_inr(current - lowest)} of the 90-day low, "
            "so waiting is unlikely to save much. Buy now.",
        )

    last_sale = finished[-1] if finished else None
    if last_sale and current > average * 0.97:
        # A sale cut off by the start of the window has an unknown start, so skip it.
        cadence = sale_cadence_days([e for e in finished if e.start_days_ago < len(series) - 1])
        weeks = max(1, js_round(cadence / 7)) if cadence else None
        next_in = max(1, cadence - last_sale.start_days_ago) if cadence else None
        rhythm = f", and sales here come round about every {weeks} weeks" if weeks else ""
        upcoming = f" The next one is likely within {next_in} days." if next_in else ""
        return Verdict(
            "wait",
            f"It dropped to {format_inr(last_sale.lowest)} in the last sale "
            f"{last_sale.end_days_ago} days ago{rhythm} — wait and save "
            f"{format_inr(current - last_sale.lowest)}.{upcoming}",
        )

    if current > average * INFLATED_THRESHOLD:
        above = js_round((current - average) / average * 100)
        return Verdict(
            "wait",
            f"{format_inr(current)} is {above}% above the 90-day average of {format_inr(average)} "
            "— seasonal demand has pushed it up, and prices usually settle within a few weeks. "
            "Wait.",
        )

    return Verdict(
        "buyNow",
        f"The price has moved by only {format_inr(highest - lowest)} in 90 days, so waiting is "
        "unlikely to save much — buy when you need it.",
    )


def history_summary(days: int, stats: PriceStats, cheapest_platform: str) -> str:
    return (
        f"Over the last {days} days the best available price ranged from "
        f"{format_inr(stats.lowest)} to {format_inr(stats.highest)}, averaging "
        f"{format_inr(stats.average)}. Today it is {format_inr(stats.current)} on "
        f"{cheapest_platform}."
    )


@dataclass(frozen=True)
class PlatformToday:
    platform: str
    price: int
    in_stock: bool
    delivery_days: int


@dataclass(frozen=True)
class PlatformSummary:
    lowest_price: int
    highest_price: int
    discount_percent: int
    cheapest_platform: str
    fastest_delivery_days: int


def available(platforms: Sequence[PlatformToday]) -> list[PlatformToday]:
    """Platforms that can sell it today; if none can, all of them, so prices still show."""
    in_stock = [p for p in platforms if p.in_stock]
    return in_stock or list(platforms)


def summarize_platforms(platforms: Sequence[PlatformToday], mrp: int) -> PlatformSummary:
    """Cheapest first, then fastest — never by which platform pays for placement."""
    selling = available(platforms)
    cheapest = min(selling, key=lambda p: (p.price, p.delivery_days, p.platform))
    lowest = min(p.price for p in selling)
    return PlatformSummary(
        lowest_price=lowest,
        highest_price=max(p.price for p in selling),
        discount_percent=discount_percent(lowest, mrp),
        cheapest_platform=cheapest.platform,
        fastest_delivery_days=min(p.delivery_days for p in selling),
    )


def discount_percent(price: int, mrp: int) -> int:
    if mrp <= 0 or price >= mrp:
        return 0
    return js_round((mrp - price) / mrp * 100)
