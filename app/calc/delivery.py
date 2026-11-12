"""Delivery versus dine-in (port of src/mocks/calc/delivery.ts, with fees read from the DB)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.money import js_round
from app.schemas.food import DeliveryComparison, DeliveryFeeBreakdown

#: How many weekday lunches a month the "if you switched" line assumes.
WEEKDAY_MEALS_PER_MONTH = 22
#: The delivery fee grows per km beyond this distance.
FREE_KM = 2.0


@dataclass(frozen=True)
class Quote:
    platform: str
    item_price: int
    base_delivery_fee: int
    per_km_fee: int
    platform_fee: int
    packaging_fee: int
    gst_percent: int


def breakdown(quote: Quote, distance_km: float) -> DeliveryFeeBreakdown:
    """One platform's full bill. Each part is rounded to whole rupees, so the parts always add
    up to the total exactly. GST applies to the marked-up item price plus packaging."""
    extra_km = max(0.0, distance_km - FREE_KM)
    delivery_fee = js_round(quote.base_delivery_fee + extra_km * quote.per_km_fee)
    taxes = js_round((quote.item_price + quote.packaging_fee) * quote.gst_percent / 100)
    total = quote.item_price + delivery_fee + quote.platform_fee + quote.packaging_fee + taxes
    return DeliveryFeeBreakdown(
        platform=quote.platform,
        item_price=quote.item_price,
        delivery_fee=delivery_fee,
        platform_fee=quote.platform_fee,
        packaging_fee=quote.packaging_fee,
        taxes=taxes,
        total=total,
    )


def compare_delivery(
    *,
    listing_id: str,
    listing_name: str,
    dish: str,
    dine_in_price: int,
    quotes: Sequence[Quote],
    distance_km: float,
) -> DeliveryComparison:
    options = sorted((breakdown(q, distance_km) for q in quotes), key=lambda b: b.total)
    cheapest = options[0]
    amount_saved = cheapest.total - dine_in_price
    return DeliveryComparison(
        listing_id=listing_id,
        listing_name=listing_name,
        dish=dish,
        dine_in_price=dine_in_price,
        cheapest_delivery=cheapest,
        delivery_options=options,
        amount_saved=amount_saved,
        percent_saved=js_round(amount_saved / cheapest.total * 100) if cheapest.total > 0 else 0,
        monthly_saving_if_switched=amount_saved * WEEKDAY_MEALS_PER_MONTH,
    )


def marked_up_price(dine_in_price: int, markup_percent: int) -> int:
    """What a platform lists a dish at (used when generating quotes)."""
    return js_round(dine_in_price * (1 + markup_percent / 100))
