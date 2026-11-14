"""Travel times from a client's location to pharmacies (docs/04 R-RT, docs/06 §8 "Routing").

Two halves, kept apart on purpose:
- `travel_to` and `legs` run inside a transaction and never touch the network. They read
  the 24-hour cache and fall back to the straight-line estimate.
- asking the routing service happens outside any transaction: `missing` says what to
  ask for, `fetch` asks, `store` keeps the answer. So a slow network never holds a
  database connection, let alone a lock.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as upsert

from dawalink.db.models import District, Pharmacy, TravelTimeCache
from dawalink.domain.geo import Point, Travel, cell, estimate, rounded
from dawalink.domain.numbers import AUTOMATIC_REACH_CAR_MIN, TRAVEL_CACHE_TTL
from dawalink.domain.planning import CLIENT, Leg
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

log = structlog.get_logger(__name__)

Mode = Literal["car", "walk"]
MODES: tuple[Mode, Mode] = ("car", "walk")


@dataclass(frozen=True)
class Location:
    """Where a client is, for one search, chat or request. Rounded; never sent to the LLM."""

    point: Point
    source: Literal["shared", "district"]
    district_id: int | None = None


class RoutingService(Protocol):
    """A road-time provider (OpenRouteService in production)."""

    def road_times(
        self, origins: Mapping[str, Point], destinations: Mapping[uuid.UUID, Point], mode: Mode
    ) -> Mapping[tuple[str, uuid.UUID], tuple[int, float]]:
        """`{(origin key, pharmacy): (minutes, km)}` for every pair it could route.

        One call for all the pairs. Raises on any failure or timeout (N-41).
        """
        ...


@dataclass(frozen=True)
class Wanted:
    """The road times that aren't cached yet: what to ask the routing service for."""

    origins: Mapping[str, Point]  # by cache cell
    destinations: Mapping[uuid.UUID, Point]

    def __bool__(self) -> bool:
        return bool(self.origins and self.destinations)


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


def _cached(
    tx: Tx, cells: Sequence[str], pharmacy_ids: Sequence[uuid.UUID]
) -> dict[tuple[str, uuid.UUID], dict[str, tuple[int, float]]]:
    """Fresh road times, by (origin cell, pharmacy), then by mode."""
    rows = tx.session.execute(
        select(
            TravelTimeCache.origin_cell,
            TravelTimeCache.pharmacy_id,
            TravelTimeCache.mode,
            TravelTimeCache.minutes,
            TravelTimeCache.km,
        ).where(
            TravelTimeCache.origin_cell.in_(cells),
            TravelTimeCache.pharmacy_id.in_(pharmacy_ids),
            TravelTimeCache.source == "road",
            TravelTimeCache.computed_at > tx.now - TRAVEL_CACHE_TTL,
        )
    ).all()
    found: dict[tuple[str, uuid.UUID], dict[str, tuple[int, float]]] = {}
    for origin_cell, pharmacy_id, mode, minutes, km in rows:
        found.setdefault((origin_cell, pharmacy_id), {})[mode] = (minutes, float(km))
    return found


def _between(origin: Point, pin: Point, modes: Mapping[str, tuple[int, float]] | None) -> Travel:
    """The road time when both modes are cached; otherwise the straight-line estimate."""
    if modes and "car" in modes and "walk" in modes:
        return Travel(
            car_min=modes["car"][0], walk_min=modes["walk"][0], km=modes["car"][1], source="road"
        )
    return estimate(origin, pin)


def travel_to(
    tx: Tx, origin: Location, pharmacy_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Travel]:
    """The travel time to each pharmacy: from the cache, or the straight-line estimate."""
    if not pharmacy_ids:
        return {}
    here = cell(origin.point)
    cached = _cached(tx, [here], pharmacy_ids)
    return {
        pharmacy_id: _between(origin.point, pin, cached.get((here, pharmacy_id)))
        for pharmacy_id, pin in _pins(tx, pharmacy_ids).items()
    }


