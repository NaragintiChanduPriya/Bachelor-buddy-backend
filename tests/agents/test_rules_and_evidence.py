"""Pure agent pieces: intent matching, extraction, card building and the number check."""

from __future__ import annotations

import pytest

from app.agents.evidence import CardRef, Evidence
from app.agents.personal import ExpenseLog, parse_expense_log, small_talk_kind
from app.agents.rules import (
    extract_amount,
    extract_category,
    extract_count,
    extract_price_cap,
    extract_sort,
    has_word,
    match_intent,
    wants_list,
)
from app.agents.tools import TOOLS, compact_schema
from app.schemas.budget import BudgetCategoryOut
from app.schemas.food import FoodListingSummary


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("I have ₹150 and I'm hungry near office", "foodNearby"),
        ("Formal shoes under ₹1,500 for an interview on Friday", "productDeadline"),
        ("How much did I spend on food this month?", "spendOnFood"),
        ("Cheapest way to buy groceries this month", "groceryPlan"),
        ("Find a PG under ₹10,000 near Marathahalli", "homeSearch"),
        ("How much money is left in my budget?", "budgetStatus"),
        ("How much have I saved this month?", "savingsStatus"),
        ("What offers can I use on my card?", "deals"),
        ("tell me a joke", None),
    ],
)
def test_the_demo_requests_route_to_the_right_intent(message: str, intent: str | None) -> None:
    assert match_intent(message) == intent


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        # "rice" used to match inside "prices", sending this to the grocery plan.
        ("give me hotels list nearby me in the order of lowest to highest prices", "foodNearby"),
        ("great prices on rice?", None),
        ("hotels near my room", "foodNearby"),
        ("top 5 restaurants near office highest to lowest", "foodNearby"),
        ("best rated mess near home under 100", "foodNearby"),
        ("nearest darshini", "foodNearby"),
        ("Show me monthly tiffin plans", "foodNearby"),
        ("need a hotel room for 2 nights near Koramangala", "homeSearch"),
        ("PGs in HSR lowest to highest rent below 10k", "homeSearch"),
        ("Is delivery cheaper than going there?", "deliveryCompare"),
        ("Is delivery cheaper than eating at the mess?", "deliveryCompare"),
        ("Where is my money going?", "budgetStatus"),
        ("How much did I spend on food near office?", "spendOnFood"),
    ],
)
def test_everyday_phrasings_route_like_a_person_would(message: str, intent: str | None) -> None:
    assert match_intent(message) == intent


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("what is my selected location", "profile"),
        ("where do i live", "profile"),
        ("what is my salary", "profile"),
        ("what cards have I saved", "profile"),
        ("who am i", "profile"),
        ("tell me about myself", "profile"),
        ("what is my email", "profile"),
        ("How much have I saved toward my goal", "savingsStatus"),
        ("What offers can I use on my cards?", "deals"),
        ("hotels near my office", "foodNearby"),
        ("PGs near my office", "homeSearch"),
        ("how much did I spend on rent this month", "spendOnCategory"),
        ("how much have I spent this month", "spendTotal"),
        ("what did I spend yesterday", "spendTotal"),
        ("show my recent expenses", "expenses"),
        ("my biggest expense this month", "expenses"),
        ("Show my notifications", "alerts"),
        ("Show my price alerts", "alerts"),
        ("what is on my grocery list", "groceryPlan"),
        ("how much did I save last month", "savingsStatus"),
    ],
)
def test_questions_about_the_user_route_to_their_data(message: str, intent: str) -> None:
    assert match_intent(message) == intent


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("I spent 120 on lunch", ExpenseLog(120, "Lunch", "food")),
        ("log 200 for auto to office", ExpenseLog(200, "Auto to office", "travel")),
        ("add expense ₹1,200 wifi bill", ExpenseLog(1200, "Wifi bill", "bills")),
        ("spent 5k on rent", ExpenseLog(5000, "Rent", "rent")),
        ("paid 90 for chai", ExpenseLog(90, "Chai", "food")),
        ("how much did I spend on lunch?", None),  # a question, never a write
        ("I spent too much", None),  # no amount
        ("show my expenses", None),
    ],
)
def test_only_explicit_requests_log_an_expense(message: str, expected: ExpenseLog | None) -> None:
    assert parse_expense_log(message) == expected


def test_small_talk() -> None:
    assert small_talk_kind("hi") == "greeting"
    assert small_talk_kind("Good morning!") == "greeting"
    assert small_talk_kind("thanks") == "thanks"
    assert small_talk_kind("what can you do?") == "help"
    assert small_talk_kind("hi, show my recent expenses for today please") is None


def test_words_match_whole() -> None:
    assert has_word("cheap dosa", "cheap") and has_word("any hotels?", "hotel")
    assert has_word("two messes", "mess") and has_word("have ₹150", "₹")
    assert not has_word("lowest prices", "rice") and not has_word("cheapest", "cheap")


