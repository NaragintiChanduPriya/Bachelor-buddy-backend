"""Homes: search with the area-average comparison and the rent-budget insight, and detail."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.calc.homes import (
    RentRow,
    build_search_insight,
    compare_with_area_average,
    move_in_cost,
    yearly_difference,
)
from app.core.constants import HOME_TYPE_LABELS
from app.core.errors import NotFoundError
from app.db.models import AreaRentAverage, Home, HomeCommute, TechPark
from app.schemas.common import PaginationMeta
from app.schemas.home import CommuteInfo, HomeDetail, HomeSearchResponse, HomeSummary
from app.services import budget as budget_service
from app.services.context import Ctx
from app.services.food import paginate

HOME_OPTIONS = (
    joinedload(Home.area),
    joinedload(Home.commutes).joinedload(HomeCommute.tech_park).joinedload(TechPark.area),
)


def sharing_label(home_type: str, sharing: str) -> str:
    if home_type == "sharedFlat":
        return {"single": "Private room", "entireFlat": "Entire flat"}.get(sharing, "Shared room")
    return {
        "single": "Single room",
        "double": "Double sharing",
        "triple": "Triple sharing",
        "entireFlat": "Entire flat",
    }[sharing]


async def _area_averages(ctx: Ctx) -> dict[tuple[str, str], int]:
    rows = await ctx.session.scalars(select(AreaRentAverage))
    return {(r.area_id, r.home_type): r.average_rent for r in rows}


async def rent_budget(ctx: Ctx) -> int:
    """The user's monthly rent budget, read live so a budget edit changes the comparison."""
    budget = await budget_service.ensure_budget(ctx.session, ctx.user, ctx.clock.month_key())
    return budget_service.limits_of(budget).get("rent", 0)


def reference_park(ctx: Ctx, tech_park: str | None) -> str | None:
    """Distances are measured to the tech park asked for, else the user's own."""
    return tech_park or ctx.prefs.tech_park_id


def _commutes(home: Home) -> list[CommuteInfo]:
    return [
        CommuteInfo(
            tech_park_id=c.tech_park_id,
            tech_park_name=c.tech_park.name,
            tech_park_area_name=c.tech_park.area.name,
            distance_km=c.distance_km,
            bike_minutes=c.bike_minutes,
            bus_minutes=c.bus_minutes,
        )
        for c in sorted(home.commutes, key=lambda c: (c.distance_km, c.tech_park_id))
    ]


def to_summary(
    home: Home, averages: dict[tuple[str, str], int], park_id: str | None
) -> HomeSummary:
    commutes = _commutes(home)
    nearest = commutes[0]
    anchor = next((c for c in commutes if c.tech_park_id == park_id), None)
    comparison = compare_with_area_average(
        home.rent, averages.get((home.area_id, home.type), home.rent)
    )
    return HomeSummary(
        id=home.id,
        name=home.name,
        type=home.type,  # type: ignore[arg-type]
        type_label=HOME_TYPE_LABELS[home.type],
        area_id=home.area_id,
        area_name=home.area.name,
        rent=home.rent,
        deposit=home.deposit,
        sharing=home.sharing,  # type: ignore[arg-type]
        sharing_label=sharing_label(home.type, home.sharing),
        food_included=home.food_included,
        bachelor_friendly=home.bachelor_friendly,
        area_average_rent=comparison.area_average_rent,
        difference_from_average=comparison.difference_from_average,
        below_average=comparison.below_average,
        nearest_tech_park_km=nearest.distance_km,
        nearest_tech_park_name=nearest.tech_park_name,
        tech_park_distance_km=anchor.distance_km if anchor else None,
        tech_park_name=anchor.tech_park_name if anchor else None,
        rating=home.rating,
        review_count=home.review_count,
        thumbnail_seed=home.thumbnail_seed,
        sponsored=home.sponsored,
    )


async def search(
    ctx: Ctx,
    *,
    area: str | None = None,
    home_type: str | None = None,
    max_rent: int | None = None,
    food_included: bool | None = None,
    max_distance_km: float | None = None,
    tech_park: str | None = None,
) -> list[HomeSummary]:
    """Every match, cheapest first with rating breaking ties. Sponsored listings keep the
    position this honest sort gives them."""
    query = select(Home).options(*HOME_OPTIONS)
    if area:
        query = query.where(Home.area_id == area)
    if home_type:
        query = query.where(Home.type == home_type)
    if max_rent is not None:
        query = query.where(Home.rent <= max_rent)
    if food_included is not None:
        query = query.where(Home.food_included.is_(food_included))
    homes = (await ctx.session.execute(query)).unique().scalars().all()
    averages = await _area_averages(ctx)
    park_id = reference_park(ctx, tech_park)
    summaries = [to_summary(h, averages, park_id) for h in homes]
    if max_distance_km is not None:
        summaries = [
            s
            for s in summaries
            if (
                s.tech_park_distance_km
                if s.tech_park_distance_km is not None
                else s.nearest_tech_park_km
            )
            <= max_distance_km
        ]
    summaries.sort(key=lambda s: (s.rent, -s.rating, s.id))
    return summaries


async def search_page(
    ctx: Ctx, *, page: int, page_size: int, **filters: object
) -> tuple[HomeSearchResponse, PaginationMeta]:
    matches = await search(ctx, **filters)  # type: ignore[arg-type]
    insight = build_search_insight(
        [RentRow(h.id, h.name, h.rent, h.below_average) for h in matches], await rent_budget(ctx)
    )
    page_items, meta = paginate(matches, page, page_size)
    return HomeSearchResponse(homes=page_items, insight=insight), meta


async def detail(ctx: Ctx, home_id: str) -> HomeDetail:
    home = (
        (await ctx.session.execute(select(Home).options(*HOME_OPTIONS).where(Home.id == home_id)))
        .unique()
        .scalar_one_or_none()
    )
    if home is None:
        raise NotFoundError.resource("Home")
    summary = to_summary(home, await _area_averages(ctx), reference_park(ctx, None))
    budget = await rent_budget(ctx)
    now = ctx.clock.now()
    return HomeDetail(
        **summary.model_dump(),
        description=home.description,
        address=home.address,
        amenities=list(home.amenities),
        food_details=home.food_details,
        meals_per_day=home.meals_per_day,
        notice_period_days=home.notice_period_days,
        maintenance_included=home.maintenance_included,
        commutes=_commutes(home),
        available_from=home.available_from,
        available_now=home.available_from <= now,
        move_in_cost=move_in_cost(home.rent, home.deposit),
        yearly_difference_from_average=yearly_difference(summary.difference_from_average),
        rent_budget=budget,
        difference_from_rent_budget=home.rent - budget,
    )
