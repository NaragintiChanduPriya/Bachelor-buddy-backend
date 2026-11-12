"""Catalog builders: places, food, groceries, products with price history, offers and homes.

Every entity draws from its own seeded stream (`rng_for(seed, kind, id)`), so the output is
identical for the same seed and anchor, and adding an entity never shifts the others.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import time, timedelta

from app.calc.delivery import marked_up_price
from app.calc.geo import ROAD_FACTOR, bike_minutes, bus_minutes, haversine_km
from app.calc.products import PlatformToday, round_to_price_point, summarize_platforms
from app.core.constants import HISTORY_DAYS_STORED, SHOPPING_PLATFORMS
from app.core.money import format_inr, js_round
from scripts.seed import vocab
from scripts.seed.common import Anchor, Rng, Table, offset_point, ordinal, paise, rng_for, round_to
from scripts.seed.reference import (
    AREAS,
    DELIVERY_PLATFORMS,
    FOOD_OFFER_PLATFORMS,
    GROCERY_OFFER_PLATFORMS,
    GST_PERCENT,
    RENT_MULTIPLIERS,
    SHOPPING_OFFER_PLATFORMS,
    STORES,
    TECH_PARKS,
    AreaSeed,
)

PLAN_PREFIXES = ("Monthly", "Weekly")


@dataclass(frozen=True)
class ListingInfo:
    id: str
    name: str
    kind: str
    area_id: str
    veg: bool
    avg_meal_price: int
    delivery: bool


@dataclass(frozen=True)
class ProductInfo:
    id: str
    name: str
    brand: str
    category: str
    lowest_price: int
    mrp: int


@dataclass
class Catalog:
    tables: dict[str, Table] = field(default_factory=dict)
    listings: list[ListingInfo] = field(default_factory=list)
    products: list[ProductInfo] = field(default_factory=list)
    grocery_ids: dict[str, str] = field(default_factory=dict)

    def table(self, name: str, columns: tuple[str, ...], keys: tuple[str, ...]) -> Table:
        self.tables[name] = Table(name, columns, keys)
        return self.tables[name]


# ------------------------------------------------------------------ places


def _places(catalog: Catalog) -> None:
    areas = catalog.table("areas", ("id", "name", "lat", "lng", "popular", "position"), ("id",))
    for position, a in enumerate(AREAS):
        areas.add(a.id, a.name, a.lat, a.lng, a.popular, position)
    parks = catalog.table(
        "tech_parks", ("id", "name", "area_id", "lat", "lng", "position"), ("id",)
    )
    for position, p in enumerate(TECH_PARKS):
        parks.add(p.id, p.name, p.area_id, p.lat, p.lng, position)
    averages = catalog.table(
        "area_rent_averages",
        ("area_id", "home_type", "average_rent_paise"),
        ("area_id", "home_type"),
    )
    for a in AREAS:
        for home_type in RENT_MULTIPLIERS:
            averages.add(a.id, home_type, paise(area_average(a, home_type)))


def area_average(area: AreaSeed, home_type: str) -> int:
    return round_to(area.pg_rent * RENT_MULTIPLIERS[home_type], 500)


# ------------------------------------------------------------------ food

FOOD_KINDS = ("darshini", "mess", "tiffin", "restaurant", "cafe")
KIND_WEIGHTS = (30, 25, 15, 20, 10)
VEG_PROBABILITY = {"darshini": 1.0, "mess": 0.75, "tiffin": 0.85, "restaurant": 0.4, "cafe": 0.7}
DELIVERY_PROBABILITY = {"darshini": 0.6, "mess": 0.5, "tiffin": 1.0, "restaurant": 0.9, "cafe": 0.7}
HOURS: dict[str, tuple[tuple[str, str], ...]] = {
    "darshini": (("06:30", "22:00"), ("06:00", "21:30"), ("07:00", "22:30")),
    "mess": (("11:30", "22:00"), ("12:00", "15:30"), ("11:00", "21:30"), ("19:00", "23:00")),
    "tiffin": (("11:00", "21:00"), ("10:30", "20:30")),
    "restaurant": (("12:00", "23:30"), ("11:30", "23:00"), ("18:30", "01:00"), ("12:30", "00:30")),
    "cafe": (("08:00", "22:00"), ("09:00", "23:00"), ("07:30", "21:30")),
}
#: Guarantees for the demo: cheap, veg, open at lunch near the demo user's home and office.
FORCED_FOOD: dict[str, tuple[tuple[str, bool, tuple[str, str]], ...]] = {
    "area_bellandur": (
        ("mess", True, ("11:30", "22:00")),
        ("darshini", True, ("06:30", "22:00")),
        ("mess", True, ("12:00", "15:30")),
        ("tiffin", True, ("11:00", "21:00")),
        ("darshini", True, ("07:00", "22:30")),
    ),
    "area_hsr": (
        ("darshini", True, ("06:30", "22:00")),
        ("mess", True, ("11:30", "22:00")),
        ("tiffin", True, ("11:00", "21:00")),
    ),
    "area_kadubeesanahalli": (
        ("mess", True, ("11:30", "22:00")),
        ("darshini", True, ("06:00", "21:30")),
    ),
}


def _hhmm(value: str) -> time:
    hour, minute = (int(p) for p in value.split(":"))
    return time(hour, minute)


def _menu_key(kind: str, veg: bool) -> str:
    if kind == "mess":
        return "mess_veg" if veg else "mess_nonveg"
    if kind == "restaurant":
        return "restaurant_veg" if veg else "restaurant_nonveg"
    return kind


def _food_name(rng: Rng, kind: str) -> str:
    prefix = rng.choice(vocab.FOOD_NAME_PREFIXES) if rng.chance(0.55) else ""
    parts = (prefix, rng.choice(vocab.FOOD_NAME_CORES), rng.choice(vocab.FOOD_NAME_SUFFIXES[kind]))
    return " ".join(part for part in parts if part)


def _unique_name(used: set[str], candidates: Iterable[str]) -> str:
    """The first candidate not used yet. Callers pass a generator of random names."""
    for name in candidates:
        if name not in used:
            used.add(name)
            return name
    raise RuntimeError("could not find a unique name; widen the vocabulary")


def _food(catalog: Catalog, seed: int) -> None:
    listings = catalog.table(
        "food_listings",
        (
            "id", "name", "type", "area_id", "lat", "lng", "veg", "rating", "review_count",
            "price_min_paise", "price_max_paise", "avg_meal_price_paise",
            "monthly_plan_price_paise", "tags", "opening_time", "closing_time", "description",
            "address", "delivery_available", "sponsored", "thumbnail_seed",
        ),
        ("id",),
    )  # fmt: skip
    menu = catalog.table(
        "menu_items",
        ("id", "listing_id", "name", "price_paise", "veg", "popular", "position"),
        ("id",),
    )
    quotes = catalog.table(
        "delivery_quotes",
        (
            "menu_item_id", "platform_id", "item_price_paise", "base_delivery_fee_paise",
            "platform_fee_paise", "packaging_fee_paise",
        ),
        ("menu_item_id", "platform_id"),
    )  # fmt: skip
    platforms = catalog.table(
        "delivery_platforms",
        ("id", "name", "item_markup_percent", "per_km_fee_paise", "gst_percent", "position"),
        ("id",),
    )
    for position, dp in enumerate(DELIVERY_PLATFORMS):
        platforms.add(
            dp.id, dp.name, dp.item_markup_percent, paise(dp.per_km_fee), GST_PERCENT, position
        )

    used_names: set[str] = set()
    number = 0
    for area in AREAS:
        forced = FORCED_FOOD.get(area.id, ())
        for slot in range(area.food_count):
            number += 1
            listing_id = f"food_{number:03d}"
            rng = rng_for(seed, "food", listing_id)
            if slot < len(forced):
                kind, veg, hours = forced[slot]
            else:
                kind = rng.choices(FOOD_KINDS, KIND_WEIGHTS)[0]
                veg = rng.chance(VEG_PROBABILITY[kind])
                hours = rng.choice(HOURS[kind])
            name = _unique_name(used_names, (_food_name(rng, kind) for _ in range(80)))
            items = _build_menu(rng, kind, veg, cheap=slot < len(forced))
            dishes = [i for i in items if not i[0].startswith(PLAN_PREFIXES)]
            plan = next((i for i in items if i[0].startswith("Monthly lunch plan")), None)
            prices = [i[1] for i in dishes]
            mains = [i[1] for i in dishes if i[3]]
            if kind == "tiffin" and plan is not None:
                avg = js_round(plan[1] / 26)
            elif mains:
                avg = js_round(sum(mains) / len(mains))
            else:
                avg = js_round((min(prices) + max(prices)) / 2)
            delivery = kind == "tiffin" or rng.chance(DELIVERY_PROBABILITY[kind])
            lat, lng = offset_point(rng, area.lat, area.lng, 1.4)
            tags = list(rng.sample(vocab.FOOD_TAGS[kind], k=3))
            if kind == "cafe" and "Cafe" not in tags:
                tags.insert(0, "Cafe")
            listings.add(
                listing_id,
                name,
                "restaurant" if kind == "cafe" else kind,
                area.id,
                lat,
                lng,
                veg,
                rng.rating(3.6, 4.8),
                rng.randint(48, 1840),
                paise(min(prices)),
                paise(max(prices)),
                paise(avg),
                paise(plan[1]) if kind == "tiffin" and plan else None,
                tags,
                _hhmm(hours[0]),
                _hhmm(hours[1]),
                rng.choice(vocab.FOOD_DESCRIPTIONS[kind]).format(area=area.name),
                f"{ordinal(rng.randint(1, 30))} {rng.choice(('Main', 'Cross'))}, "
                f"{rng.choice(vocab.LOCALITIES[area.id])}, {area.name}",
                delivery,
                slot >= len(forced) and rng.chance(0.05),
                rng.randint(0, 359),
            )
            for position, (dish, price, dish_veg, popular) in enumerate(items, start=1):
                item_id = f"{listing_id}_item_{position:02d}"
                menu.add(item_id, listing_id, dish, paise(price), dish_veg, popular, position)
                if delivery and not dish.startswith(PLAN_PREFIXES):
                    for dp in DELIVERY_PLATFORMS:
                        quotes.add(
                            item_id,
                            dp.id,
                            paise(marked_up_price(price, dp.item_markup_percent)),
                            paise(dp.base_delivery_fee),
                            paise(dp.platform_fee),
                            paise(dp.packaging_fee),
                        )
            catalog.listings.append(
                ListingInfo(listing_id, name, kind, area.id, veg, avg, delivery)
            )


def _build_menu(
    rng: Rng, kind: str, veg: bool, *, cheap: bool
) -> list[tuple[str, int, bool, bool]]:
    """(name, price, veg, popular) in menu order: 6-20 dishes with at least two popular mains;
    tiffin services also list their plans."""
    templates = [t for t in vocab.MENU_TEMPLATES[_menu_key(kind, veg)] if t.veg or not veg]
    plans = [t for t in templates if t.name.startswith(PLAN_PREFIXES)]
    dishes = [t for t in templates if t not in plans]
    popular = [t for t in dishes if t.popular]
    count = rng.randint(6, min(20, len(dishes)))
    chosen = rng.sample(popular, k=min(len(popular), rng.randint(2, 4)))
    rest = [t for t in dishes if t not in chosen]
    chosen += rng.sample(rest, k=max(0, min(len(rest), count - len(chosen))))
    chosen.sort(key=dishes.index)

    if kind in {"darshini", "mess", "tiffin"}:
        offset = rng.choice((-10, -5, 0) if cheap else (-10, -5, 0, 0, 5, 10, 15))
        factor = 1.0
    else:
        offset, factor = 0, rng.uniform(0.9, 1.25)
    result = [
        (t.name, max(10, round_to(t.base_price * factor + offset, 5)), t.veg, t.popular)
        for t in chosen
    ]
    if kind == "tiffin":
        result += [
            (t.name, round_to(t.base_price * rng.uniform(0.9, 1.15), 50), t.veg, False)
            for t in plans
        ]
    return result


# ------------------------------------------------------------------ groceries

STORE_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "quickCommerce": {"fresh": (1.15, 1.35), "default": (1.08, 1.22)},
    "supermarket": {"fresh": (1.04, 1.18), "spice": (1.0, 1.12), "default": (0.93, 1.05)},
    "kirana": {"fresh": (0.94, 1.0), "default": (0.98, 1.04)},
    "onlineBulk": {"fresh": (1.06, 1.25), "spice": (0.9, 1.0), "default": (0.86, 0.95)},
}


def _groceries(catalog: Catalog, seed: int) -> None:
    stores = catalog.table(
        "stores", ("id", "name", "store_type", "is_primary", "position"), ("id",)
    )
    for position, s in enumerate(STORES):
        stores.add(s.id, s.name, s.store_type, s.is_primary, position)
    items = catalog.table(
        "grocery_items",
        ("id", "name", "unit", "category", "bulk_unit", "bulk_multiple", "position"),
        ("id",),
    )
    prices = catalog.table(
        "grocery_prices",
        ("item_id", "store_id", "price_paise", "bulk_price_paise"),
        ("item_id", "store_id"),
    )
    for position, t in enumerate(vocab.GROCERY_ITEMS):
        item_id = f"groc_{position + 1:03d}"
        catalog.grocery_ids[t.name] = item_id
        items.add(item_id, t.name, t.unit, t.category, t.bulk_unit, t.bulk_multiple, position)
        for store in STORES:
            rng = rng_for(seed, "grocery", item_id, store.id)
            ranges = STORE_RANGES[store.store_type]
            low, high = ranges.get(t.kind, ranges["default"])
            unit = max(5, js_round(t.kirana_price * rng.uniform(low, high)))
            bulk = None
            if store.store_type == "onlineBulk" and t.bulk_multiple:
                bulk = js_round(unit * t.bulk_multiple * rng.uniform(0.85, 0.93))
            prices.add(item_id, store.id, paise(unit), paise(bulk) if bulk else None)


# ------------------------------------------------------------------ products

PER_CATEGORY = 27
PATTERNS = ("steady", "inSale", "afterSale", "festivalSpike", "recentDrop")
PATTERN_WEIGHTS = (30, 15, 25, 10, 20)
#: Days ago the festival sale (one per year, late October-ish) started, and how long it ran.
FESTIVAL_START, FESTIVAL_LENGTH = 46, 6


def _sale_ratio(rng: Rng, primary: bool, depth: tuple[float, float]) -> float:
    ratio = rng.uniform(*depth)
    return ratio if primary else 1 - (1 - ratio) / 2


def _series(
    rng: Rng, *, level: int, pattern: str, primary: bool, events: dict[str, int | float]
) -> list[int]:
    """One platform's daily price, oldest first, today last."""
    days = HISTORY_DAYS_STORED
    weeks = days // 7 + 1
    noise = [rng.uniform(-0.015, 0.015) for _ in range(weeks)]
    trend = float(events["trend"])
    festival = bool(events["festival"])
    festival_ratio = _sale_ratio(rng, primary, (0.72, 0.8))
    sale_ratio = _sale_ratio(rng, primary, (0.74, 0.8))
    drop_ratio = 0.8 if primary else 0.9
    series: list[int] = []
    for index in range(days):
        days_ago = days - 1 - index
        value = level * (1 + trend * (index / (days - 1) - 1)) * (1 + noise[days_ago // 7])
        if festival and FESTIVAL_START - FESTIVAL_LENGTH < days_ago <= FESTIVAL_START:
            value = level * festival_ratio
        if pattern == "inSale" and days_ago < int(events["sale_length"]):
            value = level * sale_ratio
        elif pattern == "afterSale":
            cycle, length, ended = (int(events[k]) for k in ("cycle", "sale_length", "ended"))
            since = days_ago - ended
            if since >= 0 and since % cycle < length:
                value = level * sale_ratio
        elif pattern == "festivalSpike" and days_ago < 24:
            value = level * (1 + 0.14 * (1 - days_ago / 24))
        elif pattern == "recentDrop" and days_ago < int(events["drop"]):
            value = level * drop_ratio
        series.append(round_to_price_point(value))
    return series


def _products(catalog: Catalog, seed: int, anchor: Anchor) -> None:
    products = catalog.table(
        "products",
        (
            "id", "name", "brand", "category", "mrp_paise", "rating", "review_count",
            "description", "highlights", "thumbnail_seed", "sponsored_platform",
            "lowest_price_paise", "highest_price_paise", "discount_percent",
            "cheapest_platform", "fastest_delivery_days",
        ),
        ("id",),
    )  # fmt: skip
    platform_rows = catalog.table(
        "product_prices",
        (
            "product_id", "platform", "price_paise", "in_stock", "delivery_days", "sponsored",
            "base_price_paise",
        ),
        ("product_id", "platform"),
    )  # fmt: skip
    history = catalog.table(
        "price_history",
        ("product_id", "platform", "day", "price_paise"),
        ("product_id", "platform", "day"),
    )
    dates = [
        anchor.today - timedelta(days=HISTORY_DAYS_STORED - 1 - i)
        for i in range(HISTORY_DAYS_STORED)
    ]
    number = 0
    for category, spec in vocab.PRODUCT_CATEGORIES.items():
        used: set[str] = set()
        for slot in range(PER_CATEGORY):
            number += 1
            product_id = f"prod_{number:03d}"
            rng = rng_for(seed, "product", product_id)
            forced = category == "formalShoes" and slot < 3
            if forced:
                item = spec.items[slot % 2]
                name = _unique_name(used, (f"{rng.choice(spec.styles)} {item}" for _ in range(80)))
            else:
                name = _unique_name(
                    used, (f"{rng.choice(spec.styles)} {rng.choice(spec.items)}" for _ in range(80))
                )
            brand = rng.choice(spec.brands)
            low, high = spec.mrp_range
            mrp = max(low, round_to(rng.randint(low, high), 100) - 1)
            if forced:
                mrp = rng.choice((2499, 2799, 2999))
                base = 1749
                pattern = ("recentDrop", "inSale", "recentDrop")[slot]
            else:
                base = round_to_price_point(mrp * rng.uniform(0.55, 0.85))
                pattern = rng.choices(PATTERNS, PATTERN_WEIGHTS)[0]
            listed = (
                list(SHOPPING_PLATFORMS)
                if forced or rng.chance(0.85)
                else rng.sample(list(SHOPPING_PLATFORMS), k=2)
            )
            listed.sort(key=SHOPPING_PLATFORMS.index)
            primary = listed[0] if forced else rng.choice(listed)
            fast = forced or rng.chance(0.35)
            out_of_stock = None
            if not forced and len(listed) == 3 and rng.chance(0.08):
                out_of_stock = rng.choice([p for p in listed if p != primary])
            sponsored = rng.choice(listed) if not forced and rng.chance(0.06) else None
            events: dict[str, int | float] = {
                "trend": rng.uniform(-0.05, 0.05),
                "festival": (pattern != "steady" and rng.chance(0.6)) or rng.chance(0.3),
                "sale_length": rng.randint(3, 5),
                "cycle": rng.randint(28, 40),
                "ended": rng.randint(4, 14),
                "drop": rng.randint(4, 10),
            }
            today_rows: list[PlatformToday] = []
            for platform in listed:
                is_primary = platform == primary
                level = base if is_primary else round_to_price_point(base * rng.uniform(0.97, 1.12))
                series = _series(
                    rng_for(seed, "series", product_id, platform),
                    level=level,
                    pattern=pattern,
                    primary=is_primary,
                    events=events,
                )
                delivery_days = (
                    (1 if forced else rng.randint(1, 2))
                    if is_primary and fast
                    else rng.randint(2, 6)
                )
                in_stock = platform != out_of_stock
                for day, price in zip(dates, series, strict=True):
                    history.add(product_id, platform, day, paise(price))
                platform_rows.add(
                    product_id,
                    platform,
                    paise(series[-1]),
                    in_stock,
                    delivery_days,
                    platform == sponsored,
                    paise(level),
                )
                today_rows.append(PlatformToday(platform, series[-1], in_stock, delivery_days))
            summary = summarize_platforms(today_rows, mrp)
            products.add(
                product_id,
                name,
                brand,
                category,
                paise(mrp),
                rng.rating(3.6, 4.7),
                rng.randint(40, 4200),
                rng.choice(spec.descriptions).format(brand=brand, name=name),
                list(rng.sample(spec.highlights, k=3)),
                rng.randint(0, 359),
                sponsored,
                paise(summary.lowest_price),
                paise(summary.highest_price),
                summary.discount_percent,
                summary.cheapest_platform,
                summary.fastest_delivery_days,
            )
            catalog.products.append(
                ProductInfo(product_id, name, brand, category, summary.lowest_price, mrp)
            )


# ------------------------------------------------------------------ offers

CODE_PREFIX = {
    "ShopNest": "NEST",
    "TrendKart": "TREND",
    "StyleBay": "STYLE",
    "FeastDrop": "FEAST",
    "QuickBite": "BITE",
    "DabbaRun": "DABBA",
    "ZipCart": "ZIP",
    "SwiftCrate": "SWIFT",
    "StockUp Wholesale": "STOCKUP",
    "FreshAisle Supermarket": "FRESH",
}
OFFER_RANGES = {
    #: (percent caps, minimum orders, flat discounts) as (low, high, step)
    "shopping": ((250, 1000, 50), (999, 2999, 500), (100, 400, 50)),
    "food": ((50, 150, 25), (199, 399, 50), (40, 125, 5)),
    "groceries": ((75, 300, 25), (499, 1499, 250), (50, 200, 25)),
}


def _offers(catalog: Catalog, seed: int, anchor: Anchor) -> None:
    offers = catalog.table(
        "offers",
        (
            "id", "kind", "title", "description", "platform", "platform_category", "bank",
            "card_type", "code", "discount_percent", "flat_discount_paise",
            "max_discount_paise", "min_order_value_paise", "valid_from", "valid_till",
        ),
        ("id",),
    )  # fmt: skip
    # The contract's worked example, always live and ending in two days.
    offers.add(
        "offer_001",
        "card",
        "10% off with HDFC credit cards",
        "10% instant discount up to ₹500 on ShopNest orders above ₹1,500.",
        "ShopNest",
        "shopping",
        "HDFC",
        "credit",
        None,
        10,
        None,
        paise(500),
        paise(1500),
        anchor.days_ago(14, 0, 0),
        anchor.days_ahead(2, 23, 59),
    )
    plan = ["live"] * 29 + ["expired"] * 10 + ["future"] * 5
    for index, status in enumerate(plan, start=2):
        offer_id = f"offer_{index:03d}"
        rng = rng_for(seed, "offer", offer_id)
        category = rng.choice(("shopping",) * 4 + ("food",) * 3 + ("groceries",) * 3)
        platform = rng.choice(
            {
                "shopping": SHOPPING_OFFER_PLATFORMS,
                "food": FOOD_OFFER_PLATFORMS,
                "groceries": GROCERY_OFFER_PLATFORMS,
            }[category]
        )
        kind = rng.choices(("card", "coupon", "cashback"), (55, 30, 15))[0]
        # Make sure some offers need cards the demo user lacks, so eligibility varies.
        if index in (3, 4):
            kind = "card"
        bank = card_type = code = None
        if kind == "card" or (kind == "cashback" and rng.chance(0.6)):
            bank = "Kotak" if index == 3 else rng.choice(("HDFC", "SBI", "ICICI", "Axis", "Kotak"))
            card_type = (
                "debit" if index == 4 else rng.choices(("credit", "debit", None), (55, 25, 20))[0]
            )
            if index == 4:
                bank = "HDFC"
        caps, minimums, flats = OFFER_RANGES[category]
        minimum = rng.money(minimums[0], minimums[1], minimums[2])
        percent = flat = cap = None
        if rng.chance(0.7):
            percent = rng.choice((5, 10, 10, 12, 15, 20))
            cap = rng.money(*caps)
        else:
            flat = rng.money(*flats)
            minimum = max(minimum, flat * 4)
        if kind == "coupon":
            code = f"{CODE_PREFIX[platform]}{percent or flat}"
        value = f"{percent}%" if percent else format_inr(flat or 0)
        cards = f"{bank} {card_type} cards" if card_type else f"{bank} cards"
        title = {
            "card": f"{value} off with {cards}",
            "coupon": f"{value} off with code {code}",
            "cashback": f"{value} cashback" + (f" with {cards}" if bank else ""),
        }[kind]
        verb = "cashback" if kind == "cashback" else "instant discount"
        description = (
            f"{percent}% {verb} up to {format_inr(cap or 0)} on {platform} orders above "
            f"{format_inr(minimum)}."
            if percent
            else f"{format_inr(flat or 0)} {verb} on {platform} orders above {format_inr(minimum)}."
        )
        if bank:
            description += f" Valid on {cards}."
        if status == "live":
            valid_from = anchor.days_ago(rng.randint(1, 20), 0, 0)
            ends = rng.choice((0, 1, 2, 3)) if rng.chance(0.25) else rng.randint(4, 25)
            valid_till = anchor.days_ahead(ends, 23, 59)
        elif status == "expired":
            valid_from = anchor.days_ago(rng.randint(40, 60), 0, 0)
            valid_till = anchor.days_ago(rng.randint(1, 15), 23, 59)
        else:
            valid_from = anchor.days_ahead(rng.randint(2, 10), 0, 0)
            valid_till = anchor.days_ahead(rng.randint(15, 40), 23, 59)
        offers.add(
            offer_id,
            kind,
            title,
            description,
            platform,
            category,
            bank,
            card_type,
            code,
            percent,
            paise(flat) if flat else None,
            paise(cap) if cap else None,
            paise(minimum),
            valid_from,
            valid_till,
        )


# ------------------------------------------------------------------ homes

HOME_TYPE_WEIGHTS = (("pg", 50), ("coliving", 25), ("sharedFlat", 25))
SHARING = {
    "pg": (("single", 25), ("double", 40), ("triple", 35)),
    "coliving": (("single", 50), ("double", 50)),
    "sharedFlat": (("single", 60), ("double", 30), ("entireFlat", 10)),
}
AMENITIES = {
    "pg": vocab.PG_AMENITIES,
    "coliving": vocab.COLIVING_AMENITIES,
    "sharedFlat": vocab.FLAT_AMENITIES,
}


def _homes(catalog: Catalog, seed: int, anchor: Anchor) -> None:
    homes = catalog.table(
        "homes",
        (
            "id", "name", "type", "area_id", "lat", "lng", "rent_paise", "deposit_paise",
            "sharing", "food_included", "bachelor_friendly", "rating", "review_count",
            "thumbnail_seed", "sponsored", "description", "address", "amenities",
            "food_details", "meals_per_day", "notice_period_days", "maintenance_included",
            "available_from",
        ),
        ("id",),
    )  # fmt: skip
    commutes = catalog.table(
        "home_commutes",
        ("home_id", "tech_park_id", "distance_km", "bike_minutes", "bus_minutes"),
        ("home_id", "tech_park_id"),
    )
    used: set[str] = set()
    number = 0
    for area in AREAS:
        for slot in range(area.home_count):
            number += 1
            home_id = f"home_{number:03d}"
            rng = rng_for(seed, "home", home_id)
            forced = area.id == "area_marathahalli" and slot < 3
            home_type = (
                "pg"
                if forced
                else rng.choices(
                    [t for t, _ in HOME_TYPE_WEIGHTS], [w for _, w in HOME_TYPE_WEIGHTS]
                )[0]
            )
            sharing = rng.choices(
                [s for s, _ in SHARING[home_type]], [w for _, w in SHARING[home_type]]
            )[0]
            average = area_average(area, home_type)
            low, high = (0.76, 0.86) if forced else (0.76, 1.24)
            if sharing == "entireFlat":
                low, high = 1.12, 1.24
            rent = max(4000, round_to(average * rng.uniform(low, high), 500))
            rent = min(
                max(rent, round_to(average * 0.75 + 249, 500)), round_to(average * 1.25 - 249, 500)
            )
            locality = rng.choice(vocab.LOCALITIES[area.id])
            if home_type == "pg":
                name = _unique_name(
                    used,
                    (
                        (f"{rng.choice(vocab.PG_NAME_CORES)} {rng.choice(vocab.PG_NAME_SUFFIXES)}")
                        for _ in range(80)
                    ),
                )
            elif home_type == "coliving":
                name = _unique_name(
                    used, (f"{rng.choice(vocab.COLIVING_BRANDS)} {locality}" for _ in range(80))
                )
            elif sharing == "entireFlat":
                localities = vocab.LOCALITIES[area.id]
                name = _unique_name(
                    used,
                    (f"Entire 1BHK, {rng.choice(localities)}, {area.name}" for _ in range(80)),
                )
            else:
                name = _unique_name(
                    used,
                    (
                        rng.choice(vocab.FLAT_NAME_PATTERNS).format(
                            bhk=rng.choice((2, 3)), locality=locality
                        )
                        for _ in range(80)
                    ),
                )
            food = (home_type == "pg" and rng.chance(0.8)) or (
                home_type == "coliving" and rng.chance(0.5)
            )
            if home_type == "pg":
                deposit = round_to(rng.choice((rent, rent * 2, 10000, 15000)), 1000)
            elif home_type == "coliving":
                deposit = rent * 2
            else:
                deposit = round_to(rent * rng.choice((3, 4)), 1000)
            available_now = rng.chance(0.65)
            available_from = (
                anchor.days_ago(rng.randint(1, 25), 10, 0)
                if available_now
                else anchor.days_ahead(rng.randint(3, 30), 10, 0)
            )
            lat, lng = offset_point(rng, area.lat, area.lng, 1.2)
            homes.add(
                home_id,
                name,
                home_type,
                area.id,
                lat,
                lng,
                paise(rent),
                paise(deposit),
                sharing,
                food,
                rng.chance(0.95),
                rng.rating(3.7, 4.7),
                rng.randint(24, 480),
                rng.randint(0, 359),
                not forced and rng.chance(0.05),
                rng.choice(vocab.HOME_DESCRIPTIONS[home_type]).format(area=area.name),
                f"{locality}, {area.name}, Bengaluru",
                list(rng.sample(AMENITIES[home_type], k=rng.randint(5, 8))),
                rng.choice(vocab.PG_FOOD_DETAILS) if food else None,
                rng.choice((2, 3)) if food else None,
                rng.choice((15, 30))
                if home_type == "pg"
                else (30 if home_type == "coliving" else rng.choice((30, 60))),
                home_type != "sharedFlat" or rng.chance(0.6),
                available_from,
            )
            for park in TECH_PARKS:
                park_rng = rng_for(seed, "commute", home_id, park.id)
                road = haversine_km(lat, lng, park.lat, park.lng) * ROAD_FACTOR
                distance = max(0.5, js_round((road + park_rng.uniform(-0.2, 0.6)) * 10) / 10)
                commutes.add(
                    home_id, park.id, distance, bike_minutes(distance), bus_minutes(distance)
                )


def build_catalog(seed: int, anchor: Anchor) -> Catalog:
    catalog = Catalog()
    _places(catalog)
    _food(catalog, seed)
    _groceries(catalog, seed)
    _products(catalog, seed, anchor)
    _offers(catalog, seed, anchor)
    _homes(catalog, seed, anchor)
    return catalog
