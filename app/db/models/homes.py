"""PGs, co-living spaces and shared flats, their commutes, and market rent averages."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import HOME_TYPES, SHARING_TYPES
from app.db.base import Base
from app.db.models._common import one_of
from app.db.models.reference import Area, TechPark
from app.db.types import Rupees


class Home(Base):
    __tablename__ = "homes"
    __table_args__ = (
        one_of("type", HOME_TYPES),
        one_of("sharing", SHARING_TYPES),
        CheckConstraint("rent_paise > 0", name="rent_positive"),
        CheckConstraint("deposit_paise >= 0", name="deposit_non_negative"),
        CheckConstraint("rating BETWEEN 0 AND 5", name="rating_range"),
        Index("ix_homes_area", "area_id"),
        Index("ix_homes_type", "type"),
        Index("ix_homes_rent", "rent_paise"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(12))
    area_id: Mapped[str] = mapped_column(ForeignKey("areas.id"))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    #: Per person per month (for a shared flat, one person's share).
    rent: Mapped[int] = mapped_column("rent_paise", Rupees)
    deposit: Mapped[int] = mapped_column("deposit_paise", Rupees)
    sharing: Mapped[str] = mapped_column(String(12))
    food_included: Mapped[bool] = mapped_column(Boolean)
    bachelor_friendly: Mapped[bool] = mapped_column(Boolean)
    rating: Mapped[float] = mapped_column(Float)
    review_count: Mapped[int] = mapped_column(Integer)
    thumbnail_seed: Mapped[int] = mapped_column(Integer)
    sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(String(200))
    amenities: Mapped[list[str]] = mapped_column(ARRAY(String(60)))
    food_details: Mapped[str | None] = mapped_column(Text)
    meals_per_day: Mapped[int | None] = mapped_column(SmallInteger)
    notice_period_days: Mapped[int] = mapped_column(SmallInteger)
    maintenance_included: Mapped[bool] = mapped_column(Boolean)
    available_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    area: Mapped[Area] = relationship(lazy="raise")
    commutes: Mapped[list[HomeCommute]] = relationship(
        lazy="raise", cascade="all, delete-orphan", order_by="HomeCommute.distance_km"
    )


class HomeCommute(Base):
    """Road distance and typical weekday travel time from a home to each tech park."""

    __tablename__ = "home_commutes"
    __table_args__ = (Index("ix_home_commutes_park_distance", "tech_park_id", "distance_km"),)

    home_id: Mapped[str] = mapped_column(
        ForeignKey("homes.id", ondelete="CASCADE"), primary_key=True
    )
    tech_park_id: Mapped[str] = mapped_column(
        ForeignKey("tech_parks.id", ondelete="CASCADE"), primary_key=True
    )
    distance_km: Mapped[float] = mapped_column(Float)
    bike_minutes: Mapped[int] = mapped_column(SmallInteger)
    bus_minutes: Mapped[int] = mapped_column(SmallInteger)

    tech_park: Mapped[TechPark] = relationship(lazy="raise")


class AreaRentAverage(Base):
    """Market reference rent per area and home type (not an average of our listings)."""

    __tablename__ = "area_rent_averages"
    __table_args__ = (one_of("home_type", HOME_TYPES),)

    area_id: Mapped[str] = mapped_column(
        ForeignKey("areas.id", ondelete="CASCADE"), primary_key=True
    )
    home_type: Mapped[str] = mapped_column(String(12), primary_key=True)
    average_rent: Mapped[int] = mapped_column("average_rent_paise", Rupees)