def legs(tx: Tx, origin: Location, pharmacy_ids: Sequence[uuid.UUID]) -> dict[tuple[str, str], Leg]:
    """Every leg a multi-pharmacy plan can use: client to pharmacy, and pharmacy to pharmacy.

    The keys are what the planner expects: `CLIENT` and the pharmacies' IDs as text (R-RT2).
    """
    pins = _pins(tx, pharmacy_ids)
    cells = {cell(origin.point): CLIENT} | {cell(pin): str(pid) for pid, pin in pins.items()}
    points = {CLIENT: origin.point} | {str(pid): pin for pid, pin in pins.items()}
    cached = _cached(tx, list(cells), list(pins))
    result: dict[tuple[str, str], Leg] = {}
    for origin_cell, start in cells.items():
        for pharmacy_id, pin in pins.items():
            if start == str(pharmacy_id):
                continue
            way = _between(points[start], pin, cached.get((origin_cell, pharmacy_id)))
            result[(start, str(pharmacy_id))] = Leg(way.car_min, way.walk_min, way.source)
    return result


def within_reach(travel: Travel) -> bool:
    """Close enough for automatic offers and early-release asks (R-RT3, N-23)."""
    return travel.car_min <= AUTOMATIC_REACH_CAR_MIN


# --- Asking the routing service -------------------------------------------------------


def missing(
    tx: Tx, origin: Location, pharmacy_ids: Sequence[uuid.UUID], *, between: bool = False
) -> Wanted:
    """What isn't cached: from the client to these pharmacies and, with `between`, from
    each of them to the others (a plan with several stops needs those)."""
    pins = _pins(tx, pharmacy_ids)
    origins = {cell(origin.point): origin.point}
    if between and len(pins) > 1:
        origins |= {cell(pin): pin for pin in pins.values()}
    cached = _cached(tx, list(origins), list(pins))
    needed_origins: dict[str, Point] = {}
    needed_pins: dict[uuid.UUID, Point] = {}
    for origin_cell, point in origins.items():
        for pharmacy_id, pin in pins.items():
            if cell(pin) == origin_cell:
                continue  # a pharmacy to itself
            modes = cached.get((origin_cell, pharmacy_id), {})
            if "car" not in modes or "walk" not in modes:
                needed_origins[origin_cell] = point
                needed_pins[pharmacy_id] = pin
    return Wanted(needed_origins, needed_pins)


def fetch(routing: RoutingService, wanted: Wanted) -> list[dict[str, Any]]:
    """Asks the routing service, outside any transaction. A failure gives nothing back:
    the estimate is used, and a failure never reaches the client (FX-18)."""
    if not wanted:
        return []
    rows: list[dict[str, Any]] = []
    try:
        for mode in MODES:
            for (origin_cell, pharmacy_id), (minutes, km) in routing.road_times(
                wanted.origins, wanted.destinations, mode
            ).items():
                rows.append(
                    {
                        "pharmacy_id": pharmacy_id,
                        "origin_cell": origin_cell,
                        "mode": mode,
                        "minutes": minutes,
                        "km": km,
                        "source": "road",
                    }
                )
    except Exception as error:
        # The message may quote the request, which holds a location: only its type is logged.
        log.warning("routing_failed", error=type(error).__name__)
        return []
    return rows


def store(tx: Tx, rows: Sequence[Mapping[str, Any]]) -> int:
    """Keeps road times for a day (N-43). Returns how many pharmacies got some."""
    if not rows:
        return 0
    stamped = [{**row, "computed_at": tx.now} for row in rows]
    statement = upsert(TravelTimeCache).values(stamped)
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


def refresh(
    tx: Tx, routing: RoutingService, origin: Location, pharmacy_ids: Sequence[uuid.UUID]
) -> int:
    """`missing`, `fetch` and `store` in one go, for callers that hold no locks.

    A turn of the agent uses the three steps apart, so that no transaction is open while
    the routing service answers.
    """
    return store(tx, fetch(routing, missing(tx, origin, pharmacy_ids)))
