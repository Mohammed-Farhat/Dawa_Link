"""each pharmacy decides what it lists

The owner, 2026-11-19 (decision log BLD-D44): a pharmacy no longer has every box with
180 days left or fewer listed for it. It chooses when its boxes are listed by themselves
(`pharmacies.auto_list_days`: 30, 60, 90 or 180 days left, or 0 for never), and may list
one box by hand (`listing_control = 'LISTED'`).

Every pharmacy starts at 180, which is what happened until now: nothing changes for a
pharmacy that changes nothing. A box is still never listed with more than 180 days left.

Going back turns the boxes listed by hand into ordinary ones and drops the column.

Revision ID: d94c1e7a5b02
Revises: c7a2f90b3e11
Create Date: 2026-11-19 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d94c1e7a5b02"
down_revision: str | None = "c7a2f90b3e11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The only definition of "visible to clients" (docs/04 INV-16). The columns it returns
# are unchanged, so everything that reads it reads it as before.
VISIBLE = """
    CREATE OR REPLACE FUNCTION visible_listings(p_today date)
    RETURNS TABLE (
      inventory_item_id uuid,
      pharmacy_id uuid,
      product_id uuid,
      expiry_date date,
      days_left int,
      qty_available int,
      price_lbp bigint
    ) LANGUAGE sql STABLE AS $$
      SELECT ii.id, ii.pharmacy_id, ii.product_id, ii.expiry_date,
             ii.expiry_date - p_today,
             ii.qty_on_hand - ii.qty_reserved,
             effective_price_lbp(
               p.public_price_lbp, ii.price_override_lbp, ii.expiry_date - p_today)
      FROM inventory_items ii
      JOIN products p ON p.id = ii.product_id
      JOIN pharmacies ph ON ph.id = ii.pharmacy_id
      WHERE ph.status = 'APPROVED'
        AND NOT p.controlled
        AND ii.qty_on_hand - ii.qty_reserved >= 1
        AND ii.expiry_date BETWEEN p_today AND p_today + 180
        AND {listed}
    $$
"""
# Listed by hand, or by the pharmacy's own rule (0: nothing by itself).
BY_THE_PHARMACY = """(
          ii.listing_control = 'LISTED'
          OR (ii.listing_control = 'LIVE'
              AND ph.auto_list_days > 0
              AND ii.expiry_date <= p_today + ph.auto_list_days)
        )"""
BEFORE = "ii.listing_control = 'LIVE'"


def upgrade() -> None:
    op.add_column(
        "pharmacies",
        sa.Column(
            "auto_list_days", sa.SmallInteger(), server_default=sa.text("180"), nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_pharmacies_auto_list_days_range"), "pharmacies", "auto_list_days BETWEEN 0 AND 180"
    )
    op.drop_constraint(
        op.f("ck_inventory_items_listing_control_values"), "inventory_items", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_inventory_items_listing_control_values"),
        "inventory_items",
        "listing_control IN ('LIVE', 'LISTED', 'PAUSED')",
    )
    op.execute(VISIBLE.format(listed=BY_THE_PHARMACY))


def downgrade() -> None:
    op.execute(VISIBLE.format(listed=BEFORE))
    op.execute(
        "UPDATE inventory_items SET listing_control = 'LIVE' WHERE listing_control = 'LISTED'"
    )
    op.drop_constraint(
        op.f("ck_inventory_items_listing_control_values"), "inventory_items", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_inventory_items_listing_control_values"),
        "inventory_items",
        "listing_control IN ('LIVE', 'PAUSED')",
    )
    op.drop_constraint(op.f("ck_pharmacies_auto_list_days_range"), "pharmacies", type_="check")
    op.drop_column("pharmacies", "auto_list_days")
