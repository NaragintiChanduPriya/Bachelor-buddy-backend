"""Rent math for the Home agent (port of src/mocks/calc/homes.ts)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.money import js_round
from app.schemas.home import HomeSearchInsight


@dataclass(frozen=True)
class AreaComparison:
    area_average_rent: int
    difference_from_average: int
    below_average: bool


def compare_with_area_average(rent: int, area_average_rent: int) -> AreaComparison:
    difference = rent - area_average_rent
    return AreaComparison(area_average_rent, difference, difference < 0)


def yearly_difference(monthly_difference: int) -> int:
    return monthly_difference * 12


def move_in_cost(rent: int, deposit: int) -> int:
    return rent + deposit


@dataclass(frozen=True)
class RentRow:
    id: str
    name: str
    rent: int
    below_average: bool


def build_search_insight(homes: Sequence[RentRow], rent_budget: int) -> HomeSearchInsight:
    """Across every match, not just the page. Sponsored listings count like any other."""
    cheapest: RentRow | None = None
    for home in homes:
        if cheapest is None or home.rent < cheapest.rent:
            cheapest = home
    monthly = max(0, rent_budget - cheapest.rent) if cheapest else 0
    return HomeSearchInsight(
        rent_budget=rent_budget,
        match_count=len(homes),
        within_budget_count=sum(1 for h in homes if h.rent <= rent_budget),
        below_average_count=sum(1 for h in homes if h.below_average),
        average_rent=js_round(sum(h.rent for h in homes) / len(homes)) if homes else None,
        cheapest_home_id=cheapest.id if cheapest else None,
        cheapest_home_name=cheapest.name if cheapest else None,
        cheapest_rent=cheapest.rent if cheapest else None,
        monthly_saving_vs_budget=monthly,
        yearly_saving_vs_budget=yearly_difference(monthly),
    )
