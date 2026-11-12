"""Bank card offers, coupons and cashback. User- and clock-dependent fields are derived on read."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._common import one_of
from app.db.types import Rupees


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        one_of("kind", ("card", "coupon", "cashback")),
        one_of("platform_category", ("shopping", "food", "groceries")),
        CheckConstraint("card_type IS NULL OR card_type IN ('credit', 'debit')", name="card_type"),
        CheckConstraint(
            "(discount_percent IS NULL) <> (flat_discount_paise IS NULL)",
            name="exactly_one_discount",
        ),
        CheckConstraint(
            "discount_percent IS NULL OR discount_percent BETWEEN 1 AND 100",
            name="percent_range",
        ),
        CheckConstraint("min_order_value_paise >= 0", name="min_order_non_negative"),
        CheckConstraint("valid_till > valid_from", name="valid_window"),
        Index("ix_offers_valid_till", "valid_till"),
        Index("ix_offers_platform", "platform"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(String(40))
    platform_category: Mapped[str] = mapped_column(String(12))
    bank: Mapped[str | None] = mapped_column(String(40))
    card_type: Mapped[str | None] = mapped_column(String(10))
    code: Mapped[str | None] = mapped_column(String(30))
    discount_percent: Mapped[int | None] = mapped_column(SmallInteger)
    flat_discount: Mapped[int | None] = mapped_column("flat_discount_paise", Rupees)
    max_discount: Mapped[int | None] = mapped_column("max_discount_paise", Rupees)
    min_order_value: Mapped[int] = mapped_column("min_order_value_paise", Rupees)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_till: Mapped[datetime] = mapped_column(DateTime(timezone=True))
