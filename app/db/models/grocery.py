"""Grocery stores, the catalog, per-store prices and each user's monthly list."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import GROCERY_CATEGORIES, STORE_ORDER
from app.db.base import Base
from app.db.models._common import one_of
from app.db.models.budget import MONTH_CHECK
from app.db.types import Rupees


class Store(Base):
    """Two stores per store type. The comparison uses, per type, whichever is cheaper for the
    user's list; the primary store is the default when there is no list to compare."""

    __tablename__ = "stores"
    __table_args__ = (one_of("store_type", STORE_ORDER),)

    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    store_type: Mapped[str] = mapped_column(String(16), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(SmallInteger)


class GroceryItem(Base):
    __tablename__ = "grocery_items"
    __table_args__ = (
        one_of("category", GROCERY_CATEGORIES),
        CheckConstraint(
            "(bulk_unit IS NULL) = (bulk_multiple IS NULL)", name="bulk_fields_together"
        ),
        CheckConstraint("bulk_multiple IS NULL OR bulk_multiple > 1", name="bulk_multiple_gt_one"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    unit: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(40), index=True)
    bulk_unit: Mapped[str | None] = mapped_column(String(30))
    bulk_multiple: Mapped[int | None] = mapped_column(SmallInteger)
    position: Mapped[int] = mapped_column(SmallInteger)


class GroceryPrice(Base):
    __tablename__ = "grocery_prices"
    __table_args__ = (
        CheckConstraint("price_paise > 0", name="price_positive"),
        Index("ix_grocery_prices_store", "store_id"),
    )

    item_id: Mapped[str] = mapped_column(
        ForeignKey("grocery_items.id", ondelete="CASCADE"), primary_key=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), primary_key=True
    )
    price: Mapped[int] = mapped_column("price_paise", Rupees)
    #: Price of one bulk pack (online-bulk stores only).
    bulk_price: Mapped[int | None] = mapped_column("bulk_price_paise", Rupees)


class GroceryList(Base):
    __tablename__ = "grocery_lists"
    __table_args__ = (
        UniqueConstraint("user_id", "month", name="uq_grocery_lists_user_month"),
        CheckConstraint(f"month {MONTH_CHECK}", name="month_format"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    month: Mapped[str] = mapped_column(String(7))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[GroceryListItem]] = relationship(
        lazy="raise", cascade="all, delete-orphan", order_by="GroceryListItem.position"
    )


class GroceryListItem(Base):
    __tablename__ = "grocery_list_items"
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 50", name="quantity_range"),)

    list_id: Mapped[int] = mapped_column(
        ForeignKey("grocery_lists.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("grocery_items.id", ondelete="CASCADE"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(SmallInteger)
    position: Mapped[int] = mapped_column(SmallInteger)
