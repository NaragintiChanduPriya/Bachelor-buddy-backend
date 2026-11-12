"""Users, auth tokens, preferences and saved cards."""

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

from app.core.constants import FOOD_PREFERENCES
from app.db.base import Base
from app.db.models._common import created_at_column, one_of
from app.db.models.reference import Area, TechPark
from app.db.types import Rupees


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("age BETWEEN 16 AND 100", name="age_range"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(80))
    age: Mapped[int] = mapped_column(SmallInteger)
    occupation: Mapped[str] = mapped_column(String(80))
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Rows created by scripts/generate_data.py; a reseed deletes only these.
    is_seeded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()

    preferences: Mapped[UserPreferences | None] = relationship(
        back_populates="user", lazy="raise", cascade="all, delete-orphan", uselist=False
    )
    cards: Mapped[list[UserCard]] = relationship(
        lazy="raise", cascade="all, delete-orphan", order_by="UserCard.position"
    )


class RefreshToken(Base):
    """Opaque refresh tokens, stored as SHA-256 hashes and rotated on every use.

    Tokens issued from one login share a `family_id`. Presenting a token that was already
    rotated means it leaked, so the whole family is revoked.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_family", "family_id"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class UserPreferences(Base):
    """Filled in at onboarding. Until then the money fields are 0 and the places are null."""

    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint("salary_paise >= 0", name="salary_non_negative"),
        CheckConstraint("savings_goal_paise >= 0", name="goal_non_negative"),
        one_of("food_preference", FOOD_PREFERENCES),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    salary: Mapped[int] = mapped_column("salary_paise", Rupees, default=0)
    savings_goal: Mapped[int] = mapped_column("savings_goal_paise", Rupees, default=0)
    home_area_id: Mapped[str | None] = mapped_column(ForeignKey("areas.id"))
    office_area_id: Mapped[str | None] = mapped_column(ForeignKey("areas.id"))
    tech_park_id: Mapped[str | None] = mapped_column(ForeignKey("tech_parks.id"))
    food_preference: Mapped[str | None] = mapped_column(String(12))

    user: Mapped[User] = relationship(back_populates="preferences", lazy="raise")
    home_area: Mapped[Area | None] = relationship(foreign_keys=[home_area_id], lazy="raise")
    office_area: Mapped[Area | None] = relationship(foreign_keys=[office_area_id], lazy="raise")
    tech_park: Mapped[TechPark | None] = relationship(lazy="raise")


class UserCard(Base):
    __tablename__ = "user_cards"
    __table_args__ = (
        one_of("card_type", ("credit", "debit")),
        UniqueConstraint("user_id", "position", name="uq_user_cards_position"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    bank: Mapped[str] = mapped_column(String(40))
    card_type: Mapped[str] = mapped_column(String(10))
    label: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(SmallInteger)
