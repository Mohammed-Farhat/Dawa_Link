"""Makes the simulated world's map once: python -m dawalink.sim.geometry

30 pharmacies and 200 client points in 8 districts, written to `eval/world/world.json`
(docs/08 §2.3). The places are fixed for every seed, because road travel times between
them are computed once and stored next to this file. A run's seed decides everything
else: the stock, who asks for what and when, and how people behave.

Every point is a town or neighbourhood of our own list of areas (`data/areas*.csv`,
whose centres are © OpenStreetMap contributors), moved by up to about 300 m, so that it
is a place where people live and near a road. Nobody real lives or works at these points.
"""

import argparse
import json
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

from dawalink.db.reference import AREAS_FILE, OSM_AREAS_FILE, read_areas

WORLD_FILE = Path("../eval/world/world.json")
MAP_SEED = 0
# district, pharmacies, client points: more of both where more people live.
DISTRICTS = (
    ("Beirut", 7, 50),
    ("Matn", 5, 35),
    ("Baabda", 5, 35),
    ("Aley", 2, 12),
    ("Keserwan", 3, 20),
    ("Tripoli", 3, 20),
    ("Zahle", 2, 12),
    ("Sidon", 3, 16),
)
# Opening hours, as an index into `world.SCHEDULES`; some close early, some on Sunday.
SCHEDULE_WEIGHTS = ((0, 4), (1, 2), (2, 3), (3, 1), (4, 2))
PICKUP_DAYS = (1, 1, 2, 3)
# What a client doesn't always say (docs/08 §2.3): the "hidden situation".
HAS_CAR = 0.65
FREE = (("any", 50), ("after_18", 30), ("before_14", 20))
LANGUAGES = (("arabizi", 40), ("arabic", 25), ("english", 25), ("mixed", 10))
PREFERENCES = ((None, 55), ("cheapest", 20), ("nearest", 15), ("fewest_trips", 10))
PHARMACY_JITTER = 0.002  # about 200 m
CLIENT_JITTER = 0.003


def _weighted[T](numbers: random.Random, choices: tuple[tuple[T, int], ...]) -> T:
    return numbers.choices([value for value, _ in choices], [weight for _, weight in choices])[0]


def _moved(numbers: random.Random, value: Decimal, by: float, digits: int) -> float:
    return round(float(value) + numbers.uniform(-by, by), digits)


def make(seed: int = MAP_SEED) -> dict[str, Any]:
    """The map as plain data. The same seed gives the same map."""
    numbers = random.Random(seed)
    places: dict[str, list[dict[str, object]]] = {}
    for path in (AREAS_FILE, OSM_AREAS_FILE):
        for area in read_areas(path):
            if not area["whole_district"]:
                places.setdefault(str(area["district"]), []).append(area)

    pharmacies: list[dict[str, Any]] = []
    clients: list[dict[str, Any]] = []
    for district, pharmacy_count, client_count in DISTRICTS:
        here = sorted(places[district], key=lambda area: int(str(area["id"])))
        for place in numbers.sample(here, pharmacy_count):
            number = len(pharmacies) + 1
            pharmacies.append(
                {
                    "n": number,
                    "district": district,
                    "near": place["name"],
                    "lat": _moved(numbers, place["ref_lat"], PHARMACY_JITTER, 5),  # type: ignore[arg-type]
                    "lon": _moved(numbers, place["ref_lon"], PHARMACY_JITTER, 5),  # type: ignore[arg-type]
                    "schedule": _weighted(numbers, SCHEDULE_WEIGHTS),
                    "pickup_days": numbers.choice(PICKUP_DAYS),
                }
            )
        for _ in range(client_count):
            place = numbers.choice(here)
            clients.append(
                {
                    "n": len(clients) + 1,
                    "district": district,
                    "near": place["name"],
                    # A client's location is used rounded to about 100 m (N-43).
                    "lat": _moved(numbers, place["ref_lat"], CLIENT_JITTER, 3),  # type: ignore[arg-type]
                    "lon": _moved(numbers, place["ref_lon"], CLIENT_JITTER, 3),  # type: ignore[arg-type]
                    "has_car": numbers.random() < HAS_CAR,
                    "free": _weighted(numbers, FREE),
                    "language": _weighted(numbers, LANGUAGES),
                    "preference": _weighted(numbers, PREFERENCES),
                }
            )
    return {"version": 1, "map_seed": seed, "pharmacies": pharmacies, "clients": clients}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=WORLD_FILE)
    arguments = parser.parse_args()
    world = make()
    arguments.file.parent.mkdir(parents=True, exist_ok=True)
    arguments.file.write_text(
        json.dumps(world, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{len(world['pharmacies'])} pharmacies and {len(world['clients'])} client points")


if __name__ == "__main__":
    main()
