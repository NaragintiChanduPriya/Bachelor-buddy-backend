from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.calc.budget import (
    build_budget,
    build_category,
    generate_limits,
    percent_used,
    status_for,
    validate_limits,
)
from app.calc.savings import (
    FollowedRecommendation,
    build_monthly_savings,
    build_savings_history,
    month_label,
    projected_by_month_end,
    recommendation_saving,
    saved_so_far,
)
from app.schemas.savings import SavingsHistoryPoint

DEMO_LIMITS = {
    "rent": 14000,
    "food": 7500,
    "groceries": 2500,
    "shopping": 2500,
    "travel": 2000,
    "bills": 1500,
    "misc": 2000,
    "savings": 8000,
}
DEMO_SPENT = {
    "rent": 14000,
    "food": 5250,
    "groceries": 1680,
    "shopping": 700,
    "travel": 1130,
    "bills": 1340,
    "misc": 920,
}


@pytest.mark.parametrize(
    ("used", "status"),
    [(0, "ok"), (69, "ok"), (70, "warning"), (89, "warning"), (90, "danger"), (140, "danger")],
)
def test_status_thresholds(used: int, status: str) -> None:
    assert status_for(used) == status


def test_percent_used_handles_zero_limits() -> None:
    assert percent_used(0, 0) == 0
    assert percent_used(10, 0) == 100
    assert percent_used(5250, 7500) == 70


def test_category_row_matches_the_contract_example() -> None:
    row = build_category("food", 7500, 5250)
    assert (row.remaining, row.percent_used, row.status, row.label) == (2250, 70, "warning", "Food")


def test_budget_totals_and_daily_safe_spend() -> None:
    budget = build_budget("2026-11", 40000, DEMO_LIMITS, DEMO_SPENT, days_left=15)
    assert budget.total_limit == 40000
    assert budget.total_spent == 25020
    assert budget.total_remaining == 14980
    assert budget.percent_used == 63
    # Spendable = remaining minus the untouched savings set-aside, spread over the days left.
    assert budget.daily_safe_spend == (14980 - 8000) // 15
    assert budget.categories[0].id == "rent"
    assert (
        build_budget("2026-11", 40000, DEMO_LIMITS, DEMO_SPENT, days_left=0).daily_safe_spend == 0
    )


def test_limit_validation() -> None:
    assert validate_limits(list(DEMO_LIMITS.items()), 40000).valid
    over = validate_limits([*DEMO_LIMITS.items(), ("misc", 2500)], 40000)
    assert not over.valid
    assert over.message is not None and "more than your ₹40,000 salary" in over.message
    negative = validate_limits([("food", -1)], 40000)
    assert negative.message == "Food cannot be negative."


def test_generated_limits_for_the_demo_salary() -> None:
    assert generate_limits(40000, 8000) == DEMO_LIMITS


@pytest.mark.parametrize(
    ("salary", "goal"), [(5000, 0), (23456, 1234), (95000, 20000), (61111, 4999)]
)
def test_generated_limits_always_total_the_salary(salary: int, goal: int) -> None:
    limits = generate_limits(salary, goal)
    assert sum(limits.values()) == salary
    assert limits["savings"] == goal
    assert all(v >= 0 for v in limits.values())


def test_savings_for_the_demo_user_on_the_15th() -> None:
    """The honest formula from Phase 0: ₹2,730 banked, ₹5,140 projected, ₹2,860 short."""
    assert saved_so_far(8000, DEMO_LIMITS, DEMO_SPENT, 15, 30) == 2730
    assert projected_by_month_end(40000, DEMO_LIMITS, DEMO_SPENT, 15, 30) == 5140
    monthly = build_monthly_savings(
        month="2026-11",
        salary=40000,
        goal=8000,
        limits=DEMO_LIMITS,
        spent=DEMO_SPENT,
        day=15,
        days_in_month=30,
        recommendations=[
            FollowedRecommendation(
                "rec_001", "Mess lunches", "food", 1120, datetime(2026, 11, 3, tzinfo=UTC)
            ),
            FollowedRecommendation(
                "rec_002", "Bulk rice", "grocery", 1680, datetime(2026, 11, 6, tzinfo=UTC)
            ),
        ],
    )
    assert monthly.saved == 2730
    assert monthly.percent_of_goal == 34
    assert monthly.projected_by_month_end == 5140
    assert not monthly.on_track
    assert monthly.headline == "On pace for ₹5,140 — ₹2,860 short of your goal."
    assert monthly.month_label == "November 2026"
    # Only underspending categories, biggest first, shares of their total.
    assert [c.category for c in monthly.by_category] == ["shopping", "bills", "misc"]
    assert sum(c.percent_of_total for c in monthly.by_category) in (99, 100, 101)
    assert [r.id for r in monthly.by_recommendation] == ["rec_002", "rec_001"]


def test_a_finished_month_banks_salary_minus_spending() -> None:
    spent = {**DEMO_SPENT, "food": 9000, "groceries": 2400}
    total = sum(spent.values())
    monthly = build_monthly_savings(
        month="2026-10", salary=40000, goal=8000, limits=DEMO_LIMITS, spent=spent,
        day=31, days_in_month=31, recommendations=[],
    )  # fmt: skip
    assert monthly.saved == 40000 - total
    assert monthly.projected_by_month_end == monthly.saved
    assert monthly.headline.startswith(f"You saved ₹{40000 - total:,}")


def test_recommendation_saving_is_never_negative() -> None:
    assert recommendation_saving(190, 110, 14) == 1120
    assert recommendation_saving(100, 120, 3) == 0


def test_savings_history_summary_and_trend() -> None:
    points = [
        SavingsHistoryPoint(month=m, month_label=month_label(m), saved=s, goal=8000)
        for m, s in [("2026-05", 2100), ("2026-06", 3400), ("2026-10", 7600)]
    ]
    history = build_savings_history(points)
    assert history.total_saved == 13100
    assert history.average_saved == 4367
    assert history.best_month == "October 2026"
    assert history.trend_percent == 262
    assert "over 3 months" in history.summary
    assert build_savings_history([]).summary == "No savings history yet."
