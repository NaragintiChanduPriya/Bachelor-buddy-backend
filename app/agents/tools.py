"""Specialist tools. Each validates its arguments with Pydantic, calls the same service the REST
endpoint uses, records what it found in the Evidence, and returns compact JSON for the model."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select

from app.agents.evidence import Evidence
from app.calc.grocery import to_plan_summary
from app.calc.offers import best_offer_for
from app.core.clock import month_bounds, shift_month
from app.core.errors import AppError
from app.db.models import Area, Expense
from app.schemas.expense import CreateExpenseRequest
from app.schemas.food import FoodListingSummary
from app.schemas.home import HomeSummary
from app.schemas.offer import OfferOut
from app.schemas.product import ProductSummary
from app.services import budget as budget_service
from app.services import expenses as expense_service
from app.services import food as food_service
from app.services import groceries as grocery_service
from app.services import homes as home_service
from app.services import notifications as notification_service
from app.services import offers as offer_service
from app.services import products as product_service
from app.services import savings as savings_service
from app.services.context import Ctx

logger = logging.getLogger(__name__)

WALKABLE_KM = 2.5
LIST_LIMIT = 5


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


Handler = Callable[[Ctx, Evidence, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    agent: str
    description: str
    args: type[Args]
    step: str
    handler: Handler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": compact_schema(self.args.model_json_schema()),
            },
        }


def compact_schema(schema: Any) -> Any:
    """Drop the `title` annotations Pydantic adds, to save prompt tokens. A *property* named
    "title" (like log_expense's) is a field, not an annotation, so it is kept."""
    if isinstance(schema, list):
        return [compact_schema(v) for v in schema]
    if not isinstance(schema, dict):
        return schema
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title" and isinstance(value, str):
            continue
        if key in {"properties", "$defs"} and isinstance(value, dict):
            result[key] = {name: compact_schema(sub) for name, sub in value.items()}
        else:
            result[key] = compact_schema(value)
    return result


# ------------------------------------------------------------------ compact shapes


def food_brief(item: FoodListingSummary, near: str) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "type": item.type,
        "area": item.area_name,
        "avgMealPrice": item.avg_meal_price,
        "distanceKm": item.distance_from_office_km
        if near == "office"
        else item.distance_from_home_km,
        "openNow": item.open_now,
        "veg": item.veg,
        "rating": item.rating,
        "monthlyPlanPrice": item.monthly_plan_price,
    }


def product_brief(item: ProductSummary) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "brand": item.brand,
        "lowestPrice": item.lowest_price,
        "mrp": item.mrp,
        "cheapestPlatform": item.cheapest_platform,
        "fastestDeliveryDays": item.fastest_delivery_days,
        "rating": item.rating,
        "sponsored": item.sponsored,
    }


def home_brief(item: HomeSummary) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "type": item.type,
        "area": item.area_name,
        "rent": item.rent,
        "areaAverageRent": item.area_average_rent,
        "differenceFromAverage": item.difference_from_average,
        "foodIncluded": item.food_included,
        "techParkDistanceKm": item.tech_park_distance_km,
        "sponsored": item.sponsored,
    }


def offer_brief(item: OfferOut) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "platform": item.platform,
        "daysLeft": item.days_left,
        "minOrderValue": item.min_order_value,
        "example": item.example.model_dump(by_alias=True),
    }


# ------------------------------------------------------------------ budget


class NoArgs(Args):
    pass


class CategoryArgs(Args):
    category: Literal["rent", "food", "groceries", "shopping", "travel", "bills", "misc"]


class LogExpenseArgs(Args):
    category: Literal["rent", "food", "groceries", "shopping", "travel", "bills", "misc", "savings"]
    title: str = Field(min_length=1, max_length=120)
    amount: int = Field(gt=0, le=1_000_000)
    merchant: str | None = Field(default=None, max_length=120)


async def get_budget_status(ctx: Ctx, ev: Evidence, _: NoArgs) -> dict[str, Any]:
    budget = await budget_service.current_budget(ctx.session, ctx.user, ctx.clock)
    ev.budget = budget.categories
    return budget.model_dump(by_alias=True)


