from __future__ import annotations

from typing import Any

from pydantic import field_validator

from app.core.constants import PriceVerdict, ProductCategory
from app.schemas.common import CamelModel, UtcDateTime
from app.schemas.offer import OfferOut
from app.schemas.validators import whole_number


class PlatformPrice(CamelModel):
    platform: str
    price: int
    mrp: int
    discount_percent: int
    in_stock: bool
    delivery_days: int
    delivery_by: UtcDateTime
    sponsored: bool
    is_cheapest: bool


class ProductSummary(CamelModel):
    id: str
    name: str
    brand: str
    category: ProductCategory
    category_label: str
    lowest_price: int
    highest_price: int
    mrp: int
    discount_percent: int
    rating: float
    review_count: int
    cheapest_platform: str
    fastest_delivery_days: int
    thumbnail_seed: int
    sponsored: bool


class ProductDetail(ProductSummary):
    description: str
    highlights: list[str]
    platforms: list[PlatformPrice]
    verdict: PriceVerdict
    verdict_reason: str
    lowest_90_day: int
    highest_90_day: int
    average_90_day: int
    above_lowest_90_day: int
    best_offer: OfferOut | None
    best_deal_platform: str
    best_deal_base_price: int
    final_price: int
    offer_saving: int
    total_saving_vs_mrp: int
    has_alert: bool
    alert_target_price: int | None


class PricePoint(CamelModel):
    date: str
    #: Platform name -> price; keys are platform names, so no camelCase conversion applies.
    prices: dict[str, int]


class PriceHistoryOut(CamelModel):
    product_id: str
    days: int
    platforms: list[str]
    points: list[PricePoint]
    lowest: int
    highest: int
    average: int
    current_lowest: int
    summary: str


class PriceAlertOut(CamelModel):
    id: str
    product_id: str
    product_name: str
    target_price: int
    current_price: int
    gap_to_target: int
    triggered: bool
    created_at: UtcDateTime


class SetPriceAlertRequest(CamelModel):
    target_price: int

    @field_validator("target_price", mode="before")
    @classmethod
    def _target(cls, value: Any) -> int:
        message = "Enter a target price in whole rupees greater than zero."
        target = whole_number(value, message)
        if target <= 0:
            raise ValueError(message)
        return target


class DeleteAlertResponse(CamelModel):
    product_id: str
