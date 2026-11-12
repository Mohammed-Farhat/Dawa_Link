"""Synthetic pharmacies, stock and clients for the demo: python -m dawalink.ops.seed_demo

Everything is invented, and the same seed always gives the same data (docs/05 §9).
The accounts can't log in yet: their passwords are set when logins are built (build step 7).
"""

import argparse
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import Connection, create_engine, func, insert, select

from dawalink.config import load_settings, required
from dawalink.db.models import (
    ClientProfile,
    District,
    InventoryItem,
    Pharmacy,
    PharmacyHours,
    Product,
    User,
)
from dawalink.domain.clock import SystemClock, beirut_date
from dawalink.observability.logging import configure_logging

log = structlog.get_logger(__name__)

DEFAULT_SEED = 42
# No password hash has this shape, so these accounts can't log in until one is set.
NO_PASSWORD = "!"
# (district, how many pharmacies): most of them where most clients are.
PHARMACIES_PER_DISTRICT = (
    ("Beirut", 5),
    ("Matn", 3),
    ("Baabda", 2),
    ("Tripoli", 2),
    ("Sidon", 2),
    ("Zahle", 1),
    ("Keserwan", 1),
)
CLIENT_DISTRICTS = ("Beirut", "Beirut", "Matn", "Baabda", "Tripoli", "Sidon")
ITEMS_PER_PHARMACY = 60
ALL_WEEK = range(7)
MONDAY_TO_SATURDAY = range(6)
# Opening hours as (days, [(opens, closes)]) in minutes after midnight.
SCHEDULES: tuple[tuple[range, tuple[tuple[int, int], ...]], ...] = (
    (MONDAY_TO_SATURDAY, ((8 * 60, 21 * 60),)),
    (MONDAY_TO_SATURDAY, ((8 * 60, 13 * 60), (16 * 60, 20 * 60))),
    (ALL_WEEK, ((8 * 60, 22 * 60),)),
    (ALL_WEEK, ((0, 24 * 60),)),
)
# Days until expiry: mostly inside the published window, some early-release, some private.
EXPIRY_RANGES = ((3, 30), (31, 90), (91, 180), (91, 180), (181, 270), (271, 500))


@dataclass(frozen=True)
class SeedResult:
    pharmacies: int
    clients: int
    inventory_items: int


def _uuid(numbers: random.Random) -> uuid.UUID:
    return uuid.UUID(int=numbers.getrandbits(128), version=4)


def _products_to_stock(connection: Connection, numbers: random.Random) -> list[uuid.UUID]:
    """Products that pharmacies will hold: mostly ones that have equivalents elsewhere."""
    rows = connection.execute(
        select(Product.id, Product.equivalence_key)
        .where(Product.controlled.is_(False))
        .order_by(Product.moph_code)
    ).all()
    group_size: dict[str, int] = {}
    for _, key in rows:
        if key:
            group_size[key] = group_size.get(key, 0) + 1
    with_equivalents = [pid for pid, key in rows if key and group_size[key] >= 3]
    others = [pid for pid, key in rows if not (key and group_size[key] >= 3)]
    numbers.shuffle(with_equivalents)
    numbers.shuffle(others)
    return with_equivalents[:400] + others[:100]


