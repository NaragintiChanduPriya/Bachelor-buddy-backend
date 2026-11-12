from __future__ import annotations

from app.core.constants import HomeType, SharingType
from app.schemas.common import CamelModel, UtcDateTime


class CommuteInfo(CamelModel):
    tech_park_id: str
    tech_park_name: str
    tech_park_area_name: str
    distance_km: float
    bike_minutes: int
    bus_minutes: int


class HomeSummary(CamelModel):
    id: str
    name: str
    type: HomeType
    type_label: str
    area_id: str
    area_name: str
    rent: int
    deposit: int
    sharing: SharingType
    sharing_label: str
    food_included: bool
    bachelor_friendly: bool
    area_average_rent: int
    difference_from_average: int
    below_average: bool
    nearest_tech_park_km: float
    nearest_tech_park_name: str
    tech_park_distance_km: float | None
    tech_park_name: str | None
    rating: float
    review_count: int
    thumbnail_seed: int
    sponsored: bool


class HomeDetail(HomeSummary):
    description: str
    address: str
    amenities: list[str]
    food_details: str | None
    meals_per_day: int | None
    notice_period_days: int
    maintenance_included: bool
    commutes: list[CommuteInfo]
    available_from: UtcDateTime
    available_now: bool
    move_in_cost: int
    yearly_difference_from_average: int
    rent_budget: int
    difference_from_rent_budget: int


class HomeSearchInsight(CamelModel):
    rent_budget: int
    match_count: int
    within_budget_count: int
    below_average_count: int
    average_rent: int | None
    cheapest_home_id: str | None
    cheapest_home_name: str | None
    cheapest_rent: int | None
    monthly_saving_vs_budget: int
    yearly_saving_vs_budget: int


class HomeSearchResponse(CamelModel):
    homes: list[HomeSummary]
    insight: HomeSearchInsight
