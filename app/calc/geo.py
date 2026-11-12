"""Distances and commute times."""

from __future__ import annotations

import math

from app.core.money import js_round

EARTH_RADIUS_KM = 6371.0
#: Roads are not straight lines; about 1.35x the crow-flies distance is typical in Bangalore.
ROAD_FACTOR = 1.35
#: Food distances never show below this (a place next door is still a short walk).
MIN_DISTANCE_KM = 0.3


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance in km, rounded to one decimal."""
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    h = math.sin(d_lat / 2) ** 2 + math.sin(d_lng / 2) ** 2 * math.cos(
        math.radians(lat1)
    ) * math.cos(math.radians(lat2))
    return js_round(2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h)) * 10) / 10


def walking_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return max(MIN_DISTANCE_KM, haversine_km(lat1, lng1, lat2, lng2))


def bike_minutes(km: float) -> int:
    """Bangalore traffic is slow; these keep commute numbers believable."""
    return max(5, js_round(km * 3.2))


def bus_minutes(km: float) -> int:
    return max(10, js_round(km * 5.5))