def seed_demo(connection: Connection, *, seed: int, now: datetime) -> SeedResult:
    """Adds the demo data inside the caller's transaction. `now` comes from the app clock."""
    today = beirut_date(now)
    numbers = random.Random(seed)
    districts = {
        name: (district_id, lat, lon)
        for district_id, name, lat, lon in connection.execute(
            select(District.id, District.name, District.ref_lat, District.ref_lon)
        )
    }
    users: list[dict[str, Any]] = []
    pharmacies: list[dict[str, Any]] = []
    hours: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []

    number = 0
    for district, count in PHARMACIES_PER_DISTRICT:
        district_id, lat, lon = districts[district]
        for letter in "ABCDE"[:count]:
            number += 1
            user_id, pharmacy_id = _uuid(numbers), _uuid(numbers)
            users.append(
                {
                    "id": user_id,
                    "email": f"pharmacy{number:02d}@demo.dawalink.test",
                    "password_hash": NO_PASSWORD,
                    "role": "pharmacist",
                    "full_name": f"Demo Pharmacist {number:02d}",
                    "email_verified_at": now,
                }
            )
            pharmacies.append(
                {
                    "id": pharmacy_id,
                    "owner_user_id": user_id,
                    "name": f"{district} Pharmacy {letter} (demo)",
                    "address": f"{number} Demo Street, {district}",
                    "license_number": f"DEMO-{number:04d}",
                    "phone": f"+961 00 000 {number:03d}",
                    "district_id": district_id,
                    # Within about 1.5 km of the district's reference point.
                    "lat": lat + Decimal(numbers.randrange(-150, 151)) / Decimal(10_000),
                    "lon": lon + Decimal(numbers.randrange(-150, 151)) / Decimal(10_000),
                    "pickup_days": numbers.choice((1, 1, 2, 3)),
                    "status": "APPROVED",
                    "approved_at": now,
                }
            )
            days, ranges = SCHEDULES[number % len(SCHEDULES)]
            hours.extend(
                {
                    "pharmacy_id": pharmacy_id,
                    "weekday": weekday,
                    "seq": seq,
                    "open_minute": opens,
                    "close_minute": closes,
                }
                for weekday in days
                for seq, (opens, closes) in enumerate(ranges, start=1)
            )

    for index, district in enumerate(CLIENT_DISTRICTS, start=1):
        user_id = _uuid(numbers)
        users.append(
            {
                "id": user_id,
                "email": f"client{index:02d}@demo.dawalink.test",
                "password_hash": NO_PASSWORD,
                "role": "client",
                "full_name": f"Demo Client {index:02d}",
                "email_verified_at": now,
            }
        )
        profiles.append(
            {"user_id": user_id, "status": "ACTIVE", "district_id": districts[district][0]}
        )

    connection.execute(insert(User), users)
    connection.execute(insert(Pharmacy), pharmacies)
    connection.execute(insert(PharmacyHours), hours)
    connection.execute(insert(ClientProfile), profiles)

    products = _products_to_stock(connection, numbers)
    items: list[dict[str, Any]] = []
    if products:
        for pharmacy in pharmacies:
            for product_id in numbers.sample(products, min(ITEMS_PER_PHARMACY, len(products))):
                low, high = numbers.choice(EXPIRY_RANGES)
                items.append(
                    {
                        "id": _uuid(numbers),
                        "pharmacy_id": pharmacy["id"],
                        "product_id": product_id,
                        "batch": f"B{numbers.randrange(10_000, 100_000)}",
                        "expiry_date": today + timedelta(days=numbers.randrange(low, high + 1)),
                        "qty_on_hand": numbers.randrange(1, 13),
                        "last_edited_at": now,
                    }
                )
        connection.execute(insert(InventoryItem), items)
    return SeedResult(len(pharmacies), len(profiles), len(items))


def has_pharmacies(connection: Connection) -> bool:
    return bool(connection.execute(select(func.count()).select_from(Pharmacy)).scalar_one())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    arguments = parser.parse_args()
    settings = load_settings()
    configure_logging(settings.log_level)
    (migrator_url,) = required(settings, "database_migrator_url")
    engine = create_engine(migrator_url)
    try:
        with engine.begin() as connection:
            if has_pharmacies(connection):
                log.info("demo_seed_skipped", reason="pharmacies already exist")
                return
            result = seed_demo(connection, seed=arguments.seed, now=SystemClock().now())
        log.info(
            "demo_seeded",
            pharmacies=result.pharmacies,
            clients=result.clients,
            inventory_items=result.inventory_items,
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