async def get_category_spending(ctx: Ctx, ev: Evidence, args: CategoryArgs) -> dict[str, Any]:
    budget = await budget_service.current_budget(ctx.session, ctx.user, ctx.clock)
    ev.budget = budget.categories
    row = next(c for c in budget.categories if c.id == args.category)
    start, end = month_bounds(budget.month, ctx.clock.zone)
    count, delivery_count, delivery_total = (
        await ctx.session.execute(
            select(
                func.count(),
                func.count().filter(Expense.source == "delivery"),
                func.coalesce(func.sum(Expense.amount).filter(Expense.source == "delivery"), 0),
            ).where(
                Expense.user_id == ctx.user.id,
                Expense.category == args.category,
                Expense.spent_at >= start,
                Expense.spent_at < end,
            )
        )
    ).one()
    return {
        **row.model_dump(by_alias=True),
        "expenseCount": int(count),
        "deliveryOrders": int(delivery_count),
        "deliveryTotal": int(delivery_total),
    }


async def log_expense(ctx: Ctx, ev: Evidence, args: LogExpenseArgs) -> dict[str, Any]:
    created = await expense_service.create_expense(
        ctx,
        CreateExpenseRequest(
            category=args.category, title=args.title, amount=args.amount, merchant=args.merchant
        ),
    )
    return {
        "logged": created.expense.model_dump(by_alias=True, mode="json"),
        "category": created.category.model_dump(by_alias=True),
    }


# ------------------------------------------------------------------ food


FoodSort = Literal["price", "priceDesc", "distance", "rating"]


class FoodSearchArgs(Args):
    near: Literal["home", "office"] = "office"
    max_price: int | None = Field(default=None, gt=0, le=5000)
    place_type: Literal["darshini", "mess", "tiffin", "restaurant"] | None = None
    open_now: bool = True
    #: The order the user asked for ("lowest to highest" is price, "nearest" is distance).
    sort: FoodSort = "price"
    limit: int = Field(default=LIST_LIMIT, ge=1, le=8)


class ListingArgs(Args):
    listing_id: str = Field(max_length=20)


class CompareDeliveryArgs(Args):
    listing_id: str = Field(max_length=20)
    dish: str | None = Field(default=None, max_length=120)


async def find_food(
    ctx: Ctx, *, near: str, max_price: int | None, place_type: str | None, open_now: bool
) -> tuple[list[FoodListingSummary], bool]:
    """Within walking distance first; widen only when nothing nearby fits. Shared with rules."""
    veg_only = ctx.prefs.food_preference in {"veg", "vegan"}
    items = await food_service.search(
        ctx, place_type=place_type, veg_only=veg_only, max_price=max_price, sort="price", near=near
    )
    if open_now:
        items = [i for i in items if i.open_now]

    def distance(i: FoodListingSummary) -> float:
        return i.distance_from_office_km if near == "office" else i.distance_from_home_km

    nearby = [i for i in items if distance(i) <= WALKABLE_KM]
    pool = nearby or items
    sort_food(pool, "price", near)
    return pool, not nearby and bool(items)


def sort_food(items: list[FoodListingSummary], order: str, near: str) -> None:
    """Sorts in place in the order the user asked for; ties go to the cheaper, closer place."""

    def distance(i: FoodListingSummary) -> float:
        return i.distance_from_office_km if near == "office" else i.distance_from_home_km

    if order == "priceDesc":
        items.sort(key=lambda i: (-i.avg_meal_price, distance(i), i.id))
    elif order == "distance":
        items.sort(key=lambda i: (distance(i), i.avg_meal_price, i.id))
    elif order == "rating":
        items.sort(key=lambda i: (-i.rating, i.avg_meal_price, i.id))
    else:
        items.sort(key=lambda i: (i.avg_meal_price, distance(i), i.id))


async def search_nearby_food(ctx: Ctx, ev: Evidence, args: FoodSearchArgs) -> dict[str, Any]:
    pool, widened = await find_food(
        ctx,
        near=args.near,
        max_price=args.max_price,
        place_type=args.place_type,
        open_now=args.open_now,
    )
    sort_food(pool, args.sort, args.near)
    top = pool[: args.limit]
    ev.food.update({i.id: i for i in top})
    anchor = ctx.prefs.office_area if args.near == "office" else ctx.prefs.home_area
    return {
        "anchor": anchor.name if anchor else "",
        "widenedBeyondWalkingDistance": widened,
        "matches": len(pool),
        "listings": [food_brief(i, args.near) for i in top],
    }


