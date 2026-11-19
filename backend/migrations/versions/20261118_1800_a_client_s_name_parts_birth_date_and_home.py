"""a client's name parts, birth date and home

The client's profile holds more (the owner, 2026-11-18, decision log BLD-D40): the name
in parts, a birth date, a home town from our own list of places, and a home place the
client puts on a map and can move. The home place is rounded like every location we
keep (about 100 m).

Existing clients get their one name split at its first space. Going back drops the
columns: what they held is lost.

Revision ID: b3e8a1d46f20
Revises: 9d2f4b7c1e55
Create Date: 2026-11-18 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3e8a1d46f20"
down_revision: str | None = "9d2f4b7c1e55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "client_profiles"
HOME_PLACE = "(home_lat IS NULL) = (home_lon IS NULL)"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("first_name", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("middle_name", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("last_name", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column(TABLE, sa.Column("home_area_id", sa.SmallInteger(), nullable=True))
    op.add_column(TABLE, sa.Column("home_lat", sa.Numeric(7, 3), nullable=True))
    op.add_column(TABLE, sa.Column("home_lon", sa.Numeric(7, 3), nullable=True))
    op.create_foreign_key(
        op.f("fk_client_profiles_home_area_id_areas"),
        TABLE,
        "areas",
        ["home_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(op.f("ck_client_profiles_home_place_is_whole"), TABLE, HOME_PLACE)
    op.execute(
        """
        UPDATE client_profiles c
        SET first_name = split_part(btrim(u.full_name), ' ', 1),
            last_name = NULLIF(btrim(substr(btrim(u.full_name),
                                            length(split_part(btrim(u.full_name), ' ', 1)) + 1)), '')
        FROM users u
        WHERE u.id = c.user_id
        """
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_client_profiles_home_place_is_whole"), TABLE, type_="check")
    op.drop_constraint(op.f("fk_client_profiles_home_area_id_areas"), TABLE, type_="foreignkey")
    for column in (
        "home_lon",
        "home_lat",
        "home_area_id",
        "birth_date",
        "last_name",
        "middle_name",
        "first_name",
    ):
        op.drop_column(TABLE, column)
