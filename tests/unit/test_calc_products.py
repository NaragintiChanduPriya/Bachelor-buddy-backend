"""Buy-now-or-wait verdict rules, on hand-built 90-day series."""

from __future__ import annotations

import pytest

from app.calc.products import (
    PlatformToday,
    build_verdict,
    daily_lowest,
    detect_sale_events,
    discount_percent,
    price_stats,
    round_to_price_point,
    sale_cadence_days,
    summarize_platforms,
)

DAYS = 90


def steady(level: int = 2000) -> list[int]:
    return [level + (15 if day % 7 < 3 else -15) for day in range(DAYS)]


@pytest.mark.parametrize(
    ("value", "expected"), [(1650, 1649), (1644, 1639), (3, 9), (2199.6, 2199)]
)
def test_price_points_end_in_nine(value: float, expected: int) -> None:
    assert round_to_price_point(value) == expected


def test_daily_lowest_and_stats() -> None:
    assert daily_lowest([[5, 9, 3], [6, 2, 4]]) == [5, 2, 3]
    assert daily_lowest([]) == []
    stats = price_stats([100, 200, 300])
    assert (stats.lowest, stats.highest, stats.average, stats.current) == (100, 300, 200, 300)


def test_today_at_the_low_after_a_drop_is_buy_now() -> None:
    series = steady()[:-5] + [1649] * 5
    verdict = build_verdict(series)
    assert verdict.verdict == "buyNow"
    assert verdict.reason.startswith("₹1,649 is the lowest price in 90 days")


def test_a_sale_that_ended_recently_means_wait() -> None:
    series = steady()
    for start in (20, 52):  # two sales, the last one ended 30 days ago
        for day in range(start, start + 4):
            series[day] = 1500
    verdict = build_verdict(series)
    assert verdict.verdict == "wait"
    assert "dropped to ₹1,500 in the last sale" in verdict.reason
    assert "every 5 weeks" in verdict.reason


def test_seasonal_spike_means_wait() -> None:
    series = steady()
    for days_ago in range(20):
        series[-1 - days_ago] = round(2000 * (1 + 0.14 * (1 - days_ago / 20)))
    verdict = build_verdict(series)
    assert verdict.verdict == "wait"
    assert "above the 90-day average" in verdict.reason


def test_a_steady_price_is_buy_now() -> None:
    series = steady()
    series[-1] = series[0] + 40  # nowhere near the low, nowhere near a sale, not inflated
    verdict = build_verdict(series)
    assert verdict.verdict == "buyNow"
    assert verdict.reason.startswith("The price has moved by only")


def test_sale_detection_and_cadence() -> None:
    series = [2000] * 30
    for day in (5, 6, 15, 16, 25, 26):
        series[day] = 1700
    events = detect_sale_events(series, 2000)
    assert [(e.start_days_ago, e.end_days_ago, e.lowest) for e in events] == [
        (24, 23, 1700),
        (14, 13, 1700),
        (4, 3, 1700),
    ]
    assert sale_cadence_days(events) == 10
    assert sale_cadence_days(events[:1]) is None
    ongoing = detect_sale_events([2000] * 10 + [1700] * 2, 2000)
    assert ongoing[-1].end_days_ago == 0


def test_platform_summary_ignores_out_of_stock_and_placement() -> None:
    rows = [
        PlatformToday("ShopNest", 1649, True, 2),
        PlatformToday("TrendKart", 1499, False, 1),  # cheapest but out of stock
        PlatformToday("StyleBay", 1649, True, 1),  # same price, faster
    ]
    summary = summarize_platforms(rows, mrp=2999)
    assert (summary.lowest_price, summary.highest_price) == (1649, 1649)
    assert summary.cheapest_platform == "StyleBay"
    assert summary.fastest_delivery_days == 1
    assert summary.discount_percent == discount_percent(1649, 2999) == 45
    all_out = summarize_platforms([PlatformToday("ShopNest", 999, False, 3)], 1999)
    assert all_out.lowest_price == 999  # still shows a price
    assert discount_percent(2000, 1999) == 0