async def get_listing(ctx: Ctx, ev: Evidence, args: ListingArgs) -> dict[str, Any]:
    detail = await food_service.detail(ctx, args.listing_id)
    ev.food[detail.id] = FoodListingSummary.model_validate(detail.model_dump())
    return {
        **food_brief(detail, "office"),
        "timings": detail.timings,
        "deliveryAvailable": detail.delivery_available,
        "menu": [m.model_dump(by_alias=True) for m in detail.menu[:10]],
    }


async def compare_delivery_vs_dine_in(
    ctx: Ctx, ev: Evidence, args: CompareDeliveryArgs
) -> dict[str, Any]:
    comparison = await food_service.delivery_comparison(ctx, args.listing_id, args.dish)
    return comparison.model_dump(by_alias=True)


# ------------------------------------------------------------------ groceries


async def get_grocery_list(ctx: Ctx, ev: Evidence, _: NoArgs) -> dict[str, Any]:
    current = await grocery_service.current_list(ctx)
    return {
        "month": current.month,
        "itemCount": current.item_count,
        "estimatedTotal": current.estimated_total,
        "lines": [
            {
                "name": i.name,
                "quantity": i.quantity,
                "cheapestStore": i.cheapest_store_label,
                "lineTotal": i.line_total,
            }
            for i in current.items[:12]
        ],
    }


async def compare_grocery_stores(ctx: Ctx, ev: Evidence, _: NoArgs) -> dict[str, Any]:
    comparison = await grocery_service.comparison(ctx)
    ev.grocery_plan = to_plan_summary(comparison)
    return {
        "itemCount": comparison.item_count,
        "storeTotals": [t.model_dump(by_alias=True) for t in comparison.store_totals],
        "cheapestStoreLabel": comparison.cheapest_store_label,
        "mixedBasketTotal": comparison.mixed_basket_total,
        "bulkSaving": comparison.bulk_saving,
        "quickCommerceExtra": comparison.quick_commerce_extra,
        "splitSaving": comparison.split_saving,
    }


# ------------------------------------------------------------------ shopping


class ProductSearchArgs(Args):
    query: str | None = Field(default=None, max_length=80)
    category: (
        Literal[
            "shirts",
            "jeans",
            "formalShoes",
            "backpacks",
            "earphones",
            "watches",
            "raincoats",
            "helmets",
        ]
        | None
    ) = None
    max_price: int | None = Field(default=None, gt=0)
    max_delivery_days: int | None = Field(default=None, ge=1, le=14)
    sort: Literal["price", "rating", "discount"] = "price"


class ProductArgs(Args):
    product_id: str = Field(max_length=20)


class HistoryArgs(Args):
    product_id: str = Field(max_length=20)
    days: int = Field(default=90, ge=7, le=90)


async def search_products(ctx: Ctx, ev: Evidence, args: ProductSearchArgs) -> dict[str, Any]:
    items, _total = await product_service.search(
        ctx.session, q=args.query, category=args.category, max_price=args.max_price, sort=args.sort
    )
    if args.max_delivery_days is not None:
        items = [i for i in items if i.fastest_delivery_days <= args.max_delivery_days]
    top = items[:LIST_LIMIT]
    ev.products.update({i.id: i for i in top})
    return {"matches": len(items), "products": [product_brief(i) for i in top]}


async def get_price_history(ctx: Ctx, ev: Evidence, args: HistoryArgs) -> dict[str, Any]:
    history = await product_service.price_history(ctx, args.product_id, args.days)
    return history.model_dump(by_alias=True, exclude={"points"})


async def get_buy_or_wait_verdict(ctx: Ctx, ev: Evidence, args: ProductArgs) -> dict[str, Any]:
    detail = await product_service.detail(ctx, args.product_id)
    ev.products[detail.id] = ProductSummary.model_validate(detail.model_dump())
    if detail.best_offer:
        ev.offers[detail.best_offer.id] = detail.best_offer
    return {
        **product_brief(detail),
        "verdict": detail.verdict,
        "verdictReason": detail.verdict_reason,
        "lowest90Day": detail.lowest_90_day,
        "average90Day": detail.average_90_day,
        "platforms": [
            {
                "platform": p.platform,
                "price": p.price,
                "inStock": p.in_stock,
                "deliveryDays": p.delivery_days,
                "deliveryBy": p.delivery_by.date().isoformat(),
            }
            for p in detail.platforms
        ],
        "bestOffer": offer_brief(detail.best_offer) if detail.best_offer else None,
        "bestDealPlatform": detail.best_deal_platform,
        "bestDealBasePrice": detail.best_deal_base_price,
        "finalPrice": detail.final_price,
        "offerSaving": detail.offer_saving,
    }


