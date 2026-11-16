"""The simulated world's road travel times: python -m dawalink.sim.travel_table

Asked once from the routing service and kept in `eval/world/travel.json` (docs/08 §2.3),
so a simulation run makes no routing call: it is free and gives the same times every
time. The table holds, by car and on foot, the trip from every client point and from
every pharmacy to every pharmacy.

The points are the invented ones of `world.json`: nothing about a person is sent.
Road data © OpenStreetMap contributors; times computed by openrouteservice.org.
"""

import argparse
import json
import time
import uuid
from collections.abc import Iterator, Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dawalink.config import load_settings
from dawalink.domain.geo import Point, cell
from dawalink.routing import OpenRouteService
from dawalink.services.travel import MODES, RoutingService
from dawalink.sim.world import World, load

TRAVEL_FILE = Path("../eval/world/travel.json")
CREDIT = (
    "Travel times computed by openrouteservice.org; road data © OpenStreetMap contributors, "
    "available under the Open Database License (https://www.openstreetmap.org/copyright)."
)
# The hosted service allows 3,500 trips (origins x pharmacies) in one request, but a request
# that large across the whole country times out there. 25 x 30 is answered in seconds.
ORIGINS_PER_REQUEST = 25
PAUSE_S = 2.0
TIMEOUT_S = 60.0

# cell -> mode -> one [minutes, km] per pharmacy (in the map's order), or null with no road.
Table = dict[str, dict[str, list[list[float] | None]]]


def _point(lat: float, lon: float) -> Point:
    return Point(Decimal(str(lat)), Decimal(str(lon)))


def origins_of(world: World) -> dict[str, Point]:
    """Every place a trip can start from: the client points and the pharmacies."""
    places = [_point(c.lat, c.lon) for c in world.clients]
    places += [_point(p.lat, p.lon) for p in world.pharmacies]
    return {cell(place): place for place in places}


def _batches(origins: Mapping[str, Point], size: int) -> Iterator[dict[str, Point]]:
    keys = list(origins)
    for start in range(0, len(keys), size):
        yield {key: origins[key] for key in keys[start : start + size]}


def fetch(routing: RoutingService, world: World, *, pause_s: float = PAUSE_S) -> tuple[Table, int]:
    """Asks for every trip. Returns the table and how many requests it took."""
    pins = {pharmacy.id: _point(pharmacy.lat, pharmacy.lon) for pharmacy in world.pharmacies}
    table: Table = {}
    requests = 0
    for mode in MODES:
        for batch in _batches(origins_of(world), ORIGINS_PER_REQUEST):
            if requests:
                time.sleep(pause_s)
            answer = routing.road_times(batch, pins, mode)
            requests += 1
            for origin in batch:
                table.setdefault(origin, {})[mode] = [
                    list(answer[(origin, pharmacy_id)]) if (origin, pharmacy_id) in answer else None
                    for pharmacy_id in pins
                ]
    return table, requests


def write(path: Path, table: Table, *, fetched: date) -> None:
    content = {"credit": CREDIT, "fetched": fetched.isoformat(), "cells": table}
    path.write_text(
        json.dumps(content, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read(path: Path = TRAVEL_FILE) -> Table | None:
    """The table, or None when it hasn't been fetched: estimates are used then."""
    if not path.is_file():
        return None
    cells: Table = json.loads(path.read_text(encoding="utf-8"))["cells"]
    return cells


def cache_rows(table: Table, world: World, *, now: datetime) -> list[dict[str, Any]]:
    """The table as rows of the app's own travel-time cache, dated `now`.

    The cache keeps a time for 24 hours of the app's clock (N-43): a simulated day that
    starts at `now` finds every one of them fresh.
    """
    ids: list[uuid.UUID] = [pharmacy.id for pharmacy in world.pharmacies]
    own_cell = {
        pharmacy.id: cell(_point(pharmacy.lat, pharmacy.lon)) for pharmacy in world.pharmacies
    }
    rows = []
    for origin, by_mode in table.items():
        for mode, trips in by_mode.items():
            for pharmacy_id, trip in zip(ids, trips, strict=True):
                if trip is None or own_cell[pharmacy_id] == origin:
                    continue  # no road, or a pharmacy to itself
                rows.append(
                    {
                        "pharmacy_id": pharmacy_id,
                        "origin_cell": origin,
                        "mode": mode,
                        "minutes": int(trip[0]),
                        "km": trip[1],
                        "source": "road",
                        "computed_at": now,
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=TRAVEL_FILE)
    arguments = parser.parse_args()
    settings = load_settings()
    if settings.ors_api_key is None:
        raise SystemExit("ORS_API_KEY is not set: the routing service can't be asked.")
    world = load()
    routing = OpenRouteService(
        api_key=settings.ors_api_key.get_secret_value(),
        base_url=settings.ors_url,
        timeout_s=TIMEOUT_S,
    )
    table, requests = fetch(routing, world)
    write(arguments.file, table, fetched=date.today())
    trips = sum(len(trips) for by_mode in table.values() for trips in by_mode.values())
    without_road = sum(
        trip is None for by_mode in table.values() for trips in by_mode.values() for trip in trips
    )
    print(
        f"{requests} requests, {len(table)} starting points, {trips} trips, "
        f"{without_road} with no road"
    )


if __name__ == "__main__":
    main()
