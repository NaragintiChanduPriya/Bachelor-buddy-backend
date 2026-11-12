"""Savings math.

Definitions (d = today's day of the month in IST, D = days in the month):

- Fixed categories (rent, bills) are expected in full from the 1st. Variable categories (food,
  groceries, shopping, travel, misc) are expected pro rata: `limit * d / D`.
- Category saving = expected so far - spent so far (negative means overspending).
- `saved` (banked so far) = max(0, goal * d / D + sum of category savings). For a finished month
  (d = D) this is exactly `salary - total spent`.
- `projectedByMonthEnd` = salary - projected spend, where fixed categories count at
  max(limit, spent) and variable categories continue at their current daily rate.
- `byCategory` lists the categories that are underspending, biggest first.
- `byRecommendation` lists followed recommendations, each worth
  `(alternative - chosen) * times`. They explain where savings came from and are NOT added to
  `saved`: the cheaper choice already shows up as lower spending, so adding them would count
  the same rupee twice.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.core.constants import CATEGORY_LABELS, FIXED_CATEGORIES, SPENDING_CATEGORIES
from app.core.money import format_inr, js_round
from app.schemas.savings import (
    MonthlySavings,
    SavingsByCategory,
    SavingsByRecommendation,
    SavingsHistory,
    SavingsHistoryPoint,
)

MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def month_label(month: str) -> str:
    """ "2026-10" -> "October 2026"."""
    year, number = month.split("-")
    return f"{MONTH_NAMES[int(number) - 1]} {year}"


@dataclass(frozen=True)
class FollowedRecommendation:
    id: str
    title: str
    agent: str
    saved: int
    followed_at: datetime


def recommendation_saving(alternative_price: int, chosen_price: int, times: int) -> int:
    return max(0, alternative_price - chosen_price) * times


def category_savings(
    limits: Mapping[str, int], spent: Mapping[str, int], day: int, days_in_month: int
) -> dict[str, int]:
    """Expected-so-far minus spent, per spending category."""
    result: dict[str, int] = {}
    for category in SPENDING_CATEGORIES:
        limit = limits.get(category, 0)
        expected = limit if category in FIXED_CATEGORIES else js_round(limit * day / days_in_month)
        result[category] = expected - spent.get(category, 0)
    return result


def saved_so_far(
    goal: int, limits: Mapping[str, int], spent: Mapping[str, int], day: int, days_in_month: int
) -> int:
    accrued_goal = js_round(goal * day / days_in_month)
    return max(0, accrued_goal + sum(category_savings(limits, spent, day, days_in_month).values()))


def projected_by_month_end(
    salary: int, limits: Mapping[str, int], spent: Mapping[str, int], day: int, days_in_month: int
) -> int:
    projected_spend = 0
    for category in SPENDING_CATEGORIES:
        spent_so_far = spent.get(category, 0)
        if category in FIXED_CATEGORIES:
            projected_spend += max(limits.get(category, 0), spent_so_far)
        else:
            projected_spend += js_round(spent_so_far / day * days_in_month) if day > 0 else 0
    return max(0, salary - projected_spend)


def build_monthly_savings(
    *,
    month: str,
    salary: int,
    goal: int,
    limits: Mapping[str, int],
    spent: Mapping[str, int],
    day: int,
    days_in_month: int,
    recommendations: Sequence[FollowedRecommendation],
) -> MonthlySavings:
    savings = category_savings(limits, spent, day, days_in_month)
    saved = saved_so_far(goal, limits, spent, day, days_in_month)
    projected = projected_by_month_end(salary, limits, spent, day, days_in_month)

    positive = {c: s for c, s in savings.items() if s > 0}
    positive_total = sum(positive.values()) or 1
    by_category = sorted(
        (
            SavingsByCategory(
                category=c,  # type: ignore[arg-type]
                label=CATEGORY_LABELS[c],
                saved=s,
                percent_of_total=js_round(s / positive_total * 100),
            )
            for c, s in positive.items()
        ),
        key=lambda row: -row.saved,
    )
    by_recommendation = [
        SavingsByRecommendation(
            id=r.id, title=r.title, agent=r.agent, saved=r.saved, followed_at=r.followed_at
        )
        for r in sorted(recommendations, key=lambda r: -r.saved)
    ]
    finished = day >= days_in_month
    if finished:
        headline = (
            f"You saved {format_inr(saved)} in {month_label(month)}, past your "
            f"{format_inr(goal)} goal."
            if saved >= goal
            else f"You saved {format_inr(saved)} in {month_label(month)}, "
            f"{format_inr(goal - saved)} short of your goal."
        )
    elif projected >= goal:
        headline = (
            f"On track to save {format_inr(projected)} this month, past your "
            f"{format_inr(goal)} goal."
        )
    else:
        headline = (
            f"On pace for {format_inr(projected)} — {format_inr(goal - projected)} short of "
            "your goal."
        )
    return MonthlySavings(
        month=month,
        month_label=month_label(month),
        saved=saved,
        goal=goal,
        percent_of_goal=js_round(saved / goal * 100) if goal > 0 else 0,
        on_track=(saved if finished else projected) >= goal,
        projected_by_month_end=saved if finished else projected,
        by_category=by_category,
        by_recommendation=by_recommendation,
        headline=headline,
    )


def build_savings_history(points: Sequence[SavingsHistoryPoint]) -> SavingsHistory:
    if not points:
        return SavingsHistory(
            months=[],
            average_saved=0,
            best_month="",
            total_saved=0,
            trend_percent=0,
            summary="No savings history yet.",
        )
    total = sum(p.saved for p in points)
    average = js_round(total / len(points))
    best = points[0]
    for point in points[1:]:
        if point.saved > best.saved:
            best = point
    first, last = points[0], points[-1]
    trend = js_round((last.saved - first.saved) / first.saved * 100) if first.saved > 0 else 0
    return SavingsHistory(
        months=list(points),
        average_saved=average,
        best_month=best.month_label,
        total_saved=total,
        trend_percent=trend,
        summary=(
            f"Saved {format_inr(total)} over {len(points)} months, averaging "
            f"{format_inr(average)} a month. Best month was {best.month_label} at "
            f"{format_inr(best.saved)}."
        ),
    )
