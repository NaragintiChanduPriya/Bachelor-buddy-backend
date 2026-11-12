"""Offers: live offers turned into the API shape for the current user and clock."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.calc.offers import (
    Card,
    OfferTerms,
    build_example,
    card_matches,
    days_until,
    ineligible_reason,
)
from app.core.constants import EXPIRING_SOON_DAYS, TYPICAL_ORDER_VALUE
from app.core.errors import BadRequestError
from app.db.models import Offer
from app.schemas.offer import OfferOut, OffersResponse
from app.services.context import Ctx


def terms_of(offer: Offer) -> OfferTerms:
    return OfferTerms(
        id=offer.id,
        platform=offer.platform,
        bank=offer.bank,
        card_type=offer.card_type,
        discount_percent=offer.discount_percent,
        flat_discount=offer.flat_discount,
        max_discount=offer.max_discount,
        min_order_value=offer.min_order_value,
    )


def user_cards(ctx: Ctx) -> list[Card]:
    return [Card(bank=c.bank, type=c.card_type) for c in ctx.user.cards]


def to_offer_out(offer: Offer, cards: list[Card], now: datetime, zone: ZoneInfo) -> OfferOut:
    terms = terms_of(offer)
    days_left = days_until(offer.valid_till, now, zone)
    order_value = max(TYPICAL_ORDER_VALUE[offer.platform_category], offer.min_order_value)
    return OfferOut(
        id=offer.id,
        kind=offer.kind,  # type: ignore[arg-type]
        title=offer.title,
        description=offer.description,
        platform=offer.platform,
        platform_category=offer.platform_category,  # type: ignore[arg-type]
        bank=offer.bank,
        card_type=offer.card_type,  # type: ignore[arg-type]
        code=offer.code,
        discount_percent=offer.discount_percent,
        flat_discount=offer.flat_discount,
        max_discount=offer.max_discount,
        min_order_value=offer.min_order_value,
        valid_from=offer.valid_from,
        valid_till=offer.valid_till,
        expiring_soon=days_left <= EXPIRING_SOON_DAYS,
        days_left=max(0, days_left),
        eligible=card_matches(terms, cards),
        ineligible_reason=ineligible_reason(terms, cards),
        example=build_example(order_value, terms),
    )


async def live_offer_rows(ctx: Ctx) -> list[Offer]:
    now = ctx.clock.now()
    return list(
        await ctx.session.scalars(
            select(Offer).where(Offer.valid_from <= now, Offer.valid_till > now)
        )
    )


async def live_offer_pairs(ctx: Ctx) -> list[tuple[Offer, OfferOut]]:
    """Every live offer (row and API shape), soonest-ending first, then by example saving."""
    cards = user_cards(ctx)
    now = ctx.clock.now()
    pairs = [(o, to_offer_out(o, cards, now, ctx.clock.zone)) for o in await live_offer_rows(ctx)]
    pairs.sort(key=lambda pair: (pair[1].days_left, -pair[1].example.discount, pair[1].id))
    return pairs


async def live_offers(ctx: Ctx) -> list[OfferOut]:
    return [out for _, out in await live_offer_pairs(ctx)]


async def usable_offers(ctx: Ctx) -> list[OfferOut]:
    return [o for o in await live_offers(ctx) if o.eligible]


async def offers_response(
    ctx: Ctx,
    *,
    platform: str | None,
    card: str | None,
    expiring_within_days: int | None,
    eligible_only: bool,
) -> OffersResponse:
    all_live = await live_offers(ctx)
    offers = [o for o in all_live if o.eligible] if eligible_only else list(all_live)
    if platform:
        offers = [o for o in offers if o.platform.lower() == platform.lower()]
    if card:
        saved = next((c for c in ctx.user.cards if c.card_id == card), None)
        if saved is None:
            raise BadRequestError(f'"{card}" is not one of your saved cards.')
        chosen = [Card(bank=saved.bank, type=saved.card_type)]
        offers = [
            o
            for o in offers
            if o.bank is not None
            and card_matches(
                OfferTerms(o.id, o.platform, o.bank, o.card_type, None, None, None, 0), chosen
            )
        ]
    if expiring_within_days is not None:
        offers = [o for o in offers if o.days_left <= expiring_within_days]
    usable = [o for o in all_live if o.eligible]
    return OffersResponse(
        offers=offers,
        total_count=len(all_live),
        eligible_count=len(usable),
        expiring_soon_count=sum(1 for o in usable if o.expiring_soon),
        biggest_example_saving=max((o.example.discount for o in usable), default=0),
    )
