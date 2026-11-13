"""What the services need (build step 4).

- `orders.reminder_sent_at`: so the clock check sends each pickup reminder once, and finds
  the reservations still to remind with one indexed query.
- `claims.source`: where a claim was created, which decides where its events go.
- One open early-release request per claim.

Revision ID: 1b8c0d249d75
Revises: f508dadd13e7
Create Date: 2026-11-12 19:03:29.004459
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1b8c0d249d75"
down_revision: str | None = "f508dadd13e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("source", sa.Text(), server_default=sa.text("'search'"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_claims_source_values"),
        "claims",
        "source IN ('search', 'assistant', 'request')",
    )
    op.create_index(
        "uq_early_release_requests_one_open_per_claim",
        "early_release_requests",
        ["claim_id"],
        unique=True,
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.add_column(
        "orders", sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_orders_reminder_due",
        "orders",
        ["deadline"],
        unique=False,
        postgresql_where=sa.text("state = 'RESERVED' AND reminder_sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orders_reminder_due",
        table_name="orders",
        postgresql_where=sa.text("state = 'RESERVED' AND reminder_sent_at IS NULL"),
    )
    op.drop_column("orders", "reminder_sent_at")
    op.drop_index(
        "uq_early_release_requests_one_open_per_claim",
        table_name="early_release_requests",
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.drop_constraint(op.f("ck_claims_source_values"), "claims", type_="check")
    op.drop_column("claims", "source")
