"""Enumerations shared by models, schemas and services. They mirror the frontend's `src/types`."""

from __future__ import annotations

from typing import Final, Literal

BudgetCategoryId = Literal[
    "rent", "food", "groceries", "shopping", "travel", "bills", "misc", "savings"
]
CATEGORY_IDS: Final[tuple[BudgetCategoryId, ...]] = (
    "rent",
    "food",
    "groceries",
    "shopping",
    "travel",
    "bills",
    "misc",
    "savings",
)
CATEGORY_LABELS: Final[dict[str, str]] = {
    "rent": "Rent",
    "food": "Food",
    "groceries": "Groceries",
    "shopping": "Shopping",
    "travel": "Travel",
    "bills": "Bills",
    "misc": "Misc",
    "savings": "Savings",
}
#: Spending categories (everything except the savings set-aside).
SPENDING_CATEGORIES: Final[tuple[str, ...]] = tuple(c for c in CATEGORY_IDS if c != "savings")
#: Costs that land in full early in the month, so they count fully from day one.
FIXED_CATEGORIES: Final[frozenset[str]] = frozenset({"rent", "bills"})

BudgetStatus = Literal["ok", "warning", "danger"]
ExpenseSource = Literal["manual", "delivery", "subscription", "recurring"]
EXPENSE_SOURCES: Final[tuple[str, ...]] = ("manual", "delivery", "subscription", "recurring")

FoodPreference = Literal["veg", "nonVeg", "eggetarian", "vegan"]
FOOD_PREFERENCES: Final[tuple[str, ...]] = ("veg", "nonVeg", "eggetarian", "vegan")
CardType = Literal["credit", "debit"]

FoodPlaceType = Literal["darshini", "mess", "tiffin", "restaurant"]
FOOD_PLACE_TYPES: Final[tuple[str, ...]] = ("darshini", "mess", "tiffin", "restaurant")
FoodSort = Literal["price", "distance", "rating"]
NearAnchor = Literal["home", "office"]

StoreType = Literal["quickCommerce", "supermarket", "kirana", "onlineBulk"]
#: Column order everywhere the store types are listed.
STORE_ORDER: Final[tuple[StoreType, ...]] = ("quickCommerce", "supermarket", "kirana", "onlineBulk")
#: Tie-break order when two stores cost the same: nearest home first.
STORE_TIE_ORDER: Final[tuple[StoreType, ...]] = (
    "kirana",
    "supermarket",
    "onlineBulk",
    "quickCommerce",
)
GROCERY_CATEGORIES: Final[tuple[str, ...]] = (
    "Rice, flour & dal",
    "Oil, ghee & sugar",
    "Spices & masala",
    "Coffee & tea",
    "Dairy & batter",
    "Vegetables",
    "Fruit",
    "Bakery & breakfast",
    "Snacks",
    "Household & toiletries",
)

ProductCategory = Literal[
    "shirts", "jeans", "formalShoes", "backpacks", "earphones", "watches", "raincoats", "helmets"
]
PRODUCT_CATEGORY_LABELS: Final[dict[str, str]] = {
    "shirts": "Shirts",
    "jeans": "Jeans",
    "formalShoes": "Formal shoes",
    "backpacks": "Backpacks",
    "earphones": "Earphones",
    "watches": "Watches",
    "raincoats": "Raincoats",
    "helmets": "Helmets",
}
ProductSort = Literal["price", "rating", "discount"]
#: Fixed platform order, so each platform keeps the same chart colour in the UI.
SHOPPING_PLATFORMS: Final[tuple[str, ...]] = ("ShopNest", "TrendKart", "StyleBay")
PriceVerdict = Literal["buyNow", "wait"]
#: Days of daily price history kept per product and platform.
HISTORY_DAYS_STORED: Final = 180
#: Days the API and the verdict look back over.
HISTORY_DAYS_API: Final = 90

OfferKind = Literal["card", "coupon", "cashback"]
OfferPlatformCategory = Literal["shopping", "food", "groceries"]
#: The order value used for each offer's worked example, raised to the minimum order if higher.
TYPICAL_ORDER_VALUE: Final[dict[str, int]] = {"shopping": 2499, "food": 349, "groceries": 899}
EXPIRING_SOON_DAYS: Final = 3

HomeType = Literal["pg", "coliving", "sharedFlat"]
HOME_TYPES: Final[tuple[str, ...]] = ("pg", "coliving", "sharedFlat")
HOME_TYPE_LABELS: Final[dict[str, str]] = {
    "pg": "PG",
    "coliving": "Co-living",
    "sharedFlat": "Shared flat",
}
SharingType = Literal["single", "double", "triple", "entireFlat"]
SHARING_TYPES: Final[tuple[str, ...]] = ("single", "double", "triple", "entireFlat")

AgentName = Literal[
    "concierge", "budget", "food", "grocery", "shopping", "deals", "home", "savings"
]
AGENT_NAMES: Final[tuple[str, ...]] = (
    "concierge",
    "budget",
    "food",
    "grocery",
    "shopping",
    "deals",
    "home",
    "savings",
)
NotificationKind = Literal[
    "budgetWarning",
    "mealSuggestion",
    "priceDrop",
    "groceryReminder",
    "offerExpiring",
    "savingsReport",
    "tip",
]
NOTIFICATION_KINDS: Final[tuple[str, ...]] = (
    "budgetWarning",
    "mealSuggestion",
    "priceDrop",
    "groceryReminder",
    "offerExpiring",
    "savingsReport",
    "tip",
)
