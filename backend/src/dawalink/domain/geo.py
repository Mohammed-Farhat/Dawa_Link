"""Locations and the straight-line travel estimate (docs/04 R-S2, R-RT1, N-43, N-50).

A client's location is rounded to about 100 m before it is stored or used, and it never
reaches the LLM: tools hand out travel times and area names only (INV-24).
"""

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from dawalink.domain.numbers import (
    LOCATION_DECIMALS,
    STRAIGHT_LINE_CAR_KMH,
    STRAIGHT_LINE_ROAD_FACTOR,
    STRAIGHT_LINE_WALK_KMH,
)

EARTH_RADIUS_KM = 6371.0088
_STEP = Decimal(1).scaleb(-LOCATION_DECIMALS)


@dataclass(frozen=True)
class Point:
    lat: Decimal
    lon: Decimal

    def __post_init__(self) -> None:
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise ValueError("Not a place on Earth.")


@dataclass(frozen=True)
class Travel:
    """How far a pharmacy is. This, and never a coordinate, is what the agent sees (R-RT4)."""

    car_min: int
    walk_min: int
    km: float
    # "road" from the routing service; "straight" for the estimate, shown as "about".
    source: Literal["road", "straight"]


def rounded(lat: Decimal | float | str, lon: Decimal | float | str) -> Point:
    """A client's location, rounded to about 100 m (N-43)."""
    return Point(
        Decimal(str(lat)).quantize(_STEP, ROUND_HALF_EVEN),
        Decimal(str(lon)).quantize(_STEP, ROUND_HALF_EVEN),
    )


def cell(point: Point) -> str:
    """The rounded location as text: the key of the travel-time cache."""
    return f"{point.lat:.{LOCATION_DECIMALS}f},{point.lon:.{LOCATION_DECIMALS}f}"


def straight_line_km(a: Point, b: Point) -> float:
    lat_a, lat_b = math.radians(float(a.lat)), math.radians(float(b.lat))
    d_lat = lat_b - lat_a
    d_lon = math.radians(float(b.lon) - float(a.lon))
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def estimate(origin: Point, destination: Point) -> Travel:
    """The travel time when no road time is known: an estimate from the straight line."""
    road_km = straight_line_km(origin, destination) * STRAIGHT_LINE_ROAD_FACTOR
    return Travel(
        car_min=max(1, math.ceil(road_km / STRAIGHT_LINE_CAR_KMH * 60)),
        walk_min=max(1, math.ceil(road_km / STRAIGHT_LINE_WALK_KMH * 60)),
        km=round(road_km, 1),
        source="straight",
    )
