"""Products, today's price per platform, daily price history and price alerts."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import PRODUCT_CATEGORY_LABELS, SHOPPING_PLATFORMS
from app.db.base import Base
from app.db.models._common import created_at_column, one_of
from app.db.types import Rupees


class Product(Base):
    """A product. The lowest/highest price, discount, cheapest platform and fastest delivery are
    copied from `product_prices` whenever prices change, so search can filter and sort in SQL."""

    __tablename__ = "products"
    __table_args__ = (
        one_of("category", tuple(PRODUCT_CATEGORY_LABELS)),
        CheckConstraint("rating BETWEEN 0 AND 5", name="rating_range"),
        Index("ix_products_category", "category"),
        Index("ix_products_lowest_price", "lowest_price_paise"),
        Index("ix_products_rating", "rating"),
        Index("ix_products_discount", "discount_percent"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    brand: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(20))
    mrp: Mapped[int] = mapped_column("mrp_paise", Rupees)
    rating: Mapped[float] = mapped_column(Float)
    review_count: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    highlights: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    thumbnail_seed: Mapped[int] = mapped_column(Integer)
    sponsored_platform: Mapped[str | None] = mapped_column(String(20))

    lowest_price: Mapped[int] = mapped_column("lowest_price_paise", Rupees)
    highest_price: Mapped[int] = mapped_column("highest_price_paise", Rupees)
    discount_percent: Mapped[int] = mapped_column(SmallInteger)
    cheapest_platform: Mapped[str] = mapped_column(String(20))
    fastest_delivery_days: Mapped[int] = mapped_column(SmallInteger)

    prices: Mapped[list[ProductPrice]] = relationship(
        lazy="raise", cascade="all, delete-orphan", order_by="ProductPrice.platform"
    )


class ProductPrice(Base):
    __tablename__ = "product_prices"
    __table_args__ = (
        one_of("platform", SHOPPING_PLATFORMS),
        CheckConstraint("price_paise > 0", name="price_positive"),
    )

    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    platform: Mapped[str] = mapped_column(String(20), primary_key=True)
    price: Mapped[int] = mapped_column("price_paise", Rupees)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery_days: Mapped[int] = mapped_column(SmallInteger)
    sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    #: The price this platform returns to after a sale ends (used by the fluctuation job).
    base_price: Mapped[int] = mapped_column("base_price_paise", Rupees)


class PriceHistory(Base):
    """One row per product, platform and IST calendar day."""

    __tablename__ = "price_history"
    __table_args__ = (CheckConstraint("price_paise > 0", name="price_positive"),)

    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    platform: Mapped[str] = mapped_column(String(20), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    price: Mapped[int] = mapped_column("price_paise", Rupees)


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_price_alerts_user_product"),
        CheckConstraint("target_price_paise > 0", name="target_positive"),
        Index("ix_price_alerts_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    target_price: Mapped[int] = mapped_column("target_price_paise", Rupees)
    #: The price the last drop notification quoted, so the 6-hourly check never repeats itself.
    last_notified_price: Mapped[int | None] = mapped_column("last_notified_price_paise", Rupees)
    created_at: Mapped[datetime] = created_at_column()
