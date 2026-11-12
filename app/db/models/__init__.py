"""ORM models. Every model is imported here so `Base.metadata` is complete for Alembic."""

from app.db.models.activity import (
    AgentRun,
    ChatConversation,
    ChatMessage,
    JobRun,
    Notification,
    Recommendation,
    SavingsSnapshot,
    SeedRun,
)
from app.db.models.budget import Budget, BudgetCategory, Expense
from app.db.models.food import DeliveryPlatform, DeliveryQuote, FoodListing, MenuItem
from app.db.models.grocery import GroceryItem, GroceryList, GroceryListItem, GroceryPrice, Store
from app.db.models.homes import AreaRentAverage, Home, HomeCommute
from app.db.models.offers import Offer
from app.db.models.reference import Area, TechPark
from app.db.models.shopping import PriceAlert, PriceHistory, Product, ProductPrice
from app.db.models.users import RefreshToken, User, UserCard, UserPreferences

__all__ = [
    "AgentRun",
    "Area",
    "AreaRentAverage",
    "Budget",
    "BudgetCategory",
    "ChatConversation",
    "ChatMessage",
    "DeliveryPlatform",
    "DeliveryQuote",
    "Expense",
    "FoodListing",
    "GroceryItem",
    "GroceryList",
    "GroceryListItem",
    "GroceryPrice",
    "Home",
    "HomeCommute",
    "JobRun",
    "MenuItem",
    "Notification",
    "Offer",
    "PriceAlert",
    "PriceHistory",
    "Product",
    "ProductPrice",
    "Recommendation",
    "RefreshToken",
    "SavingsSnapshot",
    "SeedRun",
    "Store",
    "TechPark",
    "User",
    "UserCard",
    "UserPreferences",
]
