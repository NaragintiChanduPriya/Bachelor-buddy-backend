"""Rules mode: keyword intents with the same response shape as llm mode (port of the frontend's
src/mocks/chat/intents.ts and handlers/chat.ts). Needs no API key, and is the fallback when the
LLM fails. It calls the same services as the endpoints, so its numbers match the pages."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select

from app.agents import personal
from app.agents.concierge import AgentResult
from app.agents.evidence import CardRef, Evidence
from app.agents.reply import build_result as _result
from app.agents.reply import join_words as _join
from app.agents.tools import find_food, sort_food
from app.calc.grocery import to_plan_summary
from app.core.clock import month_bounds
from app.core.constants import PRODUCT_CATEGORY_LABELS
from app.core.errors import BadRequestError
from app.core.money import format_inr
from app.db.models import Area, Expense, FoodListing
from app.schemas.budget import BudgetCategoryOut, BudgetOut
from app.schemas.food import FoodListingSummary
from app.schemas.home import HomeSummary
from app.schemas.product import ProductSummary
from app.services import budget as budget_service
from app.services import food as food_service
from app.services import groceries as grocery_service
from app.services import homes as home_service
from app.services import offers as offer_service
from app.services import products as product_service
from app.services import savings as savings_service
from app.services.context import Ctx


@dataclass(frozen=True)
class Intent:
    id: str
    #: Every group needs at least one keyword hit for the intent to match.
    all_of: tuple[tuple[str, ...], ...]
    #: Extra weight when these appear, to break ties.
    boost: tuple[str, ...] = ()
    #: Optional supporting words: each hit adds a little weight but none is required.
    also: tuple[str, ...] = ()


#: Places to eat. In Bangalore English a "hotel" is usually a restaurant, darshini or mess.
FOOD_PLACES = (
    "hotel",
    "restaurant",
    "mess",
    "darshini",
    "tiffin",
    "cafe",
    "canteen",
    "eatery",
    "eateries",
    "dhaba",
)
FOOD_WORDS = (
    "hungry",
    "eat",
    "eating",
    "food",
    "lunch",
    "dinner",
    "breakfast",
    "meal",
    "snack",
    "biryani",
    "dosa",
    "idli",
    "thali",
    *FOOD_PLACES,
)

#: Budget categories other than food, by the words people use (see personal.CATEGORY_PATTERNS).
CATEGORY_WORDS = (
    "rent",
    "grocery",
    "groceries",
    "ration",
    "shopping",
    "clothes",
    "travel",
    "transport",
    "commute",
    "cab",
    "taxi",
    "auto",
    "metro",
    "bus",
    "fuel",
    "petrol",
    "bill",
    "electricity",
    "wifi",
    "wi-fi",
    "internet",
    "recharge",
    "mobile",
    "misc",
    "entertainment",
    "movie",
    "gym",
)
#: Facts about the user that the profile answers.
PROFILE_WORDS = (
    "location",
    "address",
    "area",
    "live",
    "living",
    "based",
    "office",
    "workplace",
    "tech park",
    "salary",
    "income",
    "earn",
    "goal",
    "preference",
    "diet",
    "card",
    "name",
    "email",
    "mail",
    "age",
    "old",
    "occupation",
    "job",
    "profession",
    "profile",
    "details",
    "account",
    "myself",
    "who am i",
    "about me",
    "joined",
    "member since",
)

#: Ordered by specificity; the highest score wins and the first wins a tie.
INTENTS = (
    Intent(
        "productDeadline",
        (
            ("shoes", "shirt", "jeans", "backpack", "earphones", "watch", "raincoat", "helmet", "buy"),
            ("under", "below", "budget", "cheap", "cheapest", "₹", "rs", "interview", "friday", "need"),
        ),
        ("interview", "friday", "formal"),
    ),
    Intent(
        "deliveryCompare",
        (
            ("delivery", "deliver", "delivered", "order in", "feastdrop", "quickbite", "dabbarun"),
            ("cheaper", "cheap", "cheapest", "worth", "compare", "vs", "versus", "than", "instead", "save", "fee", "cost"),
        ),
        ("delivery",),
    ),
    Intent(
        "foodNearby",
        (FOOD_WORDS,),
        ("hungry", "lunch", "hotel", "restaurant", "mess", "darshini", "tiffin"),
        ("near", "nearby", "around", "office", "home", "cheap", "cheapest", "list", "show", "under", "₹", "rs", "have"),
    ),
    Intent("spendOnFood", (("spend", "spent", "spending"), ("food", "eating", "meal", "lunch", "dinner", "breakfast", "snack", "delivery")), ("how much",)),
    Intent(
        "groceryPlan",
        (
            ("grocery", "groceries", "ration", "rice", "dal", "stock"),
            ("cheap", "cheapest", "buy", "month", "monthly", "where", "order", "way", "list", "items", "what", "whats", "show", "my"),
        ),
    ),
    Intent(
        "homeSearch",
        (
            ("pg", "flat", "room", "house", "home", "rent", "coliving", "co-living", "stay", "hostel", "lodge", "accommodation"),
            ("under", "near", "below", "find", "cheap", "cheapest", "cheaper", "₹", "rs", "looking", "show", "list", "nearby", "lowest", "highest", "best", "need", "want", "any", "options"),
        ),
        ("pg", "rent"),
    ),
    Intent("budgetStatus", (("budget", "left", "remaining", "afford", "money"), ("how", "much", "what", "this", "month", "i", "where", "my", "going"))),
    Intent("savingsStatus", (("save", "saved", "saving", "savings"), ("how", "much", "month", "goal", "this", "am", "last", "previous", "history", "trend", "past", "my", "report"))),
    Intent("spendOnCategory", (("spend", "spent", "spending", "paid", "pay", "cost"), CATEGORY_WORDS), ("how much",)),
    Intent("spendTotal", (("spend", "spent", "spending", "expenditure"),), (), ("total", "month", "overall", "altogether", "so far", "this")),
    Intent("expenses", (("expense", "transaction", "purchase", "bought", "payment"),), ("recent", "latest", "biggest", "largest"), ("show", "list", "my", "last", "today", "yesterday", "week", "month", "all")),
    Intent("alerts", (("alert", "notification", "reminder", "unread", "inbox"),), ("alert", "notification"), ("my", "show", "any", "new", "price", "what")),
    Intent(
        "deals",
        (
            ("offer", "deal", "coupon", "cashback", "discount"),
            ("any", "card", "have", "show", "what", "available", "my"),
        ),
    ),
    # Last, so a tie goes to the more specific intents above.
    Intent(
        "profile",
        (PROFILE_WORDS, ("my", "me", "i", "am", "what", "whats", "where", "which", "who", "how", "tell", "show", "do")),
        ("location", "profile", "salary", "email", "myself", "who am i", "about me", "selected", "occupation", "preference"),
    ),
)  # fmt: skip


def has_word(text: str, keyword: str) -> bool:
    """A whole-word match (a plural "s" or "es" counts), so "rice" no longer matches "prices"
    and "cheap" no longer matches "cheapest"."""
    if not keyword[0].isalnum():
        return keyword in text
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?:e?s)?(?![a-z0-9])"
    return re.search(pattern, text) is not None


#: "Hotel" means somewhere to stay only when the message is about staying.
#: ("hotels near my room" is still food: bachelors call where they live "my room".)
STAY_CONTEXT = re.compile(
    r"\b(stay|staying|lodge|lodging|accommodation|hostel|overnight|nights|check.?in|"
    r"hotel rooms?|rooms? for|book(?:ing)? (?:a )?(?:hotel|room))\b"
)


def normalise(message: str) -> str:
    text = message.lower().replace("’", "'")  # noqa: RUF001 (a typographic apostrophe)
    if STAY_CONTEXT.search(text):
        text = re.sub(r"\bhotels?\b", "stay", text)
    return text


def match_intent(message: str) -> str | None:
    text = normalise(message)
    best: tuple[str, int] | None = None
    for intent in INTENTS:
        hits = [sum(1 for k in group if has_word(text, k)) for group in intent.all_of]
        if any(h == 0 for h in hits):
            continue
        score = (
            sum(hits)
            + sum(1 for k in intent.also if has_word(text, k))
            + 2 * sum(1 for k in intent.boost if has_word(text, k))
        )
        if best is None or score > best[1]:
            best = (intent.id, score)
    return best[0] if best else None


# ---------------------------------------------------------------- what the user asked for

#: Explicit orderings. "Cheapest" alone asks for one best pick, not an ordering.
SORT_PATTERNS = (
    ("priceDesc", r"highest to lowest|high to low|most expensive|costliest|expensive first|descending|decreasing"),
    ("price", r"lowest to highest|low to high|cheapest first|ascending|increasing|by price|price order|order of price"),
    ("rating", r"best rated|top rated|highest rated|best reviewed|by rating|\bratings?\b"),
    ("distance", r"\bnearest\b|\bclosest\b|by distance"),
)  # fmt: skip
ORDER_LABELS = {
    "price": "cheapest first",
    "priceDesc": "most expensive first",
    "rating": "best rated first",
    "distance": "nearest first",
}
LIST_WORDS = re.compile(
    r"\b(list|all|options|places|show me|which|top \d+|hotels|restaurants|messes|darshinis|"
    r"cafes|canteens|eateries|dhabas|plans|pgs|flats|homes)\b"
)


def extract_sort(message: str) -> str | None:
    text = message.lower()
    return next((order for order, pattern in SORT_PATTERNS if re.search(pattern, text)), None)


def wants_list(message: str) -> bool:
    """A list or an ordering, rather than "what should I eat"."""
    return extract_sort(message) is not None or LIST_WORDS.search(message.lower()) is not None


def extract_count(message: str, default: int = 6) -> int:
    match = re.search(
        r"\btop (\d{1,2})\b|\b(\d{1,2}) (?:places|options|hotels|restaurants|messes|results|pgs)\b",
        message.lower(),
    )
    count = int(match.group(1) or match.group(2)) if match else default
    return max(1, min(count, 10))


def extract_price_cap(message: str) -> int | None:
    """A spending limit ("under ₹200", "I have 150", "below 10k"), never a count like "top 10"."""
    text = message.lower().replace(",", "")
    match = re.search(
        r"(?:under|below|within|less than|up ?to|max(?:imum)?|budget(?: of)?|have|only)\s*"
        r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(k\b)?"
        r"|(?:₹|\brs\.?\s*|\binr\s*)(\d+(?:\.\d+)?)\s*(k\b)?",
        text,
    )
    if match is None:
        return None
    number = float(match.group(1) or match.group(3))
    value = round(number * 1000) if (match.group(2) or match.group(4)) else round(number)
    return value if value >= 10 else None


def extract_amount(message: str) -> int | None:
    """The first rupee amount, e.g. "under ₹1,500" or "I have 150"."""
    match = re.search(r"(?:₹|rs\.?\s*)?(\d{2,6})", message.replace(",", ""), re.IGNORECASE)
    return int(match.group(1)) if match else None


CATEGORY_PATTERNS = (
    ("formalShoes", r"\b(formal )?shoes?\b|\boxfords?\b|\bderby\b"),
    ("shirts", r"\bshirts?\b"),
    ("jeans", r"\bjeans\b|\bdenims?\b"),
    ("backpacks", r"\bbackpacks?\b|\blaptop bag\b|\bbags?\b"),
    ("earphones", r"\bearphones?\b|\bearbuds?\b|\bheadphones?\b"),
    ("watches", r"\bwatch(es)?\b"),
    ("raincoats", r"\braincoats?\b|\brain jacket\b"),
    ("helmets", r"\bhelmets?\b"),
)


def extract_category(message: str) -> str | None:
    text = message.lower()
    return next((c for c, pattern in CATEGORY_PATTERNS if re.search(pattern, text)), None)


def extract_area(message: str, areas: Sequence[Area]) -> Area | None:
    """By full name or the short name people use ("HSR" for HSR Layout)."""
    text = message.lower()

    def names(area: Area) -> set[str]:
        full = area.name.lower()
        return {full, re.sub(r" (layout|nagar|stage|phase|city|road)$", "", full)}

    return next((a for a in areas if any(has_word(text, n) for n in names(a))), None)


def days_until_next_friday(ctx: Ctx) -> int:
    weekday = ctx.clock.local_now().weekday()  # Monday 0 .. Friday 4
    delta = (4 - weekday) % 7
    return delta or 7


TYPE_LABELS = {
    "darshini": "darshini",
    "mess": "mess",
    "tiffin": "tiffin service",
    "restaurant": "restaurant",
}
TYPE_PLURALS = {
    "darshini": "darshinis",
    "mess": "messes",
    "tiffin": "tiffin services",
    "restaurant": "restaurants",
}


def extract_place_type(message: str) -> str | None:
    """Only the specific kinds; "hotel" and "restaurant" mean any place to eat."""
    text = message.lower()
    for place_type, pattern in (
        ("mess", r"\bmess(es)?\b"),
        ("darshini", r"\bdarshinis?\b"),
        ("tiffin", r"\btiffins?\b"),
    ):
        if re.search(pattern, text):
            return place_type
    return None  # fmt: skip


def food_anchor(ctx: Ctx, message: str) -> tuple[str, str]:
    """Where "near me" is: what the user said, else the office in working hours, else home.
    Returns the anchor and, when it was inferred from the time, why."""
    text = message.lower()
    if re.search(r"\b(office|work|workplace|tech park)\b", text):
        return "office", ""
    if re.search(r"\b(home|my place|my room|my pg|my flat|house)\b", text):
        return "home", ""
    now = ctx.clock.local_now()
    if ctx.prefs.office_area is not None and now.weekday() < 5 and 9 <= now.hour < 19:
        return "office", ", since you are usually at work at this hour"
    return "home", ""


def _km(item: FoodListingSummary, near: str) -> float:
    return item.distance_from_office_km if near == "office" else item.distance_from_home_km


async def _food_nearby(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: foodNearby. A list in the order asked for, or one best pick within a budget."""
    if wants_list(message):
        return await _food_list(ctx, ev, message, budget)
    lower = message.lower()
    prefs = ctx.prefs
    by_id = {c.id: c for c in budget.categories}
    anchor, why = food_anchor(ctx, message)
    near_office = anchor == "office"
    anchor_area = prefs.office_area if near_office else prefs.home_area
    area_name = anchor_area.name if anchor_area else ""
    cap = extract_price_cap(message) or 200
    place_type = extract_place_type(lower)
    pool, widened = await find_food(
        ctx, near=anchor, max_price=cap, place_type=place_type, open_now=True
    )
    top = pool[:3]
    ev.food.update({i.id: i for i in top})
    food = by_id["food"]
    if top:
        best = top[0]
        text = (
            f"With {format_inr(cap)} near your {anchor} in {area_name}{why}, {best.name} is your "
            f"best option — a typical meal there is {format_inr(best.avg_meal_price)}, about "
            f"{_km(best, anchor)} km away{', which is a short ride rather than a walk' if widened else ''}. "
            f"You have {format_inr(food.remaining)} left in your food budget this month, so this "
            "keeps you comfortably inside it."
        )
    else:
        text = (
            f"I could not find anything open under {format_inr(cap)} near your {anchor} right "
            f"now. Raising it to about {format_inr(150)} opens up several messes and darshinis."
        )
    other = "home" if near_office else "office"
    return _result(
        ev, text, [CardRef(type="food", id=i.id) for i in top], ("food", "budget"),
        ("Checking your budget…", f"Finding meals near {area_name}…", "Keeping only places open now and within walking distance…", "Ranking by price, then distance…"),
        ("Is delivery cheaper than going there?", f"Show places to eat near my {other}, cheapest first", "Show me monthly tiffin plans"),
    )  # fmt: skip


