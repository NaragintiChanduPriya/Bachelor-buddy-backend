from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.calc.delivery import Quote, breakdown, compare_delivery, marked_up_price
from app.calc.geo import bike_minutes, bus_minutes, haversine_km, walking_distance_km
from app.calc.grocery import (
    CatalogItem,
    build_comparison,
    build_grocery_list,
    cheapest_of,
    line_cost_at,
    list_line_id,
)
from app.calc.homes import RentRow, build_search_insight, compare_with_area_average
from app.calc.offers import (
    Card,
    OfferTerms,
    best_offer_for,
    build_example,
    card_matches,
    days_until,
    ineligible_reason,
    is_live,
    offer_discount,
)
from app.core.constants import StoreType

IST = ZoneInfo("Asia/Kolkata")


# ------------------------------------------------------------------ delivery


def dabbarun(dine_in: int) -> Quote:
    return Quote("DabbaRun", marked_up_price(dine_in, 12), 45, 6, 8, 15, 5)


def test_delivery_bill_matches_the_contract_example() -> None:
    bill = breakdown(dabbarun(120), distance_km=4.7)
    assert (
        bill.item_price,
        bill.delivery_fee,
        bill.platform_fee,
        bill.packaging_fee,
        bill.taxes,
    ) == (134, 61, 8, 15, 7)
    assert bill.total == 225
    comparison = compare_delivery(
        listing_id="food_003", listing_name="Mess", dish="Full meals", dine_in_price=120,
        quotes=[dabbarun(120)], distance_km=4.7,
    )  # fmt: skip
    assert (
        comparison.amount_saved,
        comparison.percent_saved,
        comparison.monthly_saving_if_switched,
    ) == (105, 47, 2310)


@pytest.mark.parametrize("dine_in", [15, 49, 120, 333, 999])
@pytest.mark.parametrize("km", [0.3, 2.0, 2.05, 7.77, 15.0])
def test_every_bill_reconciles(dine_in: int, km: float) -> None:
    quotes = [
        Quote("FeastDrop", marked_up_price(dine_in, 18), 35, 8, 12, 20, 5),
        Quote("QuickBite", marked_up_price(dine_in, 22), 29, 10, 15, 25, 5),
        dabbarun(dine_in),
    ]
    comparison = compare_delivery(
        listing_id="x",
        listing_name="x",
        dish="x",
        dine_in_price=dine_in,
        quotes=quotes,
        distance_km=km,
    )
    totals = [o.total for o in comparison.delivery_options]
    assert totals == sorted(totals)
    assert comparison.cheapest_delivery == comparison.delivery_options[0]
    for option in comparison.delivery_options:
        assert option.total == (
            option.item_price
            + option.delivery_fee
            + option.platform_fee
            + option.packaging_fee
            + option.taxes
        )
        assert option.item_price > dine_in or dine_in < 9


def test_distances_and_commutes() -> None:
    assert haversine_km(12.9121, 77.6446, 12.9304, 77.6784) == 4.2  # HSR Layout to Bellandur
    assert walking_distance_km(12.9, 77.6, 12.9, 77.6) == 0.3
    assert (bike_minutes(1), bus_minutes(1)) == (5, 10)
    assert (bike_minutes(10), bus_minutes(10)) == (32, 55)


# ------------------------------------------------------------------ groceries


RICE = CatalogItem(
    "groc_001", "Sona masoori rice", "1 kg", "Rice, flour & dal",
    {"quickCommerce": 78, "supermarket": 68, "kirana": 64, "onlineBulk": 60}, "5 kg bag", 285, 5,
)  # fmt: skip
CURD = CatalogItem(
    "groc_029", "Fresh curd", "500 g", "Dairy & batter",
    {"quickCommerce": 40, "supermarket": 36, "kirana": 32, "onlineBulk": 38}, None, None, None,
)  # fmt: skip
LABELS: dict[StoreType, str] = {
    "quickCommerce": "ZipCart",
    "supermarket": "FreshAisle",
    "kirana": "Kirana",
    "onlineBulk": "StockUp",
}


def test_bulk_packs_apply_only_at_online_bulk_and_only_when_cheaper() -> None:
    assert line_cost_at(RICE, "onlineBulk", 5).total == 285
    assert line_cost_at(RICE, "onlineBulk", 5).bulk_applied
    assert line_cost_at(RICE, "onlineBulk", 7).total == 285 + 2 * 60
    assert line_cost_at(RICE, "onlineBulk", 4).bulk_applied is False
    assert line_cost_at(RICE, "kirana", 5).total == 320


def test_ties_prefer_the_store_nearest_home() -> None:
    assert (
        cheapest_of({"quickCommerce": 50, "supermarket": 50, "kirana": 50, "onlineBulk": 50})
        == "kirana"
    )
    assert (
        cheapest_of({"quickCommerce": 50, "supermarket": 49, "kirana": 50, "onlineBulk": 49})
        == "supermarket"
    )