# ------------------------------------------------------------------ deals


class OffersArgs(Args):
    platform: str | None = Field(default=None, max_length=40)
    expiring_within_days: int | None = Field(default=None, ge=0, le=60)


class FinalPriceArgs(Args):
    price: int = Field(gt=0, le=10_000_000)
    platform: str = Field(max_length=40)


async def find_offers(ctx: Ctx, ev: Evidence, args: OffersArgs) -> dict[str, Any]:
    offers = await offer_service.usable_offers(ctx)
    if args.platform:
        offers = [o for o in offers if o.platform.lower() == args.platform.lower()]
    if args.expiring_within_days is not None:
        offers = [o for o in offers if o.days_left <= args.expiring_within_days]
    top = offers[:LIST_LIMIT]
    ev.offers.update({o.id: o for o in top})
    return {
        "usableCount": len(offers),
        "savedCards": len(ctx.user.cards),
        "expiringSoon": sum(1 for o in offers if o.expiring_soon),
        "offers": [offer_brief(o) for o in top],
    }


async def calculate_final_price(ctx: Ctx, ev: Evidence, args: FinalPriceArgs) -> dict[str, Any]:
    pairs = [(row, out) for row, out in await offer_service.live_offer_pairs(ctx) if out.eligible]
    application = best_offer_for(
        args.price, args.platform, [offer_service.terms_of(row) for row, _ in pairs]
    )
    if application is None:
        return {
            "price": args.price,
            "platform": args.platform,
            "offer": None,
            "discount": 0,
            "finalPrice": args.price,
        }
    offer = next(out for _, out in pairs if out.id == application.offer_id)
    ev.offers[offer.id] = offer
    return {
        "price": args.price,
        "platform": args.platform,
        "offer": offer_brief(offer),
        "discount": application.discount,
        "finalPrice": application.final_price,
    }


# ------------------------------------------------------------------ homes


class HomeSearchArgs(Args):
    area: str | None = Field(default=None, max_length=60, description="Area name or id")
    max_rent: int | None = Field(default=None, gt=0)
    home_type: Literal["pg", "coliving", "sharedFlat"] | None = None
    food_included: bool | None = None


class HomeArgs(Args):
    home_id: str = Field(max_length=20)


async def resolve_area(ctx: Ctx, text: str | None) -> Area | None:
    if not text:
        return None
    needle = text.strip().lower()
    for area in await ctx.session.scalars(select(Area)):
        if needle in {area.id.lower(), area.name.lower()}:
            return area
    return None


async def search_homes(ctx: Ctx, ev: Evidence, args: HomeSearchArgs) -> dict[str, Any]:
    area = await resolve_area(ctx, args.area)
    if args.area and area is None:
        return {
            "error": f'No area called "{args.area}". Use a Bangalore area name like Marathahalli.'
        }
    matches = await home_service.search(
        ctx,
        area=area.id if area else None,
        home_type=args.home_type,
        max_rent=args.max_rent,
        food_included=args.food_included,
    )
    top = matches[:LIST_LIMIT]
    ev.homes.update({h.id: h for h in top})
    rent_budget = await home_service.rent_budget(ctx)
    return {
        "area": area.name if area else "Bangalore",
        "matches": len(matches),
        "rentBudget": rent_budget,
        "homes": [home_brief(h) for h in top],
    }


async def compare_rent_to_area_average(ctx: Ctx, ev: Evidence, args: HomeArgs) -> dict[str, Any]:
    detail = await home_service.detail(ctx, args.home_id)
    ev.homes[detail.id] = HomeSummary.model_validate(detail.model_dump())
    return {
        **home_brief(detail),
        "yearlyDifferenceFromAverage": detail.yearly_difference_from_average,
        "rentBudget": detail.rent_budget,
        "differenceFromRentBudget": detail.difference_from_rent_budget,
        "moveInCost": detail.move_in_cost,
    }


# ------------------------------------------------------------------ savings


class MonthArgs(Args):
    month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class HistoryMonthsArgs(Args):
    months: int = Field(default=6, ge=1, le=24)


async def get_monthly_savings(ctx: Ctx, ev: Evidence, args: MonthArgs) -> dict[str, Any]:
    savings = await savings_service.monthly(ctx, args.month or ctx.clock.month_key())
    return savings.model_dump(by_alias=True, mode="json")


