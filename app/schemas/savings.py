from __future__ import annotations

from app.core.constants import BudgetCategoryId
from app.schemas.common import CamelModel, UtcDateTime


class SavingsByCategory(CamelModel):
    category: BudgetCategoryId
    label: str
    saved: int
    percent_of_total: int


class SavingsByRecommendation(CamelModel):
    id: str
    title: str
    agent: str
    saved: int
    followed_at: UtcDateTime


class MonthlySavings(CamelModel):
    month: str
    month_label: str
    saved: int
    goal: int
    percent_of_goal: int
    on_track: bool
    projected_by_month_end: int
    by_category: list[SavingsByCategory]
    by_recommendation: list[SavingsByRecommendation]
    headline: str


class SavingsHistoryPoint(CamelModel):
    month: str
    month_label: str
    saved: int
    goal: int


class SavingsHistory(CamelModel):
    months: list[SavingsHistoryPoint]
    average_saved: int
    best_month: str
    total_saved: int
    trend_percent: int
    summary: str
