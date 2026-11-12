"""Food, groceries, products, offers and homes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CtxDep
from app.api.params import Page, PageSize, check_choice, check_positive, optional_choice
from app.core.constants import (
    FOOD_PLACE_TYPES,
    GROCERY_CATEGORIES,
    HISTORY_DAYS_API,
    HOME_TYPES,
    PRODUCT_CATEGORY_LABELS,
)
from app.core.errors import BadRequestError
from app.db.models import Area, TechPark
from app.schemas.common import Envelope, PaginationMeta, ok
from app.schemas.food import DeliveryComparison, FoodListingDetail, FoodListingSummary
from app.schemas.grocery import (
    GroceryCatalogItem,
    GroceryComparison,
    GroceryListOut,
    UpdateGroceryListRequest,
)
from app.schemas.home import HomeDetail, HomeSearchResponse
from app.schemas.offer import OffersResponse
from app.schemas.product import (
    DeleteAlertResponse,
    PriceAlertOut,
    PriceHistoryOut,
    ProductDetail,
    ProductSummary,
    SetPriceAlertRequest,
)
from app.services import food as food_service
from app.services import groceries as grocery_service
from app.services import homes as home_service
from app.services import offers as offer_service
from app.services import products as product_service
from app.services.context import Ctx

router = APIRouter()


async def _check_area(ctx: Ctx, area: str | None) -> str | None:
    area = optional_choice(area)
    if area is not None and await ctx.session.get(Area, area) is None:
        raise BadRequestError(f'Unknown area "{area}".')
    return area


# ------------------------------------------------------------------ food


@router.get("/food/nearby", tags=["food"], summary="Cheap meals near home or office")
async def food_nearby(
    ctx: CtxDep,
    area: Annotated[str | None, Query()] = None,
    near: Annotated[str | None, Query()] = None,
    max_price: Annotated[float | None, Query(alias="maxPrice")] = None,
    type: Annotated[str | None, Query()] = None,
    veg: Annotated[bool | None, Query()] = None,
    sort: Annotated[str | None, Query()] = None,
    page: Page = 1,
    page_size: PageSize = 12,
) -> Envelope[list[FoodListingSummary]]:
    anchor = optional_choice(near) or "home"
    if anchor not in {"home", "office"}:
        raise BadRequestError('The near parameter must be "home" or "office".')
    place_type = check_choice(type, FOOD_PLACE_TYPES, 'Unknown food type "{value}".')
    order = (
        check_choice(
            sort,
            ("price", "distance", "rating"),
            'Unknown sort "{value}". Use price, distance or rating.',
        )
        or "price"
    )
    check_positive(max_price, "maxPrice")
    items = await food_service.search(
        ctx,
        area=await _check_area(ctx, area),
        place_type=place_type,
        veg_only=veg is True,
        max_price=int(max_price) if max_price is not None else None,
        sort=order,
        near=anchor,
    )
    page_items, meta = food_service.paginate(items, page, page_size)
    return ok(page_items, meta)


@router.get("/food/{listing_id}/compare-delivery", tags=["food"], summary="Delivery vs dine-in")
async def food_compare_delivery(
    listing_id: str, ctx: CtxDep, dish: Annotated[str | None, Query(max_length=120)] = None
) -> Envelope[DeliveryComparison]:
    return ok(await food_service.delivery_comparison(ctx, listing_id, optional_choice(dish)))


@router.get("/food/{listing_id}", tags=["food"], summary="One listing with its full menu")
async def food_detail(listing_id: str, ctx: CtxDep) -> Envelope[FoodListingDetail]:
    return ok(await food_service.detail(ctx, listing_id))


# ------------------------------------------------------------------ groceries


@router.get("/groceries/catalog", tags=["groceries"], summary="Every item the list can contain")
async def grocery_catalog(
    ctx: CtxDep,
    q: Annotated[str | None, Query(max_length=80)] = None,
    category: Annotated[str | None, Query()] = None,
) -> Envelope[list[GroceryCatalogItem]]:
    chosen = optional_choice(category)
    if chosen is not None and chosen not in GROCERY_CATEGORIES:
        raise BadRequestError(
            f'Unknown grocery category "{chosen}".', {"categories": list(GROCERY_CATEGORIES)}
        )
    return ok(await grocery_service.catalog_items(ctx, q, chosen))


@router.get(
    "/groceries/list",
    tags=["groceries"],
    summary="This month's list, each line at its cheapest store",
)
async def grocery_list(ctx: CtxDep) -> Envelope[GroceryListOut]:
    return ok(await grocery_service.current_list(ctx))


@router.put("/groceries/list", tags=["groceries"], summary="Replace the whole list")
async def replace_grocery_list(
    body: UpdateGroceryListRequest, ctx: CtxDep
) -> Envelope[GroceryListOut]:
    return ok(await grocery_service.replace_list(ctx, body))


@router.get(
    "/groceries/compare", tags=["groceries"], summary="The list priced at all four store types"
)
async def grocery_compare(ctx: CtxDep) -> Envelope[GroceryComparison]:
    return ok(await grocery_service.comparison(ctx))


# ------------------------------------------------------------------ products


@router.get("/products/search", tags=["products"], summary="Products across three platforms")
async def product_search(
    ctx: CtxDep,
    q: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    max_price: Annotated[float | None, Query(alias="maxPrice")] = None,
    sort: Annotated[str | None, Query()] = None,
    page: Page = 1,
    page_size: PageSize = 12,
) -> Envelope[list[ProductSummary]]:
    text = (q or "").strip()
    if len(text) > 80:
        raise BadRequestError("Keep the search under 80 characters.")
    chosen = check_choice(category, PRODUCT_CATEGORY_LABELS, 'Unknown category "{value}".')
    order = (
        check_choice(
            sort,
            ("price", "rating", "discount"),
            'Unknown sort "{value}". Use price, rating or discount.',
        )
        or "price"
    )
    check_positive(max_price, "maxPrice")
    items, total = await product_service.search(
        ctx.session,
        q=text or None,
        category=chosen,
        max_price=int(max_price) if max_price is not None else None,
        sort=order,
        page=page,
        page_size=page_size,
    )
    return ok(items, PaginationMeta(page=page, page_size=page_size, total=total))


@router.get("/products/alerts", tags=["products"], summary="Your price alerts with today's price")
async def product_alerts(ctx: CtxDep) -> Envelope[list[PriceAlertOut]]:
    return ok(await product_service.alerts(ctx))


@router.get(
    "/products/{product_id}/price-history", tags=["products"], summary="Daily price per platform"
)
async def product_price_history(
    product_id: str, ctx: CtxDep, days: Annotated[int, Query()] = HISTORY_DAYS_API
) -> Envelope[PriceHistoryOut]:
    if not 7 <= days <= HISTORY_DAYS_API:
        raise BadRequestError(
            f"The days parameter must be a whole number from 7 to {HISTORY_DAYS_API}."
        )
    return ok(await product_service.price_history(ctx, product_id, days))


@router.post(
    "/products/{product_id}/price-alert", tags=["products"], summary="Create or move a price alert"
)
async def set_price_alert(
    product_id: str, body: SetPriceAlertRequest, ctx: CtxDep
) -> Envelope[PriceAlertOut]:
    return ok(await product_service.set_alert(ctx, product_id, body.target_price))


@router.delete(
    "/products/{product_id}/price-alert", tags=["products"], summary="Remove a price alert"
)
async def delete_price_alert(product_id: str, ctx: CtxDep) -> Envelope[DeleteAlertResponse]:
    return ok(await product_service.delete_alert(ctx, product_id))


@router.get("/products/{product_id}", tags=["products"], summary="Prices, verdict and best offer")
async def product_detail(product_id: str, ctx: CtxDep) -> Envelope[ProductDetail]:
    return ok(await product_service.detail(ctx, product_id))


# ------------------------------------------------------------------ offers


@router.get("/offers", tags=["offers"], summary="Live offers, by default only the ones you can use")
async def offers(
    ctx: CtxDep,
    platform: Annotated[str | None, Query(max_length=40)] = None,
    card: Annotated[str | None, Query(max_length=40)] = None,
    expiring_within_days: Annotated[float | None, Query(alias="expiringWithinDays")] = None,
    eligible_only: Annotated[bool, Query(alias="eligibleOnly")] = True,
) -> Envelope[OffersResponse]:
    within: int | None = None
    if expiring_within_days is not None:
        if not expiring_within_days.is_integer() or not 0 <= expiring_within_days <= 60:
            raise BadRequestError("expiringWithinDays must be a whole number from 0 to 60.")
        within = int(expiring_within_days)
    return ok(
        await offer_service.offers_response(
            ctx,
            platform=optional_choice(platform),
            card=optional_choice(card),
            expiring_within_days=within,
            eligible_only=eligible_only,
        )
    )


# ------------------------------------------------------------------ homes


@router.get(
    "/homes/search", tags=["homes"], summary="PGs, co-living and shared flats vs the area average"
)
async def home_search(
    ctx: CtxDep,
    area: Annotated[str | None, Query()] = None,
    max_rent: Annotated[float | None, Query(alias="maxRent")] = None,
    type: Annotated[str | None, Query()] = None,
    food_included: Annotated[bool | None, Query(alias="foodIncluded")] = None,
    max_distance_km: Annotated[float | None, Query(alias="maxDistanceKm")] = None,
    tech_park: Annotated[str | None, Query(alias="techPark")] = None,
    page: Page = 1,
    page_size: PageSize = 12,
) -> Envelope[HomeSearchResponse]:
    home_type = check_choice(
        type, HOME_TYPES, 'Unknown home type "{value}". Use pg, coliving or sharedFlat.'
    )
    park = optional_choice(tech_park)
    if park is not None and await ctx.session.get(TechPark, park) is None:
        raise BadRequestError(f'Unknown tech park "{park}".')
    check_positive(max_rent, "maxRent")
    check_positive(max_distance_km, "maxDistanceKm")
    data, meta = await home_service.search_page(
        ctx,
        page=page,
        page_size=page_size,
        area=await _check_area(ctx, area),
        home_type=home_type,
        max_rent=int(max_rent) if max_rent is not None else None,
        food_included=food_included,
        max_distance_km=max_distance_km,
        tech_park=park,
    )
    return ok(data, meta)


@router.get("/homes/{home_id}", tags=["homes"], summary="One home with commutes and move-in cost")
async def home_detail(home_id: str, ctx: CtxDep) -> Envelope[HomeDetail]:
    return ok(await home_service.detail(ctx, home_id))
