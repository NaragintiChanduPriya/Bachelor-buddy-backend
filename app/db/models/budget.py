"""Monthly budgets, their category limits, and expenses."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import CATEGORY_IDS, EXPENSE_SOURCES
from app.db.base import Base
from app.db.models._common import created_at_column, one_of
from app.db.types import Rupees

MONTH_CHECK = "~ '^[0-9]{4}-(0[1-9]|1[0-2])$'"


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "month", name="uq_budgets_user_month"),
        CheckConstraint(f"month {MONTH_CHECK}", name="month_format"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    month: Mapped[str] = mapped_column(String(7))
    #: The salary the limits were planned against.
    salary: Mapped[int] = mapped_column("salary_paise", Rupees)
    created_at: Mapped[datetime] = created_at_column()

    categories: Mapped[list[BudgetCategory]] = relationship(
        lazy="raise", cascade="all, delete-orphan", order_by="BudgetCategory.position"
    )


class BudgetCategory(Base):
    __tablename__ = "budget_categories"
    __table_args__ = (
        one_of("category", CATEGORY_IDS),
        CheckConstraint("limit_paise >= 0", name="limit_non_negative"),
    )

    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(12), primary_key=True)
    limit_amount: Mapped[int] = mapped_column("limit_paise", Rupees)
    position: Mapped[int] = mapped_column(Integer)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        one_of("category", CATEGORY_IDS),
        one_of("source", EXPENSE_SOURCES),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
        Index("ix_expenses_user_spent", "user_id", "spent_at"),
        Index("ix_expenses_user_category_spent", "user_id", "category", "spent_at"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(500))
    amount: Mapped[int] = mapped_column("amount_paise", Rupees)
    merchant: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(14), default="manual")
    spent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
