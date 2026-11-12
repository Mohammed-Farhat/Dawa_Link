"""Reference data every database needs: the discount tiers and the districts (docs/05 §9)."""

import csv
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Connection, delete, insert
from sqlalchemy.dialects.postgresql import insert as upsert

from dawalink.db.models import District, PricingTier
from dawalink.domain.numbers import DISCOUNT_TIERS

DISTRICTS_FILE = Path("data/districts.csv")


def seed_pricing_tiers(connection: Connection) -> None:
    """Makes the tiers table equal to docs/04 N-4. The price function reads this table."""
    connection.execute(delete(PricingTier))
    connection.execute(
        insert(PricingTier),
        [
            {"min_days": low, "max_days": high, "discount_pct": discount}
            for low, high, discount in DISCOUNT_TIERS
        ],
    )


def read_districts(path: Path = DISTRICTS_FILE) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as file:
        lines = (line for line in file if not line.startswith("#"))
        return [
            {
                "id": int(row["id"]),
                "name": row["district"],
                "governorate": row["governorate"],
                "ref_lat": Decimal(row["ref_lat"]),
                "ref_lon": Decimal(row["ref_lon"]),
            }
            for row in csv.DictReader(lines)
        ]


def seed_districts(connection: Connection, path: Path = DISTRICTS_FILE) -> int:
    """Adds or updates the districts. A district's id never changes once it is used."""
    districts = read_districts(path)
    statement = upsert(District).values(districts)
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=[District.id],
            set_={
                column: statement.excluded[column]
                for column in ("name", "governorate", "ref_lat", "ref_lon")
            },
        )
    )
    return len(districts)
