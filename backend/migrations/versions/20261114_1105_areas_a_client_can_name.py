"""areas a client can name

The `areas` table, the area a conversation's location comes from, and "area" as a third
source of a location (decision log BLD-D14).

Revision ID: 7c41e9a2b6d0
Revises: 3a8df65739a1
Create Date: 2026-11-14 11:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c41e9a2b6d0"
down_revision: str | None = "3a8df65739a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HAS_A_SOURCE_LIST = ("conversations", "sourcing_requests")


def _sources(*values: str) -> str:
    return "loc_source IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.create_table(
        "areas",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("district_id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "other_names",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("whole_district", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ref_lat", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.Column("ref_lon", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name=op.f("fk_areas_district_id_districts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_areas")),
        sa.UniqueConstraint("name", "district_id", name=op.f("uq_areas_name_district_id")),
    )
    op.add_column("conversations", sa.Column("loc_area_id", sa.SmallInteger(), nullable=True))
    op.create_foreign_key(
        op.f("fk_conversations_loc_area_id_areas"),
        "conversations",
        "areas",
        ["loc_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    for table in HAS_A_SOURCE_LIST:
        op.drop_constraint(op.f(f"ck_{table}_loc_source_values"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_loc_source_values"), table, _sources("shared", "district", "area")
        )
    op.create_check_constraint(
        op.f("ck_conversations_area_only_for_its_source"),
        "conversations",
        "(loc_source IS NOT DISTINCT FROM 'area') = (loc_area_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_conversations_area_only_for_its_source"), "conversations", type_="check"
    )
    # A location that came from a named area becomes an ordinary shared one.
    for table in HAS_A_SOURCE_LIST:
        op.execute(f"UPDATE {table} SET loc_source = 'shared' WHERE loc_source = 'area'")
        op.drop_constraint(op.f(f"ck_{table}_loc_source_values"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_loc_source_values"), table, _sources("shared", "district")
        )
    op.drop_constraint(
        op.f("fk_conversations_loc_area_id_areas"), "conversations", type_="foreignkey"
    )
    op.drop_column("conversations", "loc_area_id")
    op.drop_table("areas")
