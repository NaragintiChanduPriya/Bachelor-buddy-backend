"""The synthetic data generator, in memory: determinism and internal consistency."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import timedelta

import pytest

from app.calc.budget import generate_limits
from app.core.constants import HISTORY_DAYS_STORED
from scripts.seed import vocab
from scripts.seed.anchors import TEST_NOW
from scripts.seed.catalog import Catalog, build_catalog
from scripts.seed.common import IST, Anchor
from scripts.seed.reference import RENT_MULTIPLIERS
from scripts.seed.users import ARJUN_CURRENT, ARJUN_SAVED, SeedUser, build_users

ANCHOR = Anchor(TEST_NOW)
#: Real brands the brief forbids (and near-copies), checked against every generated name.
BANNED = re.compile(
    r"swiggy|zomato|dunzo|zepto|blinkit|instamart|bigbasket|jiomart|dmart|amazon|flipkart|"
    r"myntra|ajio|meesho|nykaa|zolo|stanza|colive|nestaway|\boyo\b|nobroker|\bmtr\b|kamat|"
    r"adiga|vidyarthi|rameshwaram|meghana|truffles|nandini|boat|titan|fastrack|casio|levi|"
    r"wrangler|woodland|bata|wildcraft|skybags|steelbird|studds",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return build_catalog(42, ANCHOR)


@pytest.fixture(scope="module")
def users(catalog: Catalog) -> list[SeedUser]:
    return build_users(catalog, 42, ANCHOR, 6)


def rows(catalog: Catalog, table: str) -> list[dict[str, object]]:
    t = catalog.tables[table]
    return [dict(zip(t.columns, r, strict=True)) for r in t.rows]


def test_the_same_seed_gives_identical_data(catalog: Catalog, users: list[SeedUser]) -> None:
    again = build_catalog(42, ANCHOR)
    assert {n: t.rows for n, t in again.tables.items()} == {
        n: t.rows for n, t in catalog.tables.items()
    }
    assert repr(build_users(again, 42, ANCHOR, 6)) == repr(users)


def test_the_app_database_gets_no_people_by_default(catalog: Catalog) -> None:
    """Real people sign up; only tests and demos ask for seeded users."""
    assert build_users(catalog, 42, ANCHOR, 0, include_demo=False) == []
    only_demo = build_users(catalog, 42, ANCHOR, 0)
    assert [u.email for u in only_demo] == ["arjun@demo.com"]


def test_a_different_seed_gives_different_data(catalog: Catalog) -> None:
    other = build_catalog(7, ANCHOR)
    assert other.tables["food_listings"].rows != catalog.tables["food_listings"].rows


def test_volumes_meet_the_brief(catalog: Catalog) -> None:
    counts = {name: len(t.rows) for name, t in catalog.tables.items()}
    assert counts["areas"] >= 11 and counts["tech_parks"] >= 5
    assert counts["food_listings"] >= 150
    assert counts["stores"] == 8 and counts["grocery_items"] >= 150
    assert counts["products"] >= 200
    assert counts["offers"] >= 40
    assert counts["homes"] >= 120
    assert counts["price_history"] == counts["product_prices"] * HISTORY_DAYS_STORED


def test_primary_keys_are_unique(catalog: Catalog) -> None:
    for table in catalog.tables.values():
        keys = [tuple(r[table.columns.index(k)] for k in table.keys) for r in table.rows]
        assert len(keys) == len(set(keys)), table.name


def test_menus_and_listing_prices_agree(catalog: Catalog) -> None:
    menu: dict[object, list[dict[str, object]]] = defaultdict(list)
    for item in rows(catalog, "menu_items"):
        menu[item["listing_id"]].append(item)
    for listing in rows(catalog, "food_listings"):
        items = menu[listing["id"]]
        assert 6 <= len(items) <= 23, listing["id"]
        dishes = [
            i["price_paise"] for i in items if not str(i["name"]).startswith(("Monthly", "Weekly"))
        ]
        assert listing["price_min_paise"] == min(dishes)  # type: ignore[type-var]
        assert listing["price_max_paise"] == max(dishes)  # type: ignore[type-var]
        if listing["veg"]:
            assert all(i["veg"] for i in items), listing["id"]


def test_rents_sit_within_25_percent_of_the_area_average(catalog: Catalog) -> None:
    averages = {
        (r["area_id"], r["home_type"]): r["average_rent_paise"]
        for r in rows(catalog, "area_rent_averages")
    }
    for home in rows(catalog, "homes"):
        average = averages[(home["area_id"], home["type"])]
        assert 0.75 * average <= home["rent_paise"] <= 1.25 * average, home["id"]  # type: ignore[operator]
    assert set(RENT_MULTIPLIERS) == {"pg", "coliving", "sharedFlat"}


def test_price_history_has_no_gaps_and_ends_today(catalog: Catalog) -> None:
    by_series: dict[tuple[object, object], list[object]] = defaultdict(list)
    for point in rows(catalog, "price_history"):
        by_series[(point["product_id"], point["platform"])].append(point["day"])
    for days in by_series.values():
        assert len(days) == HISTORY_DAYS_STORED
        assert days[-1] == ANCHOR.today
        assert days[-1] - days[0] == timedelta(days=HISTORY_DAYS_STORED - 1)  # type: ignore[operator]
    today = {
        (r["product_id"], r["platform"]): r["price_paise"] for r in rows(catalog, "product_prices")
    }
    last = {
        (p["product_id"], p["platform"]): p["price_paise"]
        for p in rows(catalog, "price_history")
        if p["day"] == ANCHOR.today
    }
    assert today == last


def test_offers_include_live_expired_and_future(catalog: Catalog) -> None:
    offers = rows(catalog, "offers")
    live = [o for o in offers if o["valid_from"] <= ANCHOR.now < o["valid_till"]]  # type: ignore[operator]
    expired = [o for o in offers if o["valid_till"] <= ANCHOR.now]  # type: ignore[operator]
    future = [o for o in offers if o["valid_from"] > ANCHOR.now]  # type: ignore[operator]
    assert len(live) >= 25 and expired and future
    assert all(
        (o["discount_percent"] is None) != (o["flat_discount_paise"] is None) for o in offers
    )
    assert any(o["bank"] == "Kotak" for o in live)  # an offer the demo user cannot use


def test_demo_answers_are_guaranteed(catalog: Catalog) -> None:
    cheap_veg_near_office = [
        listing for listing in catalog.listings
        if listing.area_id == "area_bellandur" and listing.veg and listing.avg_meal_price <= 150
    ]  # fmt: skip
    assert len(cheap_veg_near_office) >= 3
    shoes = [p for p in catalog.products if p.category == "formalShoes" and p.lowest_price <= 1500]
    assert len(shoes) >= 3
    pgs = [
        h for h in rows(catalog, "homes")
        if h["area_id"] == "area_marathahalli" and h["type"] == "pg" and h["rent_paise"] <= 1_000_000  # type: ignore[operator]
    ]  # fmt: skip
    assert len(pgs) >= 3


def test_names_are_invented(catalog: Catalog, users: list[SeedUser]) -> None:
    names = [
        str(r[1])
        for t in ("food_listings", "products", "homes", "stores")
        for r in catalog.tables[t].rows
    ]
    names += [str(r[2]) for r in catalog.tables["products"].rows]  # brands
    names += [t.merchant or "" for templates in vocab.EXPENSE_TEMPLATES.values() for t in templates]
    offenders = [n for n in names if BANNED.search(n)]
    assert offenders == []
    assert len({str(r[1]) for r in catalog.tables["food_listings"].rows}) == len(
        catalog.tables["food_listings"].rows
    )


def test_arjun_hits_the_demo_numbers(users: list[SeedUser]) -> None:
    arjun = users[0]
    assert arjun.email == "arjun@demo.com"
    by_month: dict[str, Counter[str]] = defaultdict(Counter)
    for expense in arjun.expenses:
        by_month[expense.spent_at.astimezone(IST).strftime("%Y-%m")][expense.category] += (
            expense.amount
        )
    assert dict(by_month[ANCHOR.month]) == ARJUN_CURRENT
    assert sum(by_month[ANCHOR.month].values()) == 25020
    assert [s[1] for s in arjun.snapshots] == list(ARJUN_SAVED)
    for month, saved, goal, salary, spent in arjun.snapshots:
        assert salary - sum(by_month[month].values()) == saved == salary - spent
        assert goal == 8000
    assert arjun.budgets[ANCHOR.month] == generate_limits(40000, 8000)
    assert len(arjun.notifications) >= 10
    assert any(r[5] for r in arjun.recommendations) and len(arjun.alerts) >= 3
    assert arjun.grocery_list is not None and len(arjun.grocery_list[2]) == 22


def test_every_user_is_consistent(users: list[SeedUser]) -> None:
    for user in users:
        assert all(e.amount > 0 for e in user.expenses)
        assert all(e.spent_at <= ANCHOR.now for e in user.expenses), user.email
        assert len(user.budgets) == 7
        for limits in user.budgets.values():
            assert sum(limits.values()) == user.salary
        assert 16 <= user.age <= 100 and user.goal < user.salary
    assert len({u.email for u in users}) == len(users)
