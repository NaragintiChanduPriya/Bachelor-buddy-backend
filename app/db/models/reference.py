"""Bangalore geography: areas and tech parks."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    popular: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(SmallInteger, default=0)


class TechPark(Base):
    __tablename__ = "tech_parks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    area_id: Mapped[str] = mapped_column(ForeignKey("areas.id"), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    position: Mapped[int] = mapped_column(SmallInteger, default=0)

    area: Mapped[Area] = relationship(lazy="raise")
