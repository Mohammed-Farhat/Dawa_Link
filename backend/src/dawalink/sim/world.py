"""Putting the simulated world into a database (docs/08 §2.3).

The map (`eval/world/world.json`) is the same for every run. A run's **seed** decides the
stock on every shelf. Every draw comes from the seed and the thing it belongs to (this
pharmacy's shelf), never from one shared stream, so the three contenders of a seed start
from exactly the same world whatever they do afterwards.
"""

import json
import random
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Connection, insert, select

from dawalink.db.models import (
    ClientProfile,
    District,
    InventoryItem,
    Pharmacy,
    PharmacyHours,
    Product,
    TravelTimeCache,
    User,
)
from dawalink.domain.clock import beirut_date
from dawalink.sim.geometry import WORLD_FILE

NAMESPACE = uuid.UUID("6f0e0d8a-51a1-4c0e-9f0b-0f5d1c0a51b0")
NO_PASSWORD = "!"  # no one logs in to a simulated account
ALL_WEEK = range(7)
MONDAY_TO_SATURDAY = range(6)
# Opening hours as (days, [(opens, closes)]) in minutes after midnight.
SCHEDULES: tuple[tuple[range, tuple[tuple[int, int], ...]], ...] = (
    (MONDAY_TO_SATURDAY, ((8 * 60, 21 * 60),)),
    (MONDAY_TO_SATURDAY, ((8 * 60, 13 * 60), (16 * 60, 20 * 60))),
    (ALL_WEEK, ((8 * 60, 22 * 60),)),
    (ALL_WEEK, ((0, 24 * 60),)),
    (MONDAY_TO_SATURDAY, ((9 * 60, 17 * 60),)),  # closes early
)
DEMAND_SIZE = 300  # the medicines people ask for (docs/08 §2.3)
DEMAND_WITH_OTHER_BRANDS = 240
ITEMS_PER_PHARMACY = 45
# Days until expiry and their share of a shelf: published, early-release zone, private.
EXPIRY_ZONES = (((3, 180), 55), ((181, 270), 25), ((271, 500), 20))
MAX_UNITS = 6
ROWS_AT_A_TIME = 2_000

Free = Literal["any", "after_18", "before_14"]


@dataclass(frozen=True)
class SimPharmacy:
    n: int
    district: str
    lat: float
    lon: float
    schedule: int
    pickup_days: int

    @property
    def id(self) -> uuid.UUID:
        return uuid.uuid5(NAMESPACE, f"pharmacy-{self.n}")

    @property
    def owner_id(self) -> uuid.UUID:
        return uuid.uuid5(NAMESPACE, f"pharmacist-{self.n}")

    @property
    def name(self) -> str:
        return f"{self.district} Pharmacy {self.n}"


@dataclass(frozen=True)
class SimClient:
    n: int
    district: str
    lat: float
    lon: float
    # The hidden situation: what the client knows and may or may not say.
    has_car: bool
    free: Free
    language: str
    preference: str | None

    @property
    def id(self) -> uuid.UUID:
        return uuid.uuid5(NAMESPACE, f"client-{self.n}")


@dataclass(frozen=True)
class World:
    pharmacies: tuple[SimPharmacy, ...]
    clients: tuple[SimClient, ...]


@dataclass(frozen=True)
class Populated:
    """What a run needs to know about the world it was given."""

    # The medicines people ask for, the most asked first.
    demand: tuple[uuid.UUID, ...]
    inventory_items: int
    # Road times put in the app's cache. 0 means every trip is a straight-line estimate.
    road_times: int = 0


def load(path: Path = WORLD_FILE) -> World:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    keep = ("n", "district", "lat", "lon")
    return World(
        tuple(
            SimPharmacy(**{k: p[k] for k in (*keep, "schedule", "pickup_days")})
            for p in data["pharmacies"]
        ),
        tuple(
            SimClient(**{k: c[k] for k in (*keep, "has_car", "free", "language", "preference")})
            for c in data["clients"]
        ),
    )


def numbers_for(seed: int, *what: object) -> random.Random:
    """The random stream of one thing in one run: the same whoever asks, in any order."""
    return random.Random(f"{seed}|" + "|".join(str(part) for part in what))


def demand_set(connection: Connection) -> tuple[uuid.UUID, ...]:
    """The medicines people ask for: the same for every seed, most asked first.

    Mostly medicines that have another brand, as in real demand, and never a controlled one.
    """
    rows = connection.execute(
        select(Product.id, Product.equivalence_key)
        .where(Product.controlled.is_(False))
        .order_by(Product.moph_code)
    ).all()
    group_size: dict[str, int] = {}
    for _, key in rows:
        if key:
            group_size[key] = group_size.get(key, 0) + 1
    with_brands = [pid for pid, key in rows if key and group_size[key] >= 2]
    alone = [pid for pid, key in rows if not (key and group_size[key] >= 2)]
    numbers = random.Random("demand")
    numbers.shuffle(with_brands)
    numbers.shuffle(alone)
    chosen = (
        with_brands[:DEMAND_WITH_OTHER_BRANDS] + alone[: DEMAND_SIZE - DEMAND_WITH_OTHER_BRANDS]
    )
    numbers.shuffle(chosen)
    return tuple(chosen)


def popularity(count: int) -> list[float]:
    """A few medicines are asked for much more than the rest."""
    return [1 / (rank + 5) for rank in range(count)]