async def get_savings_history(ctx: Ctx, ev: Evidence, args: HistoryMonthsArgs) -> dict[str, Any]:
    history = await savings_service.history(ctx, args.months)
    return history.model_dump(by_alias=True)


# ------------------------------------------------------------------ the user's own records


ExpensePeriod = Literal["today", "yesterday", "week", "month", "lastMonth"]
PERIOD_LABELS = {
    "today": "today",
    "yesterday": "yesterday",
    "week": "in the last 7 days",
    "month": "this month",
    "lastMonth": "last month",
}


def expense_window(ctx: Ctx, period: str) -> tuple[datetime, datetime]:
    """[start, end) of a period in the business time zone, ending now for open periods."""
    now = ctx.clock.now()
    local = now.astimezone(ctx.clock.zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    later = now + timedelta(seconds=1)
    if period == "yesterday":
        return midnight - timedelta(days=1), midnight
    if period == "today":
        return midnight, later
    if period == "week":
        return midnight - timedelta(days=6), later
    month = ctx.clock.month_key()
    if period == "lastMonth":
        return month_bounds(shift_month(month, -1), ctx.clock.zone)
    return month_bounds(month, ctx.clock.zone)[0], later


class ExpensesArgs(Args):
    category: Literal["rent", "food", "groceries", "shopping", "travel", "bills", "misc"] | None = (
        None
    )
    period: ExpensePeriod = "month"
    order: Literal["latest", "biggest"] = "latest"
    limit: int = Field(default=6, ge=1, le=10)


async def get_recent_expenses(ctx: Ctx, ev: Evidence, args: ExpensesArgs) -> dict[str, Any]:
    start, end = expense_window(ctx, args.period)
    conditions = [Expense.user_id == ctx.user.id, Expense.spent_at >= start, Expense.spent_at < end]
    if args.category:
        conditions.append(Expense.category == args.category)
    count, total = (
        await ctx.session.execute(
            select(func.count(), func.coalesce(func.sum(Expense.amount), 0)).where(*conditions)
        )
    ).one()
    order = (
        (Expense.amount.desc(), Expense.spent_at.desc())
        if args.order == "biggest"
        else (Expense.spent_at.desc(), Expense.id.desc())
    )
    rows = await ctx.session.scalars(
        select(Expense).where(*conditions).order_by(*order).limit(args.limit)
    )
    return {
        "period": PERIOD_LABELS[args.period],
        "count": int(count),
        "total": int(total),
        "expenses": [
            {
                "title": e.title,
                "amount": e.amount,
                "category": e.category,
                "merchant": e.merchant,
                "date": e.spent_at.astimezone(ctx.clock.zone).date().isoformat(),
            }
            for e in rows
        ],
    }


async def get_notifications(ctx: Ctx, ev: Evidence, _: NoArgs) -> dict[str, Any]:
    payload = await notification_service.payload(ctx)
    return {
        "unreadCount": payload.unread_count,
        "latest": [
            {"title": n.title, "body": n.body, "read": n.read, "agent": n.agent}
            for n in payload.items[:5]
        ],
    }


async def get_price_alerts(ctx: Ctx, ev: Evidence, _: NoArgs) -> dict[str, Any]:
    rows = await product_service.alerts(ctx)
    return {
        "alerts": [
            {
                "product": a.product_name,
                "currentPrice": a.current_price,
                "targetPrice": a.target_price,
                "gapToTarget": a.gap_to_target,
                "reached": a.triggered,
            }
            for a in rows[:8]
        ]
    }


# ------------------------------------------------------------------ registry

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool("get_budget_status", "budget", "This month's budget: every category's limit, spent, remaining and status, days left and a safe daily spend.", NoArgs, "Checking your budget…", get_budget_status),
        Tool("get_category_spending", "budget", "One category this month: limit, spent, remaining, number of expenses, and (for food) delivery orders.", CategoryArgs, "Adding up this month's spending…", get_category_spending),
        Tool("log_expense", "budget", "Log an expense the user explicitly asked you to record. Never call this on your own.", LogExpenseArgs, "Logging the expense…", log_expense),
        Tool("search_nearby_food", "food", "Places to eat (restaurants, darshinis, messes, tiffin; \"hotels\" in Bangalore English) near the user's home or office, within walking distance (widens only if nothing nearby fits). Sorted cheapest first unless sort says otherwise; set open_now false for a full list. Prices are typical meal prices.", FoodSearchArgs, "Finding meals nearby…", search_nearby_food),
        Tool("get_listing", "food", "One eatery's menu, timings and whether it delivers.", ListingArgs, "Reading the menu…", get_listing),
        Tool("compare_delivery_vs_dine_in", "food", "The same dish eaten at the place versus delivered to the office, with every fee.", CompareDeliveryArgs, "Comparing delivery fees with eating there…", compare_delivery_vs_dine_in),
        Tool("get_grocery_list", "grocery", "The user's monthly grocery list with each line at its cheapest store.", NoArgs, "Reading your monthly grocery list…", get_grocery_list),
        Tool("compare_grocery_stores", "grocery", "The list priced at four store types: totals, cheapest store, bulk saving and the quick-commerce premium.", NoArgs, "Comparing prices across four store types…", compare_grocery_stores),
        Tool("search_products", "shopping", "Products across ShopNest, TrendKart and StyleBay, cheapest first. Filter by category, price and delivery days.", ProductSearchArgs, "Comparing prices across platforms…", search_products),
        Tool("get_price_history", "shopping", "A product's price over the last N days: low, high, average and today.", HistoryArgs, "Checking the price history…", get_price_history),
        Tool("get_buy_or_wait_verdict", "shopping", "Buy now or wait, with the reason, every platform's price and delivery date, and the best offer on the user's cards.", ProductArgs, "Deciding whether to buy now or wait…", get_buy_or_wait_verdict),
        Tool("find_offers", "deals", "Live offers the user's saved cards can unlock, soonest-ending first, each with a worked example.", OffersArgs, "Finding offers you qualify for…", find_offers),
        Tool("calculate_final_price", "deals", "The true final price of an order on a platform after the best offer the user can use.", FinalPriceArgs, "Applying the best offer on your cards…", calculate_final_price),
        Tool("search_homes", "home", "PGs, co-living and shared flats, cheapest first, each compared with the area's average rent.", HomeSearchArgs, "Searching for homes…", search_homes),
        Tool("compare_rent_to_area_average", "home", "One home against its area's average rent and the user's rent budget.", HomeArgs, "Comparing the rent with the area average…", compare_rent_to_area_average),
        Tool("get_monthly_savings", "savings", "A month's savings against the goal, the projection, and where the savings came from.", MonthArgs, "Adding up what you kept back…", get_monthly_savings),
        Tool("get_savings_history", "savings", "Savings over the last N finished months.", HistoryMonthsArgs, "Looking at your savings history…", get_savings_history),
        Tool("get_recent_expenses", "budget", "The user's own expenses: latest or biggest, for today, yesterday, the last 7 days, this month or last month, optionally one category, with the count and total.", ExpensesArgs, "Reading your expenses…", get_recent_expenses),
        Tool("get_notifications", "budget", "The user's alerts: unread count and the latest few (budget warnings, lunch ideas, price drops, savings reports).", NoArgs, "Reading your alerts…", get_notifications),
        Tool("get_price_alerts", "shopping", "The user's price alerts: each product's current price, target, gap and whether it is reached.", NoArgs, "Checking your price alerts…", get_price_alerts),
    )
}  # fmt: skip


