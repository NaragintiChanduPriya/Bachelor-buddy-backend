"""Offer math (port of src/mocks/calc/offers.ts)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.money import js_round
from app.schemas.offer import OfferExample


@dataclass(frozen=True)
class OfferTerms:
    id: str
    platform: str
    bank: str | None
    card_type: str | None
    discount_percent: int | None
    flat_discount: int | None
    max_discount: int | None
    min_order_value: int


@dataclass(frozen=True)
class Card:
    bank: str
    type: str


def offer_discount(order_value: int, terms: OfferTerms) -> int:
    """Below the minimum order the discount is 0; a percent offer is floor(order * % / 100)
    capped at `maxDiscount`; a flat offer is its amount, never more than the order."""
    if order_value <= 0 or order_value < terms.min_order_value:
        return 0
    discount = 0
    if terms.discount_percent is not None:
        discount = order_value * terms.discount_percent // 100
        if terms.max_discount is not None:
            discount = min(discount, terms.max_discount)
    elif terms.flat_discount is not None:
        discount = terms.flat_discount
    return max(0, min(discount, order_value))


def build_example(order_value: int, terms: OfferTerms) -> OfferExample:
    discount = offer_discount(order_value, terms)
    return OfferExample(
        order_value=order_value,
        discount=discount,
        final_price=order_value - discount,
        effective_percent=js_round(discount / order_value * 100) if order_value > 0 else 0,
    )


def card_matches(terms: OfferTerms, cards: Sequence[Card]) -> bool:
    """A card offer needs a saved card of that bank (and card type, if the offer names one)."""
    if not terms.bank:
        return True
    bank = terms.bank.lower()
    return any(
        card.bank.lower() == bank and (terms.card_type is None or card.type == terms.card_type)
        for card in cards
    )


def ineligible_reason(terms: OfferTerms, cards: Sequence[Card]) -> str | None:
    if not terms.bank or card_matches(terms, cards):
        return None
    needed = f"{terms.bank}{' ' + terms.card_type if terms.card_type else ''} card"
    same_bank = next((c for c in cards if c.bank.lower() == terms.bank.lower()), None)
    if same_bank:
        return f"Needs an {needed} — you have the {terms.bank} {same_bank.type} card"
    return f"Needs a {needed}, which you have not saved"


def days_until(valid_till: datetime, now: datetime, zone: ZoneInfo) -> int:
    """Calendar days (IST) from today to the offer's last day: 0 = ends today."""
    return (valid_till.astimezone(zone).date() - now.astimezone(zone).date()).days


def is_live(valid_from: datetime, valid_till: datetime, now: datetime) -> bool:
    return valid_from <= now < valid_till


@dataclass(frozen=True)
class Application:
    offer_id: str
    original_price: int
    discount: int

    @property
    def final_price(self) -> int:
        return self.original_price - self.discount


def best_offer_for(price: int, platform: str, usable: Sequence[OfferTerms]) -> Application | None:
    """The usable offer that takes the most off on this platform."""
    best: Application | None = None
    for terms in usable:
        if terms.platform != platform:
            continue
        discount = offer_discount(price, terms)
        if discount <= 0:
            continue
        if best is None or discount > best.discount:
            best = Application(terms.id, price, discount)
    return best
