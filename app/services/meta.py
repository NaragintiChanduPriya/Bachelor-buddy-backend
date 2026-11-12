"""Reference data: areas and tech parks."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Area, TechPark
from app.schemas.meta import AreaOut, AreasResponse, TechParkOut


async def areas_and_parks(session: AsyncSession) -> AreasResponse:
    areas = list(await session.scalars(select(Area).order_by(Area.position, Area.name)))
    names = {a.id: a.name for a in areas}
    parks = await session.scalars(select(TechPark).order_by(TechPark.position, TechPark.name))
    return AreasResponse(
        areas=[
            AreaOut(id=a.id, name=a.name, lat=a.lat, lng=a.lng, popular=a.popular) for a in areas
        ],
        tech_parks=[
            TechParkOut(
                id=p.id,
                name=p.name,
                area_id=p.area_id,
                area_name=names.get(p.area_id, ""),
                lat=p.lat,
                lng=p.lng,
            )
            for p in parks
        ],
    )
