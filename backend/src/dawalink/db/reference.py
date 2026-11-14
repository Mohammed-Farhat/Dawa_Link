"""Reference data every database needs: the discount tiers, the districts and the areas
(docs/05 §9)."""

import csv
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Connection, delete, insert, select
from sqlalchemy.dialects.postgresql import insert as upsert

from dawalink.db.models import Area, District, PricingTier
from dawalink.domain.numbers import DISCOUNT_TIERS

DISTRICTS_FILE = Path("data/districts.csv")
AREAS_FILE = Path("data/areas.csv")


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


def read_areas(path: Path = AREAS_FILE) -> list[dict[str, object]]:
    """The areas file as it is written: the district by name, other names separated by |."""
    with path.open(encoding="utf-8", newline="") as file:
        lines = (line for line in file if not line.startswith("#"))
        return [
            {
                "id": int(row["id"]),
                "name": row["area"],
                "district": row["district"],
                "other_names": [name for name in row["other_names"].split("|") if name],
                "whole_district": row["whole"] == "1",
                "ref_lat": Decimal(row["ref_lat"]),
                "ref_lon": Decimal(row["ref_lon"]),
            }
            for row in csv.DictReader(lines)
        ]


def seed_areas(connection: Connection, path: Path = AREAS_FILE) -> int:
    """Adds or updates the areas a client can name in chat. Run after `seed_districts`.

    An area's id never changes once it is used: a conversation may point at it.
    """
    districts = {
        name: district_id
        for district_id, name in connection.execute(select(District.id, District.name))
    }
    areas = [
        {
            **{key: value for key, value in area.items() if key != "district"},
            "district_id": districts[str(area["district"])],
        }
        for area in read_areas(path)
    ]
    statement = upsert(Area).values(areas)
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=[Area.id],
            set_={
                column: statement.excluded[column]
                for column in (
                    "name",
                    "district_id",
                    "other_names",
                    "whole_district",
                    "ref_lat",
                    "ref_lon",
                )
            },
        )
    )
    return len(areas)