def test_list_and_comparison_agree() -> None:
    entries = [(RICE, 5), (CURD, 6)]
    grocery_list = build_grocery_list(
        entries, "2026-11", datetime(2026, 11, 15, tzinfo=UTC), LABELS
    )
    comparison = build_comparison(entries, "2026-11", LABELS)
    assert grocery_list.id == "glist_202611"
    assert [line.id for line in grocery_list.items] == ["gli_001", "gli_029"]
    assert grocery_list.estimated_total == comparison.mixed_basket_total == 285 + 6 * 32
    assert grocery_list.items[0].cheapest_unit_price == 57
    totals = {t.store: t.total for t in comparison.store_totals}
    assert totals == {
        "quickCommerce": 390 + 240,
        "supermarket": 340 + 216,
        "kirana": 320 + 192,
        "onlineBulk": 285 + 228,
    }
    assert comparison.cheapest_store == "kirana"
    assert comparison.bulk_saving == totals["quickCommerce"] - totals["onlineBulk"]
    assert (
        comparison.quick_commerce_extra == totals["quickCommerce"] - comparison.mixed_basket_total
    )
    assert comparison.split_saving == totals["kirana"] - comparison.mixed_basket_total
    assert [t.store for t in comparison.store_totals] == [
        "quickCommerce",
        "supermarket",
        "kirana",
        "onlineBulk",
    ]
    assert list_line_id("groc_120") == "gli_120"


# ------------------------------------------------------------------ offers


HDFC_10 = OfferTerms("offer_001", "ShopNest", "HDFC", "credit", 10, None, 500, 1500)


def test_offer_example_matches_the_contract() -> None:
    example = build_example(2499, HDFC_10)
    assert (example.discount, example.final_price, example.effective_percent) == (249, 2250, 10)


def test_discount_rules() -> None:
    assert offer_discount(1499, HDFC_10) == 0  # below the minimum order
    assert offer_discount(9000, HDFC_10) == 500  # capped
    flat = OfferTerms("o", "ZipCart", None, None, None, 150, None, 100)
    assert offer_discount(120, flat) == 120  # never more than the order
    assert build_example(0, flat).effective_percent == 0


def test_card_eligibility_and_reasons() -> None:
    cards = [Card("HDFC", "credit"), Card("SBI", "debit")]
    assert card_matches(HDFC_10, cards)
    hdfc_debit = OfferTerms("o", "ShopNest", "HDFC", "debit", 10, None, None, 0)
    kotak = OfferTerms("o", "ShopNest", "Kotak", "credit", 10, None, None, 0)
    any_icici = OfferTerms("o", "ShopNest", "icici", None, 10, None, None, 0)
    assert (
        ineligible_reason(hdfc_debit, cards)
        == "Needs an HDFC debit card — you have the HDFC credit card"
    )
    assert ineligible_reason(kotak, cards) == "Needs a Kotak credit card, which you have not saved"
    assert card_matches(any_icici, [Card("ICICI", "debit")])
    assert ineligible_reason(HDFC_10, cards) is None


def test_offer_timing_in_ist() -> None:
    now = datetime(2026, 11, 15, 7, 0, tzinfo=UTC)
    ends_tonight = datetime(2026, 11, 15, 18, 29, tzinfo=UTC)  # 23:59 IST
    assert days_until(ends_tonight, now, IST) == 0
    assert days_until(datetime(2026, 11, 17, 18, 29, tzinfo=UTC), now, IST) == 2
    assert is_live(datetime(2026, 11, 1, tzinfo=UTC), ends_tonight, now)
    assert not is_live(datetime(2026, 11, 1, tzinfo=UTC), now, now)


def test_best_offer_takes_the_most_off_on_that_platform() -> None:
    bigger = OfferTerms("offer_009", "ShopNest", None, None, None, 300, None, 1000)
    other_platform = OfferTerms("offer_010", "TrendKart", None, None, 50, None, None, 0)
    best = best_offer_for(2499, "ShopNest", [HDFC_10, bigger, other_platform])
    assert best is not None and (best.offer_id, best.discount, best.final_price) == (
        "offer_009",
        300,
        2199,
    )
    assert best_offer_for(100, "ShopNest", [HDFC_10]) is None


# ------------------------------------------------------------------ homes


def test_area_comparison_and_search_insight() -> None:
    comparison = compare_with_area_average(7200, 10500)
    assert (comparison.difference_from_average, comparison.below_average) == (-3300, True)
    insight = build_search_insight(
        [
            RentRow("home_002", "Green Leaf", 7200, True),
            RentRow("home_009", "Nest", 9800, True),
            RentRow("home_011", "Loft", 15000, False),
        ],
        rent_budget=14000,
    )
    assert insight.match_count == 3
    assert insight.within_budget_count == 2
    assert insight.below_average_count == 2
    assert insight.average_rent == 10667
    assert (insight.cheapest_home_id, insight.cheapest_rent) == ("home_002", 7200)
    assert (insight.monthly_saving_vs_budget, insight.yearly_saving_vs_budget) == (6800, 81600)
    empty = build_search_insight([], rent_budget=14000)
    assert (empty.average_rent, empty.cheapest_home_id, empty.monthly_saving_vs_budget) == (
        None,
        None,
        0,
    )
