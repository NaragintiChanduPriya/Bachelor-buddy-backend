from __future__ import annotations

from app.core.constants import FoodPlaceType
from app.schemas.common import CamelModel


class MenuItemOut(CamelModel):
    id: str
    name: str
    price: int
    veg: bool
    popular: bool


class FoodListingSummary(CamelModel):
    id: str
    name: str
    type: FoodPlaceType
    area_id: str
    area_name: str
    veg: bool
    rating: float
    review_count: int
    price_min: int
    price_max: int
    avg_meal_price: int
    distance_from_home_km: float
    distance_from_office_km: float
    tags: list[str]
    open_now: bool
    timings: str
    thumbnail_seed: int
    sponsored: bool
    monthly_plan_price: int | None


class FoodListingDetail(FoodListingSummary):
    description: str
    address: str
    menu: list[MenuItemOut]
    opening_time: str
    closing_time: str
    delivery_available: bool


class DeliveryFeeBreakdown(CamelModel):
    platform: str
    item_price: int
    delivery_fee: int
    platform_fee: int
    packaging_fee: int
    taxes: int
    total: int


class DeliveryComparison(CamelModel):
    listing_id: str
    listing_name: str
    dish: str
    dine_in_price: int
    cheapest_delivery: DeliveryFeeBreakdown
    delivery_options: list[DeliveryFeeBreakdown]
    amount_saved: int
    percent_saved: int
    monthly_saving_if_switched: int
