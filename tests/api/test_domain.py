"""Every domain endpoint, signed in as the demo user on the seeded test database."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.db


def data(response: Any) -> Any:
    body = response.json()
    assert response.status_code == 200 and body["success"] is True, body
    return body["data"]


def fails(response: Any, status: int, code: str) -> dict[str, Any]:
    body = response.json()
    assert response.status_code == status, body
    assert body["success"] is False and body["error"]["code"] == code, body
    return body["error"]  # type: ignore[no-any-return]


# ------------------------------------------------------------------ reference and profile


async def test_areas_are_public_and_cacheable(api: AsyncClient) -> None:
    response = await api.get("/api/meta/areas")
    body = data(response)
    assert len(body["areas"]) == 15 and len(body["techParks"]) == 8
    assert body["areas"][0] == {
        "id": "area_hsr",
        "name": "HSR Layout",
        "lat": 12.9121,
        "lng": 77.6446,
        "popular": True,
    }
    orbit = next(p for p in body["techParks"] if p["id"] == "park_orbit")
    assert orbit["areaName"] == "Bellandur"
    assert response.headers["cache-control"] == "public, max-age=3600"


async def test_me(as_arjun: AsyncClient) -> None:
    me = data(await as_arjun.get("/api/me"))
    assert me["id"].startswith("user_")
    assert (me["name"], me["age"], me["avatarInitials"], me["onboarded"]) == (
        "Arjun",
        24,
        "A",
        True,
    )
    prefs = me["preferences"]
    assert (prefs["salary"], prefs["savingsGoal"], prefs["foodPreference"]) == (40000, 8000, "veg")
    assert (prefs["homeAreaName"], prefs["officeAreaName"], prefs["techParkName"]) == (
        "HSR Layout",
        "Bellandur",
        "Orbit Tech Campus",
    )
    assert [c["id"] for c in prefs["cards"]] == [
        "card_hdfc_cc",
        "card_sbi_dc",
        "card_icici_cc",
        "card_axis_dc",
    ]


# ------------------------------------------------------------------ budget and expenses


async def test_budget_matches_the_demo(as_arjun: AsyncClient) -> None:
    budget = data(await as_arjun.get("/api/budget/current"))
    assert (budget["month"], budget["salary"], budget["totalLimit"]) == ("2026-11", 40000, 40000)
    assert (budget["totalSpent"], budget["totalRemaining"], budget["percentUsed"]) == (
        25020,
        14980,
        63,
    )
    assert (budget["daysLeftInMonth"], budget["dailySafeSpend"]) == (15, 465)
    food = next(c for c in budget["categories"] if c["id"] == "food")
    assert food == {
        "id": "food",
        "label": "Food",
        "limit": 7500,
        "spent": 5250,
        "remaining": 2250,
        "percentUsed": 70,
        "status": "warning",
    }
    shopping = next(c for c in budget["categories"] if c["id"] == "shopping")
    assert shopping["remaining"] == 1800


async def test_budget_update_validates_the_whole_set(as_arjun: AsyncClient) -> None:
    over = fails(
        await as_arjun.put(
            "/api/budget/current", json={"categories": [{"id": "misc", "limit": 3000}]}
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert over["details"] == {"total": 41000, "salary": 40000}
    assert "₹41,000" in over["message"]
    fails(
        await as_arjun.put(
            "/api/budget/current", json={"categories": [{"id": "pets", "limit": 1}]}
        ),
        422,
        "VALIDATION_ERROR",
    )
    fails(
        await as_arjun.put(
            "/api/budget/current", json={"categories": [{"id": "food", "limit": 10.5}]}
        ),
        422,
        "VALIDATION_ERROR",
    )
    fails(
        await as_arjun.put("/api/budget/current", json={"categories": []}), 422, "VALIDATION_ERROR"
    )
    moved = data(
        await as_arjun.put(
            "/api/budget/current",
            json={"categories": [{"id": "food", "limit": 8000}, {"id": "misc", "limit": 1500}]},
        )
    )
    food = next(c for c in moved["categories"] if c["id"] == "food")
    assert (food["limit"], food["percentUsed"], food["status"]) == (8000, 66, "ok")
    assert moved["totalLimit"] == 40000


async def test_expense_list_filters_and_totals(as_arjun: AsyncClient) -> None:
    page = await as_arjun.get("/api/expenses", params={"pageSize": 5})
    body = data(page)
    meta = page.json()["meta"]
    assert body["filteredTotal"] == 25020
    assert meta["page"] == 1 and meta["pageSize"] == 5 and meta["total"] > 5
    dates = [e["spentAt"] for e in body["expenses"]]
    assert dates == sorted(dates, reverse=True)
    food = data(await as_arjun.get("/api/expenses", params={"category": "food", "pageSize": 50}))
    assert food["filteredTotal"] == 5250
    assert all(e["category"] == "food" and e["categoryLabel"] == "Food" for e in food["expenses"])
    october = data(await as_arjun.get("/api/expenses", params={"month": "2026-10"}))
    assert october["filteredTotal"] == 40000 - 7600
    assert (
        data(await as_arjun.get("/api/expenses", params={"category": "all"}))["filteredTotal"]
        == 25020
    )
    assert (
        fails(await as_arjun.get("/api/expenses", params={"month": "Oct"}), 400, "BAD_REQUEST")[
            "message"
        ]
        == "The month parameter must look like 2026-10."
    )
    fails(await as_arjun.get("/api/expenses", params={"category": "pets"}), 400, "BAD_REQUEST")
    fails(await as_arjun.get("/api/expenses", params={"pageSize": 500}), 400, "BAD_REQUEST")


async def test_logging_and_deleting_an_expense_moves_the_budget(as_arjun: AsyncClient) -> None:
    created = data(
        await as_arjun.post(
            "/api/expenses",
            json={
                "category": "food",
                "title": "  Lunch at the mess ",
                "amount": 120,
                "merchant": "",
                "note": None,
            },
        )
    )
    expense = created["expense"]
    assert expense["id"].startswith("exp_") and expense["title"] == "Lunch at the mess"
    assert (expense["merchant"], expense["source"], expense["spentAt"]) == (
        None,
        "manual",
        "2026-11-15T07:00:00.000Z",
    )
    assert (created["category"]["spent"], created["category"]["percentUsed"]) == (5370, 72)
    assert data(await as_arjun.get("/api/budget/current"))["totalSpent"] == 25140
    deleted = data(await as_arjun.delete(f"/api/expenses/{expense['id']}"))
    assert deleted == {
        "id": expense["id"],
        "category": {**created["category"], "spent": 5250, "remaining": 2250, "percentUsed": 70},
    }
    fails(await as_arjun.delete(f"/api/expenses/{expense['id']}"), 404, "NOT_FOUND")
    fails(await as_arjun.delete("/api/expenses/not-an-id"), 404, "NOT_FOUND")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"category": "pets", "title": "x", "amount": 10}, "Choose a valid category."),
        ({"category": "food", "title": "  ", "amount": 10}, "Give the expense a short title."),
        (
            {"category": "food", "title": "x", "amount": 0},
            "Enter an amount in whole rupees greater than zero.",
        ),
        (
            {"category": "food", "title": "x", "amount": 12.5},
            "Enter an amount in whole rupees greater than zero.",
        ),
        (
            {"category": "food", "title": "x", "amount": 2_000_000},
            "That amount looks too large. Enter it in rupees.",
        ),
        (
            {"category": "food", "title": "x", "amount": 10, "spentAt": "yesterday"},
            "The spent date is not a valid date.",
        ),
        (
            {"category": "food", "title": "x", "amount": 10, "spentAt": "2026-11-16T07:00:00Z"},
            "You cannot log an expense in the future.",
        ),
    ],
)
async def test_expense_validation_messages(
    as_arjun: AsyncClient, body: dict[str, Any], message: str
) -> None:
    assert (
        fails(await as_arjun.post("/api/expenses", json=body), 422, "VALIDATION_ERROR")["message"]
        == message
    )


# ------------------------------------------------------------------ food


async def test_food_nearby_filters_sorts_and_paginates(as_arjun: AsyncClient) -> None:
    response = await as_arjun.get(
        "/api/food/nearby",
        params={"near": "office", "maxPrice": 150, "sort": "distance", "pageSize": 5},
    )
    items = data(response)
    assert response.json()["meta"]["pageSize"] == 5
    distances = [i["distanceFromOfficeKm"] for i in items]
    assert distances == sorted(distances)
    assert all(i["avgMealPrice"] <= 150 for i in items)
    by_price = data(
        await as_arjun.get("/api/food/nearby", params={"sort": "price", "pageSize": 50})
    )
    prices = [i["avgMealPrice"] for i in by_price]
    assert prices == sorted(prices)
    veg = data(
        await as_arjun.get(
            "/api/food/nearby", params={"veg": "true", "type": "mess", "area": "area_hsr"}
        )
    )
    assert veg and all(i["veg"] and i["type"] == "mess" and i["areaId"] == "area_hsr" for i in veg)
    assert "menu" not in veg[0]  # summaries only
    assert veg[0]["timings"].count(":") == 2


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"near": "moon"}, 'The near parameter must be "home" or "office".'),
        ({"type": "cafe"}, 'Unknown food type "cafe".'),
        ({"sort": "cheapest"}, 'Unknown sort "cheapest". Use price, distance or rating.'),
        ({"maxPrice": 0}, "maxPrice must be greater than zero."),
        ({"area": "area_mars"}, 'Unknown area "area_mars".'),
    ],
)
async def test_food_nearby_rejects_bad_parameters(
    as_arjun: AsyncClient, params: dict[str, Any], message: str
) -> None:
    assert (
        fails(await as_arjun.get("/api/food/nearby", params=params), 400, "BAD_REQUEST")["message"]
        == message
    )


async def test_food_detail_and_delivery_comparison(as_arjun: AsyncClient) -> None:
    listings = data(
        await as_arjun.get("/api/food/nearby", params={"area": "area_bellandur", "pageSize": 50})
    )
    delivering = next(i for i in listings if i["type"] in ("mess", "tiffin"))
    detail = data(await as_arjun.get(f"/api/food/{delivering['id']}"))
    assert detail["menu"] and detail["openingTime"].count(":") == 1
    comparison_response = await as_arjun.get(f"/api/food/{delivering['id']}/compare-delivery")
    if comparison_response.status_code == 200:
        comparison = data(comparison_response)
        options = comparison["deliveryOptions"]
        assert comparison["cheapestDelivery"] == options[0]
        assert [o["total"] for o in options] == sorted(o["total"] for o in options)
        for o in options:
            assert (
                o["total"]
                == o["itemPrice"]
                + o["deliveryFee"]
                + o["platformFee"]
                + o["packagingFee"]
                + o["taxes"]
            )
        assert comparison["amountSaved"] == options[0]["total"] - comparison["dineInPrice"]
        assert comparison["monthlySavingIfSwitched"] == comparison["amountSaved"] * 22
        assert not comparison["dish"].startswith("Monthly")
    else:
        fails(comparison_response, 400, "BAD_REQUEST")
    fails(await as_arjun.get("/api/food/food_999"), 404, "NOT_FOUND")


# ------------------------------------------------------------------ groceries


async def test_grocery_catalog(as_arjun: AsyncClient) -> None:
    everything = data(await as_arjun.get("/api/groceries/catalog"))
    assert len(everything) == 160
    rice = everything[0]
    assert set(rice["prices"]) == {"quickCommerce", "supermarket", "kirana", "onlineBulk"}
    veg = data(
        await as_arjun.get("/api/groceries/catalog", params={"category": "Vegetables", "q": "o"})
    )
    assert veg and all(i["category"] == "Vegetables" and "o" in i["name"].lower() for i in veg)
    bad = fails(
        await as_arjun.get("/api/groceries/catalog", params={"category": "Toys"}),
        400,
        "BAD_REQUEST",
    )
    assert len(bad["details"]["categories"]) == 10


async def test_grocery_list_and_comparison_agree(as_arjun: AsyncClient) -> None:
    grocery_list = data(await as_arjun.get("/api/groceries/list"))
    comparison = data(await as_arjun.get("/api/groceries/compare"))
    assert grocery_list["id"] == "glist_202611" and grocery_list["itemCount"] == 22
    assert grocery_list["estimatedTotal"] == comparison["mixedBasketTotal"]
    assert (
        sum(line["lineTotal"] for line in grocery_list["items"]) == grocery_list["estimatedTotal"]
    )
    totals = {t["store"]: t["total"] for t in comparison["storeTotals"]}
    assert [t["store"] for t in comparison["storeTotals"]] == [
        "quickCommerce",
        "supermarket",
        "kirana",
        "onlineBulk",
    ]
    assert comparison["bulkSaving"] == max(0, totals["quickCommerce"] - totals["onlineBulk"])
    assert comparison["quickCommerceExtra"] == max(
        0, totals["quickCommerce"] - comparison["mixedBasketTotal"]
    )
    cheapest = next(t for t in comparison["storeTotals"] if t["isCheapest"])
    assert comparison["splitSaving"] == cheapest["total"] - comparison["mixedBasketTotal"]
    assert sum(t["cheapestItemCount"] for t in comparison["storeTotals"]) == 22


async def test_replacing_the_grocery_list(as_arjun: AsyncClient) -> None:
    saved = data(
        await as_arjun.put(
            "/api/groceries/list",
            json={
                "items": [
                    {"itemId": "groc_001", "quantity": 5},
                    {"itemId": "groc_005", "quantity": 1},
                ]
            },
        )
    )
    assert [line["id"] for line in saved["items"]] == ["gli_001", "gli_005"]
    assert saved["updatedAt"] == "2026-11-15T07:00:00.000Z"
    assert data(await as_arjun.get("/api/groceries/compare"))["itemCount"] == 2
    assert data(await as_arjun.put("/api/groceries/list", json={"items": []}))["itemCount"] == 0
    dup = fails(
        await as_arjun.put(
            "/api/groceries/list", json={"items": [{"itemId": "groc_001", "quantity": 1}] * 2}
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert "on the list twice" in dup["message"]
    unknown = fails(
        await as_arjun.put(
            "/api/groceries/list", json={"items": [{"itemId": "groc_999", "quantity": 1}]}
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert unknown["message"] == 'Unknown grocery item "groc_999".'
    fails(
        await as_arjun.put(
            "/api/groceries/list", json={"items": [{"itemId": "groc_001", "quantity": 51}]}
        ),
        422,
        "VALIDATION_ERROR",
    )


# ------------------------------------------------------------------ products


async def test_product_search(as_arjun: AsyncClient) -> None:
    response = await as_arjun.get(
        "/api/products/search", params={"category": "formalShoes", "maxPrice": 1500}
    )
    items = data(response)
    assert items and all(p["category"] == "formalShoes" and p["lowestPrice"] <= 1500 for p in items)
    assert [p["lowestPrice"] for p in items] == sorted(p["lowestPrice"] for p in items)
    paged = await as_arjun.get(
        "/api/products/search", params={"pageSize": 10, "page": 2, "sort": "discount"}
    )
    assert paged.json()["meta"] == {"page": 2, "pageSize": 10, "total": 216}
    discounts = [p["discountPercent"] for p in data(paged)]
    assert discounts == sorted(discounts, reverse=True)
    oxford = data(await as_arjun.get("/api/products/search", params={"q": "oxford shoes"}))
    assert oxford and all("oxford" in p["name"].lower() for p in oxford)
    assert (
        fails(
            await as_arjun.get("/api/products/search", params={"q": "x" * 81}), 400, "BAD_REQUEST"
        )["message"]
        == "Keep the search under 80 characters."
    )
    fails(
        await as_arjun.get("/api/products/search", params={"category": "phones"}),
        400,
        "BAD_REQUEST",
    )
    fails(await as_arjun.get("/api/products/search", params={"sort": "newest"}), 400, "BAD_REQUEST")


async def test_product_detail_verdict_and_history(as_arjun: AsyncClient) -> None:
    detail = data(await as_arjun.get("/api/products/prod_055"))
    assert detail["verdict"] in ("buyNow", "wait") and detail["verdictReason"]
    assert detail["lowest90Day"] <= detail["average90Day"] <= detail["highest90Day"]
    assert detail["aboveLowest90Day"] == detail["lowestPrice"] - detail["lowest90Day"]
    assert detail["finalPrice"] == detail["bestDealBasePrice"] - detail["offerSaving"]
    assert detail["totalSavingVsMrp"] == max(0, detail["mrp"] - detail["finalPrice"])
    in_stock = [p["inStock"] for p in detail["platforms"]]
    assert in_stock == sorted(in_stock, reverse=True)
    assert sum(p["isCheapest"] for p in detail["platforms"]) == 1
    assert all(p["deliveryBy"].endswith("T14:30:00.000Z") for p in detail["platforms"])  # 8 PM IST
    history = data(await as_arjun.get("/api/products/prod_055/price-history", params={"days": 30}))
    assert history["days"] == 30 and len(history["points"]) == 30
    assert history["points"][-1]["date"] == "2026-11-15"
    assert history["platforms"] == [
        p for p in ("ShopNest", "TrendKart", "StyleBay") if p in history["platforms"]
    ]
    assert history["summary"].startswith("Over the last 30 days")
    fails(
        await as_arjun.get("/api/products/prod_055/price-history", params={"days": 3}),
        400,
        "BAD_REQUEST",
    )
    fails(await as_arjun.get("/api/products/prod_999"), 404, "NOT_FOUND")


async def test_price_alerts(as_arjun: AsyncClient) -> None:
    alerts = data(await as_arjun.get("/api/products/alerts"))
    assert len(alerts) == 4 and sum(a["triggered"] for a in alerts) == 1
    for alert in alerts:
        assert alert["gapToTarget"] == max(0, alert["currentPrice"] - alert["targetPrice"])
    product = data(await as_arjun.get("/api/products/prod_010"))
    too_high = fails(
        await as_arjun.post(
            "/api/products/prod_010/price-alert", json={"targetPrice": product["lowestPrice"]}
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert too_high["details"] == {"currentPrice": product["lowestPrice"]}
    created = data(
        await as_arjun.post(
            "/api/products/prod_010/price-alert", json={"targetPrice": product["lowestPrice"] - 100}
        )
    )
    moved = data(
        await as_arjun.post(
            "/api/products/prod_010/price-alert", json={"targetPrice": product["lowestPrice"] - 200}
        )
    )
    assert moved["id"] == created["id"] and moved["targetPrice"] == product["lowestPrice"] - 200
    assert (
        data(await as_arjun.get("/api/products/prod_010"))["alertTargetPrice"]
        == moved["targetPrice"]
    )
    assert data(await as_arjun.delete("/api/products/prod_010/price-alert")) == {
        "productId": "prod_010"
    }
    fails(await as_arjun.delete("/api/products/prod_010/price-alert"), 404, "NOT_FOUND")
    fails(
        await as_arjun.post("/api/products/prod_999/price-alert", json={"targetPrice": 10}),
        404,
        "NOT_FOUND",
    )
    fails(
        await as_arjun.post("/api/products/prod_010/price-alert", json={"targetPrice": -5}),
        422,
        "VALIDATION_ERROR",
    )


# ------------------------------------------------------------------ offers


async def test_offers(as_arjun: AsyncClient) -> None:
    usable = data(await as_arjun.get("/api/offers"))
    assert usable["offers"] and all(o["eligible"] for o in usable["offers"])
    assert usable["eligibleCount"] == len(usable["offers"]) < usable["totalCount"]
    first = usable["offers"][0]
    keys = [(o["daysLeft"], -o["example"]["discount"]) for o in usable["offers"]]
    assert keys == sorted(keys)
    assert (
        first["example"]["finalPrice"]
        == first["example"]["orderValue"] - first["example"]["discount"]
    )
    hdfc = next(o for o in usable["offers"] if o["id"] == "offer_001")
    assert hdfc["example"] == {
        "orderValue": 2499,
        "discount": 249,
        "finalPrice": 2250,
        "effectivePercent": 10,
    }
    assert (hdfc["daysLeft"], hdfc["expiringSoon"]) == (2, True)
    everything = data(await as_arjun.get("/api/offers", params={"eligibleOnly": "false"}))
    blocked = [o for o in everything["offers"] if not o["eligible"]]
    assert blocked and all(o["ineligibleReason"] for o in blocked)
    hdfc_card = data(await as_arjun.get("/api/offers", params={"card": "card_hdfc_cc"}))
    assert all(o["bank"] == "HDFC" for o in hdfc_card["offers"])
    soon = data(await as_arjun.get("/api/offers", params={"expiringWithinDays": 1}))
    assert all(o["daysLeft"] <= 1 for o in soon["offers"])
    assert (
        data(await as_arjun.get("/api/offers", params={"platform": "shopnest"}))["offers"][0][
            "platform"
        ]
        == "ShopNest"
    )
    fails(await as_arjun.get("/api/offers", params={"card": "card_kotak_cc"}), 400, "BAD_REQUEST")
    fails(await as_arjun.get("/api/offers", params={"expiringWithinDays": 61}), 400, "BAD_REQUEST")


# ------------------------------------------------------------------ homes


async def test_home_search_and_insight(as_arjun: AsyncClient) -> None:
    response = await as_arjun.get(
        "/api/homes/search",
        params={"area": "area_marathahalli", "maxRent": 10000, "type": "pg", "pageSize": 2},
    )
    body = data(response)
    meta = response.json()["meta"]
    assert len(body["homes"]) == 2 and meta["total"] >= 3
    insight = body["insight"]
    assert insight["matchCount"] == meta["total"]
    assert insight["rentBudget"] == 14000
    assert insight["monthlySavingVsBudget"] == 14000 - insight["cheapestRent"]
    assert insight["yearlySavingVsBudget"] == insight["monthlySavingVsBudget"] * 12
    for home in body["homes"]:
        assert home["differenceFromAverage"] == home["rent"] - home["areaAverageRent"]
        assert home["belowAverage"] == (home["differenceFromAverage"] < 0)
        assert home["techParkName"] == "Orbit Tech Campus"
    rents = [h["rent"] for h in body["homes"]]
    assert rents == sorted(rents)
    near = data(
        await as_arjun.get(
            "/api/homes/search", params={"maxDistanceKm": 3, "techPark": "park_lumina"}
        )
    )
    assert all(
        h["techParkDistanceKm"] <= 3 and h["techParkName"] == "Lumina IT Park"
        for h in near["homes"]
    )


@pytest.mark.parametrize(
    "params",
    [
        {"type": "villa"},
        {"area": "area_mars"},
        {"techPark": "park_x"},
        {"maxRent": 0},
        {"maxDistanceKm": -1},
        {"page": 0},
        {"pageSize": 51},
    ],
)
async def test_home_search_rejects_bad_parameters(
    as_arjun: AsyncClient, params: dict[str, Any]
) -> None:
    fails(await as_arjun.get("/api/homes/search", params=params), 400, "BAD_REQUEST")


async def test_home_detail(as_arjun: AsyncClient) -> None:
    home = data(await as_arjun.get("/api/homes/home_001"))
    assert len(home["commutes"]) == 8
    distances = [c["distanceKm"] for c in home["commutes"]]
    assert distances == sorted(distances)
    assert home["nearestTechParkKm"] == distances[0]
    assert home["moveInCost"] == home["rent"] + home["deposit"]
    assert home["yearlyDifferenceFromAverage"] == home["differenceFromAverage"] * 12
    assert home["differenceFromRentBudget"] == home["rent"] - home["rentBudget"]
    fails(await as_arjun.get("/api/homes/home_999"), 404, "NOT_FOUND")


# ------------------------------------------------------------------ savings and notifications


async def test_savings_this_month(as_arjun: AsyncClient) -> None:
    savings = data(await as_arjun.get("/api/savings/monthly"))
    assert (savings["month"], savings["monthLabel"]) == ("2026-11", "November 2026")
    assert (savings["saved"], savings["goal"], savings["percentOfGoal"]) == (2730, 8000, 34)
    assert (savings["projectedByMonthEnd"], savings["onTrack"]) == (5140, False)
    assert savings["headline"] == "On pace for ₹5,140 — ₹2,860 short of your goal."
    assert [r["agent"] for r in savings["byRecommendation"]]
    saved = [r["saved"] for r in savings["byRecommendation"]]
    assert saved == sorted(saved, reverse=True)


async def test_savings_past_months_and_history(as_arjun: AsyncClient) -> None:
    october = data(await as_arjun.get("/api/savings/monthly", params={"month": "2026-10"}))
    assert october["saved"] == october["projectedByMonthEnd"] == 7600
    history = data(await as_arjun.get("/api/savings/history"))
    assert [m["saved"] for m in history["months"]] == [2100, 3400, 4600, 5800, 6900, 7600]
    assert history["months"][0]["month"] == "2026-05"
    assert (history["totalSaved"], history["averageSaved"], history["bestMonth"]) == (
        30400,
        5067,
        "October 2026",
    )
    assert history["trendPercent"] == 262
    assert (
        len(data(await as_arjun.get("/api/savings/history", params={"months": 2}))["months"]) == 2
    )
    fails(
        await as_arjun.get("/api/savings/monthly", params={"month": "2026-12"}), 400, "BAD_REQUEST"
    )
    fails(await as_arjun.get("/api/savings/monthly", params={"month": "2020-01"}), 404, "NOT_FOUND")
    fails(await as_arjun.get("/api/savings/history", params={"months": 25}), 400, "BAD_REQUEST")


async def test_notifications(as_arjun: AsyncClient) -> None:
    payload = data(await as_arjun.get("/api/notifications"))
    assert len(payload["items"]) == 13 and payload["unreadCount"] == 4
    assert payload["serverNow"] == "2026-11-15T07:00:00.000Z"
    times = [n["createdAt"] for n in payload["items"]]
    assert times == sorted(times, reverse=True)
    first_unread = next(n for n in payload["items"] if not n["read"])
    after_one = data(await as_arjun.patch(f"/api/notifications/{first_unread['id']}/read"))
    assert after_one["unreadCount"] == 3
    assert data(await as_arjun.patch("/api/notifications/read-all"))["unreadCount"] == 0
    fails(await as_arjun.patch("/api/notifications/notif_99999/read"), 404, "NOT_FOUND")
