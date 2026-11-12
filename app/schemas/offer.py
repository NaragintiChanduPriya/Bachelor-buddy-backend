from __future__ import annotations

from app.core.constants import CardType, OfferKind, OfferPlatformCategory
from app.schemas.common import CamelModel, UtcDateTime


class OfferExample(CamelModel):
    order_value: int
    discount: int
    final_price: int
    effective_percent: int


class OfferOut(CamelModel):
    id: str
    kind: OfferKind
    title: str
    description: str
    platform: str
    platform_category: OfferPlatformCategory
    bank: str | None
    card_type: CardType | None
    code: str | None
    discount_percent: int | None
    flat_discount: int | None
    max_discount: int | None
    min_order_value: int
    valid_from: UtcDateTime
    valid_till: UtcDateTime
    expiring_soon: bool
    days_left: int
    eligible: bool
    ineligible_reason: str | None
    example: OfferExample


class OffersResponse(CamelModel):
    offers: list[OfferOut]
    total_count: int
    eligible_count: int
    expiring_soon_count: int
    biggest_example_saving: int
