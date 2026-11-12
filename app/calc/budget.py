"""Budget math (port of the frontend's src/mocks/calc/budget.ts)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.constants import CATEGORY_IDS, CATEGORY_LABELS
from app.core.money import format_inr, js_round
from app.schemas.budget import BudgetCategoryOut, BudgetOut

#: Warning at 70% of a category limit, danger at 90%.
WARNING_THRESHOLD = 70
DANGER_THRESHOLD = 90
MIN_SALARY = 5000

#: How a salary is split after the savings goal: the demo user's proportions.
LIMIT_WEIGHTS: Mapping[str, float] = {
    "rent": 0.4375,
    "food": 0.2344,
    "groceries": 0.0781,
    "shopping": 0.0781,
    "travel": 0.0625,
    "bills": 0.0469,
}


def status_for(percent_used: int) -> str:
    if percent_used >= DANGER_THRESHOLD:
        return "danger"
    if percent_used >= WARNING_THRESHOLD:
        return "warning"
    return "ok"


def percent_used(spent: int, limit: int) -> int:
    """Whole percent of a limit used. A zero limit counts as fully used once anything is spent."""
    if limit <= 0:
        return 100 if spent > 0 else 0
    return js_round(spent / limit * 100)


def build_category(category: str, limit: int, spent: int) -> BudgetCategoryOut:
    used = percent_used(spent, limit)
    return BudgetCategoryOut(
        id=category,  # type: ignore[arg-type]  # validated by the Literal
        label=CATEGORY_LABELS[category],
        limit=limit,
        spent=spent,
        remaining=limit - spent,
        percent_used=used,
        status=status_for(used),  # type: ignore[arg-type]
    )


def build_budget(
    month: str,
    salary: int,
    limits: Mapping[str, int],
    spent: Mapping[str, int],
    days_left: int,
) -> BudgetOut:
    """The whole budget for a month. `savings` is a planned set-aside: it counts toward the limit
    total, and `dailySafeSpend` leaves it untouched."""
    categories = [
        build_category(c, limits.get(c, 0), spent.get(c, 0)) for c in CATEGORY_IDS if c in limits
    ]
    total_limit = sum(c.limit for c in categories)
    total_spent = sum(c.spent for c in categories)
    total_remaining = total_limit - total_spent
    savings_row = next((c for c in categories if c.id == "savings"), None)
    spendable_remaining = total_remaining - max(0, savings_row.remaining if savings_row else 0)
    return BudgetOut(
        month=month,
        salary=salary,
        total_limit=total_limit,
        total_spent=total_spent,
        total_remaining=total_remaining,
        percent_used=percent_used(total_spent, total_limit),
        days_left_in_month=days_left,
        daily_safe_spend=max(0, spendable_remaining // days_left) if days_left > 0 else 0,
        categories=categories,
    )


@dataclass(frozen=True)
class LimitCheck:
    valid: bool
    total: int
    message: str | None = None


def validate_limits(limits: Sequence[tuple[str, int]], salary: int) -> LimitCheck:
    """PUT /budget/current validates the whole set, not only the changed rows."""
    total = sum(limit for _, limit in limits)
    for category, limit in limits:
        if limit < 0:
            return LimitCheck(False, total, f"{CATEGORY_LABELS[category]} cannot be negative.")
    if total > salary:
        return LimitCheck(
            False,
            total,
            f"Your category limits add up to {format_inr(total)}, which is more than your "
            f"{format_inr(salary)} salary.",
        )
    return LimitCheck(True, total)


def generate_limits(salary: int, savings_goal: int) -> dict[str, int]:
    """Split a salary into category limits. The savings goal is honoured first; the rest is
    spread by weight, rounded to ₹100, and misc absorbs the remainder so the limits total the
    salary exactly."""
    spendable = salary - savings_goal
    limits = {c: js_round(spendable * w / 100) * 100 for c, w in LIMIT_WEIGHTS.items()}
    limits["savings"] = savings_goal
    limits["misc"] = salary - sum(limits.values())
    return {c: limits[c] for c in CATEGORY_IDS}