async def run_tool(tool: Tool, ctx: Ctx, ev: Evidence, raw_arguments: str) -> dict[str, Any]:
    """Validate, run, record. Bad arguments come back as an error the model can fix."""
    started = time.perf_counter()
    entry: dict[str, Any] = {"tool": tool.name, "agent": tool.agent}
    try:
        parsed = json.loads(raw_arguments or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("arguments must be a JSON object")
        args = tool.args.model_validate(parsed)
    except (ValueError, ValidationError) as exc:
        message = (
            "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            if isinstance(exc, ValidationError)
            else f"arguments are not valid JSON ({exc})"
        )
        entry.update(ok=False, error=f"invalid arguments: {message}")
        ev.tool_log.append(entry)
        return {"error": f"Invalid arguments: {message}. Fix them and call the tool again."}

    entry["args"] = args.model_dump(mode="json")
    ev.add_agent(tool.agent)
    ev.add_step(tool.step)
    try:
        payload = await tool.handler(ctx, ev, args)
    except AppError as exc:  # e.g. an unknown id: tell the model, let it recover
        payload = {"error": exc.message}
    entry.update(ok="error" not in payload, ms=round((time.perf_counter() - started) * 1000))
    ev.tool_log.append(entry)
    ev.record_numbers(payload)
    return payload