def _expiry_in_days(numbers: random.Random, early_release_share: float) -> int:
    """How far from expiry a box is. The early-release zone takes its share; the published
    and the private zones keep their proportion in what is left."""
    zones = [zone for zone, _ in EXPIRY_ZONES]
    weights: list[float] = [share for _, share in EXPIRY_ZONES]
    if early_release_share != weights[1] / 100:
        rest = 100 * (1 - early_release_share)
        weights = [rest * weights[0] / 75, 100 * early_release_share, rest * weights[2] / 75]
    (low, high) = numbers.choices(zones, weights)[0]
    return numbers.randrange(low, high + 1)


def shelf(
    pharmacy: SimPharmacy,
    demand: tuple[uuid.UUID, ...],
    *,
    seed: int,
    now: datetime,
    early_release_share: float = 0.25,
) -> list[dict[str, Any]]:
    """One pharmacy's stock for this seed."""
    numbers = numbers_for(seed, "shelf", pharmacy.n)
    today = beirut_date(now)
    weights = popularity(len(demand))
    products: dict[uuid.UUID, None] = {}
    while len(products) < min(ITEMS_PER_PHARMACY, len(demand)):
        products.setdefault(numbers.choices(demand, weights)[0])
    usual = EXPIRY_ZONES[1][1] / 100
    items = []
    for position, product_id in enumerate(products):
        # Always drawn, so the rest of the shelf is the same whatever the share is.
        days = _expiry_in_days(numbers, usual)
        if early_release_share != usual:
            # Another share: the dates come from a stream of their own.
            dates = numbers_for(seed, "expiry", pharmacy.n, position)
            days = _expiry_in_days(dates, early_release_share)
        items.append(
            {
                "id": uuid.uuid5(NAMESPACE, f"{seed}-item-{pharmacy.n}-{position}"),
                "pharmacy_id": pharmacy.id,
                "product_id": product_id,
                "batch": f"S{seed}-{pharmacy.n}-{position}",
                "expiry_date": today + timedelta(days=days),
                "qty_on_hand": numbers.randrange(1, MAX_UNITS + 1),
                "last_edited_at": now,
            }
        )
    return items


def populate(
    connection: Connection,
    world: World,
    *,
    seed: int,
    now: datetime,
    road_times: Sequence[Mapping[str, Any]] = (),
    stock: bool = True,
    early_release_share: float = 0.25,
) -> Populated:
    """Adds the pharmacies, the clients and this seed's stock, in the caller's transaction.

    `road_times` are rows for the app's travel-time cache (`travel_table.cache_rows`).
    With `stock=False` the shelves stay empty: a test then fills them by hand.
    Run with the migrator login, like the demo seed: it writes accounts without passwords.
    """
    districts = {
        name: district_id
        for district_id, name in connection.execute(select(District.id, District.name))
    }
    users: list[dict[str, Any]] = []
    pharmacies: list[dict[str, Any]] = []
    hours: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    for pharmacy in world.pharmacies:
        users.append(
            {
                "id": pharmacy.owner_id,
                "email": f"pharmacy{pharmacy.n:03d}@sim.dawalink.test",
                "password_hash": NO_PASSWORD,
                "role": "pharmacist",
                "full_name": f"Sim Pharmacist {pharmacy.n:03d}",
                "email_verified_at": now,
            }
        )
        pharmacies.append(
            {
                "id": pharmacy.id,
                "owner_user_id": pharmacy.owner_id,
                "name": pharmacy.name,
                "address": f"{pharmacy.n} Simulation Street, {pharmacy.district}",
                "license_number": f"SIM-{pharmacy.n:04d}",
                "phone": f"+961 00 100 {pharmacy.n:03d}",
                "district_id": districts[pharmacy.district],
                "lat": Decimal(str(pharmacy.lat)),
                "lon": Decimal(str(pharmacy.lon)),
                "pickup_days": pharmacy.pickup_days,
                "status": "APPROVED",
                "approved_at": now,
            }
        )
        days, ranges = SCHEDULES[pharmacy.schedule]
        hours.extend(
            {
                "pharmacy_id": pharmacy.id,
                "weekday": weekday,
                "seq": seq,
                "open_minute": opens,
                "close_minute": closes,
            }
            for weekday in days
            for seq, (opens, closes) in enumerate(ranges, start=1)
        )
    for client in world.clients:
        users.append(
            {
                "id": client.id,
                "email": f"client{client.n:03d}@sim.dawalink.test",
                "password_hash": NO_PASSWORD,
                "role": "client",
                "full_name": f"Sim Client {client.n:03d}",
                "email_verified_at": now,
            }
        )
        profiles.append(
            {"user_id": client.id, "status": "ACTIVE", "district_id": districts[client.district]}
        )
    connection.execute(insert(User), users)
    connection.execute(insert(Pharmacy), pharmacies)
    connection.execute(insert(PharmacyHours), hours)
    connection.execute(insert(ClientProfile), profiles)

    demand = demand_set(connection)
    items = [
        item
        for pharmacy in (world.pharmacies if stock else ())
        for item in shelf(
            pharmacy, demand, seed=seed, now=now, early_release_share=early_release_share
        )
    ]
    if items:
        connection.execute(insert(InventoryItem), items)
    for start in range(0, len(road_times), ROWS_AT_A_TIME):
        connection.execute(
            insert(TravelTimeCache), list(road_times[start : start + ROWS_AT_A_TIME])
        )
    return Populated(demand, len(items), len(road_times))
