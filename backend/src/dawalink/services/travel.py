"""Travel times from a client's location to pharmacies (docs/04 R-RT, docs/06 §8 "Routing").

Two halves, kept apart on purpose:
- `travel_to` runs inside a transaction and never touches the network. It reads the
  24-hour cache and falls back to the straight-line estimate.
- `refresh` asks the routing service and fills the cache. It runs outside any
  transaction that holds locks, so a slow network never blocks a reservation.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as upsert

from dawalink.db.models import District, Pharmacy, TravelTimeCache
from dawalink.domain.geo import Point, Travel, cell, estimate, rounded
from dawalink.domain.numbers import AUTOMATIC_REACH_CAR_MIN, TRAVEL_CACHE_TTL
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

Mode = Literal["car", "walk"]


@dataclass(frozen=True)
class Location:
    """Where a client is, for one search, chat or request. Rounded; never sent to the LLM."""

    point: Point
    source: Literal["shared", "district"]
    district_id: int | None = None


class RoutingService(Protocol):
    """A road-time provider (OpenRouteService in production)."""

    def road_times(
        self, origin: Point, destinations: Mapping[uuid.UUID, Point], mode: Mode
    ) -> Mapping[uuid.UUID, tuple[int, float]]:
        """`{pharmacy: (minutes, km)}`. Raises on any failure or timeout (N-41)."""
        ...


def shared_location(lat: float | str, lon: float | str) -> Location:
    """The location a client shared from their phone, rounded to about 100 m (N-43)."""
    try:
        return Location(rounded(lat, lon), "shared")
    except (ValueError, ArithmeticError):
        raise ServiceError(Code.VALIDATION_ERROR, "That isn't a valid location.") from None


def district_location(tx: Tx, district_id: int) -> Location:
    """A district's reference point, for a client who picked a district (R-S2)."""
    district = tx.session.get(District, district_id)
    if district is None:
        raise ServiceError(Code.VALIDATION_ERROR, "Unknown district.")
    return Location(Point(district.ref_lat, district.ref_lon), "district", district_id)


def _pins(tx: Tx, pharmacy_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Point]:
    rows = tx.session.execute(
        select(Pharmacy.id, Pharmacy.lat, Pharmacy.lon).where(Pharmacy.id.in_(pharmacy_ids))
    )
    return {pharmacy_id: Point(lat, lon) for pharmacy_id, lat, lon in rows}


def travel_to(
    tx: Tx, origin: Location, pharmacy_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Travel]:
    """The travel time to each pharmacy: from the cache, or the straight-line estimate."""
    if not pharmacy_ids:
        return {}
    fresh = tx.session.execute(
        select(
            TravelTimeCache.pharmacy_id,
            TravelTimeCache.mode,
            TravelTimeCache.minutes,
            TravelTimeCache.km,
        ).where(
            TravelTimeCache.origin_cell == cell(origin.point),
            TravelTimeCache.pharmacy_id.in_(pharmacy_ids),
            TravelTimeCache.source == "road",
            TravelTimeCache.computed_at > tx.now - TRAVEL_CACHE_TTL,
        )
    ).all()
    cached: dict[uuid.UUID, dict[str, tuple[int, float]]] = {}
    for pharmacy_id, mode, minutes, km in fresh:
        cached.setdefault(pharmacy_id, {})[mode] = (minutes, float(km))

    result: dict[uuid.UUID, Travel] = {}
    for pharmacy_id, pin in _pins(tx, pharmacy_ids).items():
        modes = cached.get(pharmacy_id, {})
        if "car" in modes and "walk" in modes:
            result[pharmacy_id] = Travel(
                car_min=modes["car"][0],
                walk_min=modes["walk"][0],
                km=modes["car"][1],
                source="road",
            )
        else:
            result[pharmacy_id] = estimate(origin.point, pin)
    return result


def within_reach(travel: Travel) -> bool:
    """Close enough for automatic offers and early-release asks (R-RT3, N-23)."""
    return travel.car_min <= AUTOMATIC_REACH_CAR_MIN


def refresh(
    tx: Tx, routing: RoutingService, origin: Location, pharmacy_ids: Sequence[uuid.UUID]
) -> int:
    """Asks the routing service for the road times that aren't cached, and stores them.

    Call it in a short transaction of its own, before the one that needs the times. If the
    service fails, nothing is stored and the estimate is used: a failure never reaches the
    client (FX-18). Returns how many pharmacies got road times.
    """
    known = {
        pharmacy_id
        for pharmacy_id, travel in travel_to(tx, origin, pharmacy_ids).items()
        if travel.source == "road"
    }
    missing = {
        pharmacy_id: pin
        for pharmacy_id, pin in _pins(tx, pharmacy_ids).items()
        if pharmacy_id not in known
    }
    if not missing:
        return 0
    rows = []
    try:
        modes: tuple[Mode, Mode] = ("car", "walk")
        for mode in modes:
            for pharmacy_id, (minutes, km) in routing.road_times(
                origin.point, missing, mode
            ).items():
                rows.append(
                    {
                        "pharmacy_id": pharmacy_id,
                        "origin_cell": cell(origin.point),
                        "mode": mode,
                        "minutes": minutes,
                        "km": km,
                        "source": "road",
                        "computed_at": tx.now,
                    }
                )
    except Exception:
        return 0
    if not rows:
        return 0
    statement = upsert(TravelTimeCache).values(rows)
    tx.session.execute(
        statement.on_conflict_do_update(
            index_elements=["pharmacy_id", "origin_cell", "mode"],
            set_={
                column: statement.excluded[column]
                for column in ("minutes", "km", "source", "computed_at")
            },
        )
    )
    return len({row["pharmacy_id"] for row in rows})
