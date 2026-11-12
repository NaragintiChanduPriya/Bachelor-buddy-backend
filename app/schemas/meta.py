from __future__ import annotations

from app.schemas.common import CamelModel


class AreaOut(CamelModel):
    id: str
    name: str
    lat: float
    lng: float
    popular: bool


class TechParkOut(CamelModel):
    id: str
    name: str
    area_id: str
    area_name: str
    lat: float
    lng: float


class AreasResponse(CamelModel):
    areas: list[AreaOut]
    tech_parks: list[TechParkOut]
