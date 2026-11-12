"""Food listings: nearby search, detail, delivery-versus-dine-in."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.calc.delivery import Quote, compare_delivery
from app.calc.geo import walking_distance_km
from app.core.errors import BadRequestError, NotFoundError
from app.db.models import Area, DeliveryQuote, FoodListing
from app.schemas.common import PaginationMeta
from app.schemas.food import DeliveryComparison, FoodListingDetail, FoodListingSummary, MenuItemOut
from app.services.context import Ctx

PLAN_PREFIXES = ("Monthly", "Weekly")


def format_hhmm(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def is_open_at(opening: time, closing: time, local: datetime) -> bool:
    """Inclusive window; a closing time past midnight (e.g. 01:00) wraps around."""
    now = local.hour * 60 + local.minute
    start = opening.hour * 60 + opening.minute
    end = closing.hour * 60 + closing.minute
    return (now >= start or now <= end) if end < start else start <= now <= end


@dataclass(frozen=True)
class Anchors:
    home: Area
    office: Area


def anchors_for(ctx: Ctx) -> Anchors:
    prefs = ctx.prefs
    assert prefs.home_area is not None  # noqa: S101 - guaranteed once onboarded
    assert prefs.office_area is not None  # noqa: S101
    return Anchors(prefs.home_area, prefs.office_area)


def to_summary(listing: FoodListing, anchors: Anchors, local_now: datetime) -> FoodListingSummary:
    return FoodListingSummary(
        id=listing.id,
        name=listing.name,
        type=listing.type,  # type: ignore[arg-type]
        area_id=listing.area_id,
        area_name=listing.area.name,
        veg=listing.veg,
        rating=listing.rating,
        review_count=listing.review_count,
        price_min=listing.price_min,
        price_max=listing.price_max,
        avg_meal_price=listing.avg_meal_price,
        distance_from_home_km=walking_distance_km(
            anchors.home.lat, anchors.home.lng, listing.lat, listing.lng
        ),
        distance_from_office_km=walking_distance_km(
            anchors.office.lat, anchors.office.lng, listing.lat, listing.lng
        ),
        tags=list(listing.tags),
        open_now=is_open_at(listing.opening_time, listing.closing_time, local_now),
        timings=f"{format_hhmm(listing.opening_time)} – {format_hhmm(listing.closing_time)}",  # noqa: RUF001 - en dash, as the contract
        thumbnail_seed=listing.thumbnail_seed,
        sponsored=listing.sponsored,
        monthly_plan_price=listing.monthly_plan_price,
    )


async def search(
    ctx: Ctx,
    *,
    area: str | None = None,
    place_type: str | None = None,
    veg_only: bool = False,
    max_price: int | None = None,
    sort: str = "price",
    near: str = "home",
) -> list[FoodListingSummary]:
    """Filtered and honestly sorted, unpaginated (shared by the endpoint and the agents).
    Sponsored listings keep the position the sort gives them."""
    query = select(FoodListing).options(joinedload(FoodListing.area))
    if area:
        query = query.where(FoodListing.area_id == area)
    if place_type:
        query = query.where(FoodListing.type == place_type)
    if veg_only:
        query = query.where(FoodListing.veg.is_(True))
    if max_price is not None:
        query = query.where(FoodListing.avg_meal_price <= max_price)
    listings = (await ctx.session.scalars(query)).all()
    anchors = anchors_for(ctx)
    local_now = ctx.clock.local_now()
    items = [to_summary(listing, anchors, local_now) for listing in listings]

    def distance(item: FoodListingSummary) -> float:
        return item.distance_from_office_km if near == "office" else item.distance_from_home_km

    if sort == "distance":
        items.sort(key=lambda i: (distance(i), i.id))
    elif sort == "rating":
        items.sort(key=lambda i: (-i.rating, i.id))
    else:
        items.sort(key=lambda i: (i.avg_meal_price, i.id))
    return items


def paginate[T](items: list[T], page: int, page_size: int) -> tuple[list[T], PaginationMeta]:
    start = (page - 1) * page_size
    return items[start : start + page_size], PaginationMeta(
        page=page, page_size=page_size, total=len(items)
    )


async def _listing_with_menu(ctx: Ctx, listing_id: str) -> FoodListing:
    listing = (
        (
            await ctx.session.execute(
                select(FoodListing)
                .options(joinedload(FoodListing.area), joinedload(FoodListing.menu))
                .where(FoodListing.id == listing_id)
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if listing is None:
        raise NotFoundError.resource("Food listing")
    return listing


async def detail(ctx: Ctx, listing_id: str) -> FoodListingDetail:
    listing = await _listing_with_menu(ctx, listing_id)
    summary = to_summary(listing, anchors_for(ctx), ctx.clock.local_now())
    return FoodListingDetail(
        **summary.model_dump(),
        description=listing.description,
        address=listing.address,
        menu=[
            MenuItemOut(id=m.id, name=m.name, price=m.price, veg=m.veg, popular=m.popular)
            for m in listing.menu
        ],
        opening_time=format_hhmm(listing.opening_time),
        closing_time=format_hhmm(listing.closing_time),
        delivery_available=listing.delivery_available,
    )


async def delivery_comparison(ctx: Ctx, listing_id: str, dish: str | None) -> DeliveryComparison:
    """The same dish eaten there versus delivered to the user's office (where a weekday lunch is
    eaten). Defaults to a popular main, never a meal plan."""
    listing = await _listing_with_menu(ctx, listing_id)
    if not listing.delivery_available:
        raise BadRequestError(f"{listing.name} does not deliver, so there is nothing to compare.")
    dishes = [m for m in listing.menu if not m.name.startswith(PLAN_PREFIXES)] or listing.menu
    chosen = (
        next((m for m in listing.menu if dish and m.name.lower() == dish.strip().lower()), None)
        or next((m for m in dishes if m.popular), None)
        or dishes[0]
    )
    rows = await ctx.session.scalars(
        select(DeliveryQuote)
        .options(joinedload(DeliveryQuote.platform))
        .where(DeliveryQuote.menu_item_id == chosen.id)
    )
    quotes = [
        Quote(
            platform=q.platform.name,
            item_price=q.item_price,
            base_delivery_fee=q.base_delivery_fee,
            per_km_fee=q.platform.per_km_fee,
            platform_fee=q.platform_fee,
            packaging_fee=q.packaging_fee,
            gst_percent=q.platform.gst_percent,
        )
        for q in rows
    ]
    if not quotes:
        raise BadRequestError(f"No delivery app lists {chosen.name} from {listing.name}.")
    office = anchors_for(ctx).office
    return compare_delivery(
        listing_id=listing.id,
        listing_name=listing.name,
        dish=chosen.name,
        dine_in_price=chosen.price,
        quotes=quotes,
        distance_km=walking_distance_km(office.lat, office.lng, listing.lat, listing.lng),
    )