async def _food_list(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Places to eat near the user, in the order they asked for (cheapest first by default)."""
    lower = message.lower()
    anchor, why = food_anchor(ctx, message)
    area = ctx.prefs.office_area if anchor == "office" else ctx.prefs.home_area
    area_name = area.name if area else ""
    order = extract_sort(message) or "price"
    count = extract_count(message)
    cap = extract_price_cap(message)
    place_type = extract_place_type(lower)
    open_now = bool(re.search(r"\bopen now\b|\bright now\b|\bopen\b", lower))
    pool, widened = await find_food(
        ctx, near=anchor, max_price=cap, place_type=place_type, open_now=open_now
    )
    sort_food(pool, order, anchor)
    top = pool[:count]
    ev.food.update({i.id: i for i in top})
    food = next(c for c in budget.categories if c.id == "food")
    kind = TYPE_PLURALS[place_type] if place_type else "places to eat"
    limit = f" under {format_inr(cap)}" if cap else ""
    show_plans = place_type == "tiffin" or "plan" in lower

    if not top:
        text = (
            f"I couldn't find any {kind}{limit} near your {anchor} in {area_name}"
            f"{' that are open now' if open_now else ''}. Raising the limit, or looking near "
            f"your {'home' if anchor == 'office' else 'office'} instead, usually turns some up."
        )
    else:
        where = "closest to" if widened else "within walking distance of"
        lines = []
        for n, item in enumerate(top, 1):
            extras = [f"{_km(item, anchor)} km", f"rated {item.rating}"]
            if show_plans and item.monthly_plan_price:
                extras.append(f"monthly plan {format_inr(item.monthly_plan_price)}")
            if not item.open_now:
                extras.append("closed now")
            lines.append(
                f"{n}. {item.name} ({TYPE_LABELS[item.type]}) — "
                f"{format_inr(item.avg_meal_price)} a meal, {', '.join(extras)}"
            )
        notes = []
        if widened:
            notes.append("Nothing fits within walking distance, so these are a short ride away.")
        if len(pool) > len(top):
            notes.append(f"{len(pool) - len(top)} more are on the Food page.")
        if ctx.prefs.food_preference in {"veg", "vegan"}:
            notes.append("I kept to vegetarian places, as you prefer.")
        notes.append(f"You have {format_inr(food.remaining)} left in your food budget this month.")
        singular = TYPE_LABELS[place_type] if place_type else "place to eat"
        opening = f"Here are {len(top)} {kind}" if len(top) > 1 else f"There is one {singular}"
        ordered = f", {ORDER_LABELS[order]}" if len(top) > 1 else ""
        text = (
            f"{opening}{limit} {where} your {anchor} in {area_name}{why}{ordered}:\n"
            + "\n".join(lines)
            + "\n\n"
            + " ".join(notes)
        )
    other = "home" if anchor == "office" else "office"
    follow_ups = [
        f"Show places to eat near my {other}, cheapest first",
        "Is delivery cheaper than going there?",
    ]
    follow_ups.append(
        "Show me monthly tiffin plans"
        if place_type != "tiffin"
        else "How much did I spend on food this month?"
    )
    return _result(
        ev, text, [CardRef(type="food", id=i.id) for i in top], ("food", "budget"),
        ("Working out where you are…", f"Finding {kind} near {area_name}…", f"Sorting them {ORDER_LABELS[order]}…", "Checking your food budget…"),
        follow_ups,
    )  # fmt: skip


async def _named_listing(ctx: Ctx, message: str) -> str | None:
    text = message.lower()
    rows = (await ctx.session.execute(select(FoodListing.id, FoodListing.name))).all()
    named = [(listing_id, name) for listing_id, name in rows if name.lower() in text]
    return max(named, key=lambda row: len(row[1]))[0] if named else None


async def _delivery_compare(
    ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut, recent_food_ids: Sequence[str]
) -> AgentResult:
    """Intent: deliveryCompare. "There" is a place named in the message, else the places the
    previous reply showed (the first one that delivers), else the cheapest delivering place
    near the office."""
    named = await _named_listing(ctx, message)
    from_previous = named is None and bool(recent_food_ids)
    candidates = [named] if named else list(recent_food_ids)
    delivering = set(
        await ctx.session.scalars(
            select(FoodListing.id).where(FoodListing.delivery_available.is_(True))
        )
    )
    if not candidates:
        pool, _ = await find_food(
            ctx, near="office", max_price=None, place_type=None, open_now=False
        )
        candidates = [i.id for i in pool if i.id in delivering][:1]
    follow_ups = (
        "Find me a cheap lunch near office",
        "How much did I spend on food this month?",
        "Show places to eat near my home, cheapest first",
    )
    if not candidates:
        return _result(
            ev, "I couldn't find a place near your office that delivers, so going there is the way to eat.",
            [], ("food",), ("Checking which places deliver…",), follow_ups,
        )  # fmt: skip

    async def show(listing_id: str) -> FoodListingSummary:
        detail = await food_service.detail(ctx, listing_id)
        summary = FoodListingSummary.model_validate(detail.model_dump())
        ev.food[summary.id] = summary
        return summary

    asked = await show(candidates[0])
    refs = [CardRef(type="food", id=asked.id)]
    chosen_id = next((c for c in candidates if c in delivering), None)
    comparison = None
    if chosen_id is not None:
        try:
            comparison = await food_service.delivery_comparison(ctx, chosen_id, None)
        except BadRequestError:  # no delivery app lists a dish from it
            comparison = None
    if comparison is None:
        others = " None of the other places I listed deliver either." if len(candidates) > 1 else ""
        text = (
            f"{asked.name} doesn't deliver, so going there is the only option — and you skip "
            f"every app fee. A meal there is about {format_inr(asked.avg_meal_price)}.{others}"
        )
        return _result(ev, text, refs, ("food",), ("Checking delivery apps…",), follow_ups)

    prefix = ""
    if chosen_id != asked.id:
        chosen = await show(chosen_id)  # type: ignore[arg-type]
        refs.append(CardRef(type="food", id=chosen.id))
        where = "Of the places I listed, " if from_previous else ""
        prefix = f"{asked.name} doesn't deliver, so there is nothing to compare there. {where}"
        prefix += f"{chosen.name} does. "
    best = comparison.cheapest_delivery
    if comparison.amount_saved > 0:
        text = prefix + (
            f"Going there is cheaper: {comparison.dish} at {comparison.listing_name} is "
            f"{format_inr(comparison.dine_in_price)} there, while the cheapest delivery is "
            f"{best.platform} at {format_inr(best.total)} after a "
            f"{format_inr(best.delivery_fee)} delivery fee, {format_inr(best.platform_fee)} "
            f"platform fee, {format_inr(best.packaging_fee)} packaging and "
            f"{format_inr(best.taxes)} taxes. Eating there saves "
            f"{format_inr(comparison.amount_saved)} ({comparison.percent_saved}%) a meal — about "
            f"{format_inr(comparison.monthly_saving_if_switched)} a month if you eat there on "
            "weekdays instead."
        )
    else:
        text = prefix + (
            f"For {comparison.dish} at {comparison.listing_name}, {best.platform} delivers it for "
            f"{format_inr(best.total)} against {format_inr(comparison.dine_in_price)} there, so "
            "delivery costs you nothing extra this time."
        )
    return _result(
        ev, text, refs, ("food",),
        (f"Pricing {comparison.dish} at {comparison.listing_name}…", "Adding every delivery, platform and packaging fee…", "Comparing with eating there…"),
        follow_ups,
    )  # fmt: skip


async def _product_deadline(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: productDeadline."""
    amount = extract_amount(message)
    lower = message.lower()
    by_id = {c.id: c for c in budget.categories}
    shopping = by_id["shopping"]
    category = extract_category(message)
    label = PRODUCT_CATEGORY_LABELS[category].lower() if category else "options"
    cap = amount or max(shopping.remaining, 0)
    limit = min(cap, shopping.remaining) if shopping.remaining > 0 else cap
    deadline = bool(re.search(r"friday|interview|urgent|tomorrow|this week|before", lower))
    friday = days_until_next_friday(ctx)

    async def search(max_price: int) -> list[ProductSummary]:
        items, _ = await product_service.search(
            ctx.session, category=category, max_price=max_price, sort="price"
        )
        return [p for p in items if not deadline or p.fastest_delivery_days <= friday]

    matches = await search(limit) if limit > 0 else []
    widened = not matches and shopping.remaining > limit
    if widened:
        matches = await search(shopping.remaining)
    top = matches[:3]
    ev.products.update({p.id: p for p in top})
    best = await product_service.detail(ctx, top[0].id) if top else None
    refs = [CardRef(type="product", id=p.id) for p in top]
    if best is None:
        text = (
            f"I could not find {label} under {format_inr(limit)}"
            f"{' that arrive before Friday' if deadline else ''}. You have "
            f"{format_inr(shopping.remaining)} left in shopping this month — raising the limit a "
            "little, or dropping the delivery deadline, opens up more options."
        )
    else:
        row = next((p for p in best.platforms if p.platform == best.best_deal_platform), None)
        offer_part = (
            f" after the {best.best_offer.title.rstrip('.')} offer, down from "
            f"{format_inr(best.best_deal_base_price)}"
            if best.best_offer
            else ""
        )
        delivery_part = ""
        if row is not None:
            arrives = row.delivery_by.astimezone(ctx.clock.zone)
            in_time = ", in time for Friday" if deadline and row.delivery_days <= friday else ""
            delivery_part = f" It arrives by {arrives.day} {arrives:%b}{in_time}."
        verdict = (
            "The price is good right now."
            if best.verdict == "buyNow"
            else "The price usually dips in sales, but with your deadline it is worth buying now."
        )
        left = max(shopping.remaining - best.final_price, 0)
        text = (
            (f"Nothing fits under {format_inr(limit)}, so I looked up to your remaining {format_inr(shopping.remaining)}. " if widened else "")
            + f"Your best option is the {best.name} from {best.brand}: {format_inr(best.final_price)} on {best.best_deal_platform}{offer_part}.{delivery_part} {verdict} That leaves {format_inr(left)} in your shopping budget this month."
        )  # fmt: skip
        if best.best_offer:
            ev.offers[best.best_offer.id] = best.best_offer
            refs.append(CardRef(type="offer", id=best.best_offer.id))
    return _result(
        ev, text, refs, ("budget", "shopping", "deals"),
        ("Checking your shopping budget…", f"Comparing {label} under {format_inr(limit)} across platforms…", "Keeping only what arrives before Friday…" if deadline else "Checking delivery dates…", "Applying the best offer on your cards…"),
        ("What offers can I use on my cards?", "What is left in my budget?", "How much have I saved this month?"),
    )  # fmt: skip


async def _spend_on_food(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: spendOnFood."""
    extract_amount(message)
    message.lower()
    by_id = {c.id: c for c in budget.categories}
    food = by_id["food"]
    start, end = month_bounds(budget.month, ctx.clock.zone)
    count, total = (
        await ctx.session.execute(
            select(func.count(), func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.user_id == ctx.user.id,
                Expense.category == "food",
                Expense.source == "delivery",
                Expense.spent_at >= start,
                Expense.spent_at < end,
            )
        )
    ).one()
    if food.spent == 0:
        text = (
            f"You haven't spent anything on food this month yet. Your food budget is "
            f"{format_inr(food.limit)}."
        )
    elif count == 0:
        text = (
            f"You have spent {format_inr(food.spent)} on food this month, which is "
            f"{food.percent_used}% of your {format_inr(food.limit)} budget, leaving "
            f"{format_inr(food.remaining)}. None of it was delivery, so you are already skipping "
            "every app fee."
        )
    else:
        text = (
            f"You have spent {format_inr(food.spent)} on food this month, which is "
            f"{food.percent_used}% of your {format_inr(food.limit)} budget, leaving "
            f"{format_inr(food.remaining)}. {count} of those were delivery orders adding up to "
            f"{format_inr(int(total))} — switching a few of those to a mess nearby is the quickest "
            "saving available to you."
        )
    return _result(
        ev, text, [CardRef(type="budgetSummary", categories=["food", "groceries"])], ("budget", "food"),
        ("Adding up this month's food expenses…", "Comparing against your budget…"),
        ("Find me a cheap lunch near office", "Cheapest way to buy groceries this month"),
    )  # fmt: skip


async def _grocery_plan(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: groceryPlan. The list itself when asked what is on it, else the cheapest plan."""
    lower = message.lower()
    by_id = {c.id: c for c in budget.categories}
    groceries = by_id["groceries"]
    wants_items = re.search(r"\b(what('?s| is) on|items|show( me)? my|my grocery list)\b", lower)
    if wants_items and not re.search(r"\b(cheap|cheapest|store|compare|bulk|where)\b", lower):
        current = await grocery_service.current_list(ctx)
        if not current.items:
            text = (
                "Your monthly grocery list is empty. Add your staples on the Groceries page and I "
                "will find the cheapest store for each one."
            )
        else:
            lines = [
                f"{n}. {i.name} x {i.quantity} — {format_inr(i.line_total)} at {i.cheapest_store_label}"
                for n, i in enumerate(current.items[:10], 1)
            ]
            more = f"\n…and {current.item_count - 10} more." if current.item_count > 10 else ""
            text = (
                f"Your list has {current.item_count} items, {format_inr(current.estimated_total)} "
                "at each item's cheapest store:\n" + "\n".join(lines) + more
            )
        return _result(
            ev, text, [], ("grocery",), ("Reading your grocery list…",),
            ("Cheapest way to buy groceries this month", "How much did I spend on groceries?"),
        )  # fmt: skip
    comparison = await grocery_service.comparison(ctx)
    plan = to_plan_summary(comparison)
    ev.grocery_plan = plan
    if plan.item_count == 0:
        text = (
            "Your monthly grocery list is empty. Add your staples on the Groceries page and I "
            "will find the cheapest store for each one."
        )
    else:
        fits = (
            "fits comfortably"
            if plan.estimated_total <= groceries.remaining
            else "needs a little trimming"
        )
        text = (
            f"Your {plan.item_count}-item list costs {format_inr(plan.estimated_total)} if you "
            f"buy each item where it is cheapest — {plan.cheapest_store_label} is the best single "
            f"store. Doing it as one monthly bulk order saves {format_inr(plan.bulk_saving)}, and "
            f"the same list on quick commerce would cost "
            f"{format_inr(comparison.quick_commerce_extra)} more. You have "
            f"{format_inr(groceries.remaining)} left in groceries, so this {fits}."
        )
    return _result(
        ev, text, [] if plan.item_count == 0 else [CardRef(type="groceryPlan")], ("grocery", "budget"),
        ("Reading your monthly grocery list…", "Comparing prices across four store types…", "Checking bulk packs against small orders…", "Checking your groceries budget…"),
        ("How much did I spend on food this month?", "What offers can I use on my cards?", "How much have I saved this month?"),
    )  # fmt: skip


def sort_homes(homes: list[HomeSummary], order: str | None) -> None:
    """The search already returns cheapest first; reorder only when asked."""
    if order == "priceDesc":
        homes.sort(key=lambda h: (-h.rent, h.id))
    elif order == "rating":
        homes.sort(key=lambda h: (-h.rating, h.rent, h.id))
    elif order == "distance":
        homes.sort(key=lambda h: (h.tech_park_distance_km or h.nearest_tech_park_km, h.rent, h.id))


async def _home_search(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: homeSearch."""
    lower = message.lower()
    by_id = {c.id: c for c in budget.categories}
    cap = extract_price_cap(message) or 12000
    home_type = (
        "pg" if re.search(r"\bpgs?\b", lower)
        else "coliving" if re.search(r"co-?living", lower)
        else "sharedFlat" if re.search(r"\bflat\b", lower)
        else None
    )  # fmt: skip
    type_label = {
        "pg": "PGs",
        "coliving": "co-living spaces",
        "sharedFlat": "shared flats",
    }.get(home_type or "", "places")
    areas = list(await ctx.session.scalars(select(Area)))
    area = extract_area(message, areas)
    if area is None and re.search(r"\b(office|work|workplace|tech ?park)\b", lower):
        area = ctx.prefs.office_area
    elif area is None and re.search(r"\bnear (my )?(home|place|room)\b|\bmy area\b", lower):
        area = ctx.prefs.home_area
    where = area.name if area else "Bangalore"
    rent = by_id["rent"]
    matches = await home_service.search(
        ctx, area=area.id if area else None, max_rent=cap, home_type=home_type
    )
    order = extract_sort(message)
    sort_homes(matches, order)
    as_list = wants_list(message)
    top = matches[: extract_count(message) if as_list else 3]
    ev.homes.update({h.id: h for h in top})
    # BachelorBuddy has monthly homes only; say so when someone asks for a hotel to stay in.
    stay_note = (
        "BachelorBuddy lists monthly places to live — PGs, co-living and shared flats — not "
        "hotels for a night. "
        if STAY_CONTEXT.search(lower) and re.search(r"\b(hotels?|lodges?|hostels?)\b", lower)
        else ""
    )
    singular = {"pg": "PG", "coliving": "co-living space", "sharedFlat": "shared flat"}.get(
        home_type or "", "place"
    )
    if top and as_list and len(top) > 1:
        lines = [
            f"{n}. {h.name} ({h.type_label}, {h.area_name}) — {format_inr(h.rent)} a month"
            f"{', food included' if h.food_included else ''}, rated {h.rating}"
            for n, h in enumerate(top, 1)
        ]
        text = (
            f"{stay_note}Here are {len(top)} of the {len(matches)} {type_label} under "
            f"{format_inr(cap)} in {where}, {ORDER_LABELS[order or 'price']}:\n"
            + "\n".join(lines)
            + f"\n\nYou budget {format_inr(rent.limit)} a month for rent now."
        )
    elif top:
        best = top[0]
        freed = rent.limit - best.rent
        versus = (
            f"{format_inr(abs(best.difference_from_average))} below" if best.below_average
            else "right at" if best.difference_from_average == 0
            else f"{format_inr(best.difference_from_average)} above"
        )  # fmt: skip
        found = (
            f"{len(matches)} {type_label} under {format_inr(cap)} in {where}. The cheapest is"
            if len(matches) > 1
            else f"one {singular} under {format_inr(cap)} in {where}:"
        )
        text = (
            f"{stay_note}I found {found} {best.name} at {format_inr(best.rent)} a month"
            f"{' with food included' if best.food_included else ''}, {versus} the area average."
            + (f" Against the {format_inr(rent.limit)} you budget for rent now, that frees up {format_inr(freed)} a month." if freed > 0 else "")
        )  # fmt: skip
    else:
        # Like a person would: the cheapest there at any rent, and what fits the budget elsewhere.
        cheapest_here = (
            await home_service.search(ctx, area=area.id if area else None, home_type=home_type)
        )[:1]
        elsewhere = (
            (await home_service.search(ctx, max_rent=cap, home_type=home_type))[:2] if area else []
        )
        top = cheapest_here + elsewhere
        ev.homes.update({h.id: h for h in top})
        parts = [f"{stay_note}Nothing in {where} comes in under {format_inr(cap)} right now."]
        if cheapest_here:
            here = cheapest_here[0]
            parts.append(
                f"The cheapest {singular} there is {here.name} at {format_inr(here.rent)} a month."
            )
        if elsewhere:
            options = _join(
                [f"{h.name} in {h.area_name} at {format_inr(h.rent)}" for h in elsewhere]
            )
            parts.append(f"Under {format_inr(cap)}, you would need to look elsewhere: {options}.")
        if not top:
            parts.append("Raising the limit a little usually opens up a few options.")
        text = " ".join(parts)
    return _result(
        ev, text, [CardRef(type="home", id=h.id) for h in top], ("home", "budget"),
        (f"Searching {where} for {type_label} under {format_inr(cap)}…", "Comparing each rent against the area average…", "Checking the commute to your tech park…"),
        ("Show me co-living under ₹15,000 near Bellandur", "What is left in my budget?", "How much have I saved this month?"),
    )  # fmt: skip


def _biggest_spends(categories: Sequence[BudgetCategoryOut], n: int = 3) -> list[BudgetCategoryOut]:
    spent = [c for c in categories if c.id != "savings" and c.spent > 0]
    return sorted(spent, key=lambda c: (-c.spent, c.id))[:n]


async def _budget_status(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: budgetStatus. "Where is my money going?" gets the biggest spends first."""
    lower = message.lower()
    biggest = _biggest_spends(budget.categories)
    asks_where = r"\bwhere\b|\bgoing\b|breakdown|\bspent\b|\bspend\b|\bspending\b"
    breakdown = bool(biggest) and re.search(asks_where, lower) is not None
    if not biggest and re.search(asks_where, lower):
        text = (
            f"You haven't logged any spending this month yet, so all "
            f"{format_inr(budget.total_remaining)} is still free for the next "
            f'{budget.days_left_in_month} days. Tell me what you spend, like "I spent ₹120 on '
            'lunch", and I will keep track.'
        )
    elif breakdown:
        text = (
            f"You have spent {format_inr(budget.total_spent)} so far this month. Most of it went "
            "to "
            + _join([f"{c.label.lower()} ({format_inr(c.spent)})" for c in biggest])
            + f". That leaves {format_inr(budget.total_remaining)} for the next "
            f"{budget.days_left_in_month} days, about {format_inr(budget.daily_safe_spend)} a day."
        )
    else:
        text = (
            f"You have {format_inr(budget.total_remaining)} left for the rest of the month, with "
            f"{budget.days_left_in_month} days to go. That works out to about "
            f"{format_inr(budget.daily_safe_spend)} a day without touching your savings goal."
        )
    spending = [c.id for c in budget.categories if c.id != "savings"][:5]
    return _result(
        ev, text, [CardRef(type="budgetSummary", categories=[str(c) for c in spending])], ("budget",),
        ("Reading your budget…", "Adding up where it went…" if breakdown else "Working out a safe daily spend…"),
        ("What is left in my budget?" if breakdown else "Where is my money going?", "How much did I spend on food this month?", "How much have I saved this month?"),
    )  # fmt: skip


async def _savings_status(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: savingsStatus. This month, or past months when asked ("last month", "trend")."""
    if re.search(
        r"\b(last|previous) month\b|\bhistory\b|\btrend\b|\bpast\b|\bmonths\b|\bevery month\b",
        message.lower(),
    ):
        history = await savings_service.history(ctx, 6)
        if not history.months:
            text = (
                "You don't have a finished month yet, so there is no savings history. Your first "
                "month-end report arrives on the 1st; until then, ask how this month is going."
            )
        else:
            last = history.months[-1]
            text = (
                f"Last month ({last.month_label}) you saved {format_inr(last.saved)} against a "
                f"{format_inr(last.goal)} goal. " + history.summary
            )
        return _result(
            ev, text, [], ("savings",), ("Reading your past months…",),
            ("How much have I saved this month?", "Where is my money going?"),
        )  # fmt: skip
    savings = await savings_service.monthly(ctx, budget.month)
    top_source = savings.by_category[0] if savings.by_category else None
    text = (
        f"{savings.headline} You have kept back {format_inr(savings.saved)} so far, "
        f"{savings.percent_of_goal}% of your {format_inr(savings.goal)} goal."
        + (f" Most of it came from {top_source.label.lower()}, at {format_inr(top_source.saved)}." if top_source else "")
    )  # fmt: skip
    return _result(
        ev, text, [], ("savings", "budget"),
        ("Adding up what you kept back…", "Comparing against your goal…"),
        ("What is left in my budget?", "How much did I spend on food?"),
    )  # fmt: skip


async def _deals(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: deals."""
    extract_amount(message)
    message.lower()
    {c.id: c for c in budget.categories}
    usable = await offer_service.usable_offers(ctx)
    expiring = [o for o in usable if o.expiring_soon]
    top = usable[:3]
    ev.offers.update({o.id: o for o in top})
    if top:
        first = top[0]
        ends = (
            "ends today"
            if first.days_left <= 0
            else f"has {first.days_left} {'day' if first.days_left == 1 else 'days'} left"
        )
        text = (
            f"You can use {len(usable)} offers on your {len(ctx.user.cards)} saved cards right now"
            + (f", and {len(expiring)} end within three days" if expiring else "")
            + f". {first.title} on {first.platform} {ends} — on a {format_inr(first.example.order_value)} order you would pay {format_inr(first.example.final_price)}, a real {first.example.effective_percent}% off after the cap."
        )  # fmt: skip
    else:
        text = (
            "None of the live offers work with your saved cards at the moment. Adding a card in "
            "Settings, or checking back in a few days, usually turns up something."
        )
    return _result(
        ev, text, [CardRef(type="offer", id=o.id) for o in top], ("deals",),
        ("Checking your saved cards…", "Finding offers you qualify for…", "Working out the true price after each cap…"),
        ("Formal shoes under ₹1,500 for an interview on Friday", "What is left in my budget?", "Cheapest way to buy groceries this month"),
    )  # fmt: skip


async def _spend_total(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: spendTotal. A day or week lists the expenses; otherwise the month's breakdown."""
    if re.search(r"\b(today|yesterday|week|last month|previous month)\b", message.lower()):
        return await personal.recent_expenses(ctx, ev, message, budget)
    return await _budget_status(ctx, ev, message, budget)


async def _fallback(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    return _result(
        ev, personal.fallback_text(message), [], (), ("Working out what you need…",),
        ("What is my selected location?", "Where is my money going?", "Show places to eat near me, cheapest first", "Show my recent expenses"),
    )  # fmt: skip


HANDLERS = {
    "foodNearby": _food_nearby,
    "productDeadline": _product_deadline,
    "spendOnFood": _spend_on_food,
    "groceryPlan": _grocery_plan,
    "homeSearch": _home_search,
    "budgetStatus": _budget_status,
    "savingsStatus": _savings_status,
    "deals": _deals,
    "spendOnCategory": personal.spend_on_category,
    "spendTotal": _spend_total,
    "expenses": personal.recent_expenses,
    "alerts": personal.alerts,
    "profile": personal.profile,
}


async def run_rules(ctx: Ctx, message: str, recent_food_ids: Sequence[str] = ()) -> AgentResult:
    """`recent_food_ids` are the places the previous reply showed, so "there" can refer to them."""
    ev = Evidence()
    # An explicit "log ₹200 for lunch" is an action, checked before any question.
    entry = personal.parse_expense_log(message)
    intent = "logExpense" if entry else match_intent(message)
    chat = personal.small_talk_kind(message) if intent is None else None
    budget = await budget_service.current_budget(ctx.session, ctx.user, ctx.clock)
    ev.budget = budget.categories
    ev.tool_log.append({"intent": intent or chat or "fallback"})
    if entry is not None:
        return await personal.log_expense(ctx, ev, entry)
    if chat is not None:
        return await personal.small_talk(ctx, ev, chat)
    if intent == "deliveryCompare":
        return await _delivery_compare(ctx, ev, message, budget, recent_food_ids)
    handler = HANDLERS.get(intent or "", _fallback)
    return await handler(ctx, ev, message, budget)
