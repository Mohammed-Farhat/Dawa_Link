"""Synthetic pharmacies, stock and clients for the demo: python -m dawalink.ops.seed_demo

Everything is invented, and the same seed always gives the same data (docs/05 §9).
The accounts can log in only when `DEMO_ACCOUNTS_PASSWORD` is set: they all get that one
password (`set_demo_passwords`). Without it no password matches them.
"""

import argparse
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import Connection, create_engine, func, insert, select, update

from dawalink.config import load_settings, required
from dawalink.db.models import (
    Area,
    ClientProfile,
    District,
    InventoryItem,
    Pharmacy,
    PharmacyHours,
    Product,
    TravelTimeCache,
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
# Invented names, one per demo client. Real-looking on purpose: the agent's redaction is
# tried against names a person could have.
CLIENT_NAMES = (
    "Rami Haddad",
    "Maya Khoury",
    "Karim Saade",
    "Lina Mansour",
    "Ziad Nassar",
    "Hala Abboud",
)
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


# Two demo pharmacies of a district are at least this far apart, in degrees (about 800 m):
# near enough to be one town, far enough for travel times to differ.
_APART = Decimal("0.008")
DEMO_LICENCES = "DEMO-%"


def land_pins(
    connection: Connection, district_id: int, count: int
) -> list[tuple[Decimal, Decimal]]:
    """Where a district's demo pharmacies stand: the centres of its named towns and
    neighbourhoods, the nearest to the district's own centre first, about 800 m apart.

    A random point around the centre, as before, put pharmacies of a coastal town in the
    sea (the owner found Sidon's there on 2026-11-18, through [Directions]). A named
    place's centre is where people live. The same district always gets the same pins.
    """
    centre_lat, centre_lon = connection.execute(
        select(District.ref_lat, District.ref_lon).where(District.id == district_id)
    ).one()

    def far(point: tuple[Decimal, Decimal]) -> Decimal:
        return (point[0] - centre_lat) ** 2 + (point[1] - centre_lon) ** 2

    places = sorted(
        {
            (lat, lon)
            for lat, lon in connection.execute(
                select(Area.ref_lat, Area.ref_lon).where(
                    Area.district_id == district_id, Area.whole_district.is_(False)
                )
            )
        },
        key=lambda point: (far(point), point),
    )
    pins: list[tuple[Decimal, Decimal]] = []
    for place in places:
        if len(pins) == count:
            break
        if all(abs(place[0] - lat) >= _APART or abs(place[1] - lon) >= _APART for lat, lon in pins):
            pins.append(place)
    # A district with too few named places (the tests' small list): the rest go east of
    # its centre, which in Lebanon is away from the sea.
    step = 0
    while len(pins) < count:
        pins.append((centre_lat, centre_lon + _APART * step))
        step += 1
    return pins


def move_demo_pins_onto_land(connection: Connection, *, now: datetime) -> int:
    """Puts the demo pharmacies of a database seeded before 2026-11-18 where `land_pins`
    says. Safe to run again: a pharmacy already there is left alone. Returns how many
    moved. The road times counted to an old pin are made stale, as when a pharmacy moves
    its own pin (`services/pharmacy_profile.py`)."""
    moved = 0
    districts = dict(connection.execute(select(District.name, District.id)).all())
    for district, count in PHARMACIES_PER_DISTRICT:
        if district not in districts:
            continue
        demo = connection.execute(
            select(Pharmacy.id, Pharmacy.lat, Pharmacy.lon)
            .where(
                Pharmacy.district_id == districts[district],
                Pharmacy.license_number.like(DEMO_LICENCES),
            )
            .order_by(Pharmacy.license_number)
        ).all()
        pins = land_pins(connection, districts[district], max(count, len(demo)))
        for (pharmacy_id, lat, lon), (new_lat, new_lon) in zip(demo, pins, strict=False):
            if (lat, lon) == (new_lat, new_lon):
                continue
            connection.execute(
                update(Pharmacy).where(Pharmacy.id == pharmacy_id).values(lat=new_lat, lon=new_lon)
            )
            connection.execute(
                update(TravelTimeCache)
                .where(TravelTimeCache.pharmacy_id == pharmacy_id)
                .values(computed_at=now - timedelta(days=3))
            )
            moved += 1
    return moved


def seed_demo(connection: Connection, *, seed: int, now: datetime) -> SeedResult:
    """Adds the demo data inside the caller's transaction. `now` comes from the app clock."""
    today = beirut_date(now)
    numbers = random.Random(seed)
    districts = dict(connection.execute(select(District.name, District.id)).all())
    users: list[dict[str, Any]] = []
    pharmacies: list[dict[str, Any]] = []
    hours: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []

    number = 0
    for district, count in PHARMACIES_PER_DISTRICT:
        district_id = districts[district]
        pins = land_pins(connection, district_id, count)
        for letter, (lat, lon) in zip("ABCDE"[:count], pins, strict=True):
            number += 1
            user_id, pharmacy_id = _uuid(numbers), _uuid(numbers)
            # Two numbers were drawn here for a random pin, until 2026-11-18. They are
            # still drawn, so that everything after them (IDs, stock) stays what it was.
            numbers.randrange(-150, 151)
            numbers.randrange(-150, 151)
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
                    # The centre of a named place of the district: on land.
                    "lat": lat,
                    "lon": lon,
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
                "full_name": CLIENT_NAMES[index - 1],
                "email_verified_at": now,
            }
        )
        first_name, _, last_name = CLIENT_NAMES[index - 1].partition(" ")
        profiles.append(
            {
                "user_id": user_id,
                "status": "ACTIVE",
                "district_id": districts[district],
                "first_name": first_name,
                "last_name": last_name or None,
            }
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


DEMO_EMAILS = "%@demo.dawalink.test"


def set_demo_passwords(connection: Connection, password: str) -> int:
    """Gives every demo account this password. Safe to run again. Returns how many."""
    # Imported here: the seed itself needs no login code.
    from dawalink.services import auth

    auth.check_strength(password)
    changed = connection.execute(
        update(User)
        .where(User.email.like(DEMO_EMAILS))
        .values(password_hash=auth.hash_password(password))
    )
    return int(changed.rowcount)


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
            else:
                result = seed_demo(connection, seed=arguments.seed, now=SystemClock().now())
                log.info(
                    "demo_seeded",
                    pharmacies=result.pharmacies,
                    clients=result.clients,
                    inventory_items=result.inventory_items,
                )
            if settings.demo_accounts_password is not None:
                accounts = set_demo_passwords(
                    connection, settings.demo_accounts_password.get_secret_value()
                )
                log.info("demo_passwords_set", accounts=accounts)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