def test_list_requests_are_understood() -> None:
    message = "give me hotels list nearby me in the order of lowest to highest prices"
    assert wants_list(message) and extract_sort(message) == "price"
    assert extract_sort("restaurants highest to lowest") == "priceDesc"
    assert extract_sort("best rated mess") == "rating"
    assert extract_sort("nearest darshini") == "distance"
    assert extract_sort("find me the cheapest lunch") is None  # one pick, not an ordering
    assert not wants_list("I have ₹150 and I'm hungry near office")
    assert extract_count("top 3 messes") == 3 and extract_count("hotels") == 6
    assert extract_count("top 50 places") == 10


def test_price_caps_ignore_counts() -> None:
    assert extract_price_cap("I have ₹150 and I'm hungry") == 150
    assert extract_price_cap("PGs below 10k") == 10000
    assert extract_price_cap("under Rs. 1,500") == 1500
    assert extract_price_cap("top 10 restaurants") is None
    assert extract_price_cap("only 2 places") is None


def test_extraction_helpers() -> None:
    assert extract_amount("Formal shoes under ₹1,500") == 1500
    assert extract_amount("I have 150 rs") == 150
    assert extract_amount("no numbers") is None
    assert extract_category("need formal shoes") == "formalShoes"
    assert extract_category("good earbuds?") == "earphones"
    assert extract_category("a laptop bag") == "backpacks"
    assert extract_category("dinner") is None


def listing(listing_id: str, price: int) -> FoodListingSummary:
    return FoodListingSummary(
        id=listing_id, name="Annapoorna Mess", type="mess", area_id="area_hsr", area_name="HSR Layout",
        veg=True, rating=4.5, review_count=100, price_min=30, price_max=120, avg_meal_price=price,
        distance_from_home_km=0.4, distance_from_office_km=4.1, tags=[], open_now=True,
        timings="11:30 – 22:00", thumbnail_seed=1, sponsored=False, monthly_plan_price=None,  # noqa: RUF001
    )  # fmt: skip


def test_cards_come_only_from_what_tools_returned() -> None:
    ev = Evidence()
    ev.food["food_003"] = listing("food_003", 102)
    ev.budget = [
        BudgetCategoryOut(
            id="food",
            label="Food",
            limit=7500,
            spent=5250,
            remaining=2250,
            percent_used=70,
            status="warning",
        ),
        BudgetCategoryOut(
            id="savings",
            label="Savings",
            limit=8000,
            spent=0,
            remaining=8000,
            percent_used=0,
            status="ok",
        ),
    ]
    cards = ev.build_cards(
        [
            CardRef(type="food", id="food_003"),
            CardRef(type="food", id="food_999"),  # invented: dropped
            CardRef(type="product", id="prod_001"),  # never looked up: dropped
            CardRef(type="food", id="food_003"),  # duplicate: dropped
            CardRef(type="budgetSummary"),
            CardRef(type="groceryPlan"),  # no grocery tool ran: dropped
        ]
    )
    assert [c.type for c in cards] == ["food", "budgetSummary"]
    assert [row.id for row in cards[1].budget] == ["food"]  # type: ignore[union-attr]


def test_number_check_flags_amounts_no_tool_returned() -> None:
    ev = Evidence()
    ev.record_numbers(
        {"avgMealPrice": 102, "nested": [{"remaining": 2250}], "note": "costs ₹1,649"}
    )
    assert ev.unknown_amounts("A meal is ₹102 and you have ₹2,250 left; shoes ₹1,649.") == []
    assert ev.unknown_amounts("Only ₹99 a meal!") == [99]


def test_agents_used_follow_the_canonical_order() -> None:
    ev = Evidence()
    ev.add_agent("food")
    ev.add_agent("budget")
    assert ev.agents_used() == ["concierge", "budget", "food"]


def test_every_tool_has_a_compact_valid_schema() -> None:
    assert len(TOOLS) >= 16
    for tool in TOOLS.values():
        schema = tool.schema()
        parameters = schema["function"]["parameters"]
        assert schema["type"] == "function"
        assert parameters["type"] == "object"
        assert "title" not in parameters  # annotations dropped...
        assert set(parameters.get("required", [])) <= set(parameters.get("properties", {}))
        assert tool.agent in {"budget", "food", "grocery", "shopping", "deals", "home", "savings"}
    # ...but a field that is really called "title" survives.
    log_expense = TOOLS["log_expense"].schema()["function"]["parameters"]
    assert "title" in log_expense["properties"] and "title" in log_expense["required"]
    assert "title" not in log_expense["properties"]["title"]
    assert compact_schema({"title": {"type": "string", "title": "Title"}}) == {
        "title": {"type": "string"}
    }
