"""Eateries, menus, delivery platforms and per-dish delivery quotes."""

from __future__ import annotations

from datetime import time

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import FOOD_PLACE_TYPES
from app.db.base import Base
from app.db.models._common import one_of
from app.db.models.reference import Area
from app.db.types import Rupees


class FoodListing(Base):
    __tablename__ = "food_listings"
    __table_args__ = (
        one_of("type", FOOD_PLACE_TYPES),
        CheckConstraint("rating BETWEEN 0 AND 5", name="rating_range"),
        CheckConstraint("price_min_paise <= price_max_paise", name="price_range"),
        Index("ix_food_listings_area", "area_id"),
        Index("ix_food_listings_type", "type"),
        Index("ix_food_listings_avg_meal_price", "avg_meal_price_paise"),
        Index("ix_food_listings_rating", "rating"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(12))
    area_id: Mapped[str] = mapped_column(ForeignKey("areas.id"))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    veg: Mapped[bool] = mapped_column(Boolean)
    rating: Mapped[float] = mapped_column(Float)
    review_count: Mapped[int] = mapped_column(Integer)
    price_min: Mapped[int] = mapped_column("price_min_paise", Rupees)
    price_max: Mapped[int] = mapped_column("price_max_paise", Rupees)
    #: The headline number for sorting and the maxPrice filter. For a tiffin service it is the
    #: monthly plan divided by the meals it covers.
    avg_meal_price: Mapped[int] = mapped_column("avg_meal_price_paise", Rupees)
    monthly_plan_price: Mapped[int | None] = mapped_column("monthly_plan_price_paise", Rupees)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)))
    opening_time: Mapped[time] = mapped_column(Time)
    closing_time: Mapped[time] = mapped_column(Time)
    description: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(String(200))
    delivery_available: Mapped[bool] = mapped_column(Boolean)
    sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    thumbnail_seed: Mapped[int] = mapped_column(Integer)

    area: Mapped[Area] = relationship(lazy="raise")
    menu: Mapped[list[MenuItem]] = relationship(
        lazy="raise", cascade="all, delete-orphan", order_by="MenuItem.position"
    )


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        CheckConstraint("price_paise > 0", name="price_positive"),
        Index("ix_menu_items_listing", "listing_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("food_listings.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    price: Mapped[int] = mapped_column("price_paise", Rupees)
    veg: Mapped[bool] = mapped_column(Boolean)
    popular: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(SmallInteger)


class DeliveryPlatform(Base):
    """Fee rules for an (invented) delivery app."""

    __tablename__ = "delivery_platforms"

    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    item_markup_percent: Mapped[int] = mapped_column(SmallInteger)
    #: Added per kilometre beyond the first two.
    per_km_fee: Mapped[int] = mapped_column("per_km_fee_paise", Rupees)
    gst_percent: Mapped[int] = mapped_column(SmallInteger)
    position: Mapped[int] = mapped_column(SmallInteger)


class DeliveryQuote(Base):
    """What a dish costs on one platform before the distance-based part of the delivery fee."""

    __tablename__ = "delivery_quotes"

    menu_item_id: Mapped[str] = mapped_column(
        ForeignKey("menu_items.id", ondelete="CASCADE"), primary_key=True
    )
    platform_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_platforms.id", ondelete="CASCADE"), primary_key=True
    )
    #: Platforms list a marked-up price, so this is above the dine-in price.
    item_price: Mapped[int] = mapped_column("item_price_paise", Rupees)
    base_delivery_fee: Mapped[int] = mapped_column("base_delivery_fee_paise", Rupees)
    platform_fee: Mapped[int] = mapped_column("platform_fee_paise", Rupees)
    packaging_fee: Mapped[int] = mapped_column("packaging_fee_paise", Rupees)

    platform: Mapped[DeliveryPlatform] = relationship(lazy="raise")
