"""another brand is shown, never held

Nothing waits for another brand of a medicine any more, so the two "also its
equivalents" columns go. A new kind of card shows where another brand is, with no
[Reserve] button (decision log BLD-D17).

Going back restores the columns as false for every row: which claims had allowed other
brands is not kept.

Revision ID: 9d2f4b7c1e55
Revises: 7c41e9a2b6d0
Create Date: 2026-11-14 15:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d2f4b7c1e55"
down_revision: str | None = "7c41e9a2b6d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WAITED_FOR_OTHER_BRANDS = ("claims", "early_release_requests")
KINDS = (
    "reserve",
    "reserve_group",
    "accept_offer",
    "cancel",
    "request_summary",
    "constraint_change",
    "remove_item",
)


def _kinds(*values: str) -> str:
    return "kind IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    for table in WAITED_FOR_OTHER_BRANDS:
        op.drop_column(table, "include_equivalents")
    op.drop_constraint(op.f("ck_proposals_kind_values"), "proposals", type_="check")
    op.create_check_constraint(
        op.f("ck_proposals_kind_values"), "proposals", _kinds(*KINDS, "other_brand")
    )


def downgrade() -> None:
    op.execute("DELETE FROM proposals WHERE kind = 'other_brand'")
    op.drop_constraint(op.f("ck_proposals_kind_values"), "proposals", type_="check")
    op.create_check_constraint(op.f("ck_proposals_kind_values"), "proposals", _kinds(*KINDS))
    for table in WAITED_FOR_OTHER_BRANDS:
        op.add_column(
            table,
            sa.Column(
                "include_equivalents", sa.Boolean(), server_default=sa.text("false"), nullable=False
            ),
        )
