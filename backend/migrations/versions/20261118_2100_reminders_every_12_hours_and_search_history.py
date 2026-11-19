"""reminders every 12 hours, and a client's last searches

Two things the owner asked for on 2026-11-18 (decision log BLD-D42):

- a reservation is reminded every 12 hours and once 2 hours before its deadline, so an
  order holds the moment of its next reminder (`next_reminder_at`), which the clock check
  looks for. Reservations that are open now get one last reminder, 2 hours before their
  deadline, unless they already had one;
- `search_history`: the names a client searched lately, read only by them and purged
  after 30 days.

Going back drops the column and the table: the searches are lost.

Revision ID: c7a2f90b3e11
Revises: b3e8a1d46f20
Create Date: 2026-11-18 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a2f90b3e11"
down_revision: str | None = "b3e8a1d46f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("next_reminder_at", sa.DateTime(timezone=True), nullable=True)
    )
    # The reservations open at this moment get the last reminder only, and only if its
    # moment is still to come: one that is already past would be sent at the first clock
    # check, which is the reminder "at once" this migration removes.
    op.execute(
        "UPDATE orders SET next_reminder_at = deadline - interval '2 hours' "
        "WHERE state = 'RESERVED' AND reminder_sent_at IS NULL "
        "AND deadline - interval '2 hours' > now()"
    )
    op.drop_index("ix_orders_reminder_due", table_name="orders")
    op.create_index(
        "ix_orders_reminder_due",
        "orders",
        ["next_reminder_at"],
        postgresql_where=sa.text("state = 'RESERVED' AND next_reminder_at IS NOT NULL"),
    )

    op.create_table(
        "search_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(query) BETWEEN 2 AND 60", name=op.f("ck_search_history_query_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["users.id"],
            name=op.f("fk_search_history_client_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_history")),
    )
    op.create_index("ix_search_history_client", "search_history", ["client_id", "searched_at"])


def downgrade() -> None:
    op.drop_index("ix_search_history_client", table_name="search_history")
    op.drop_table("search_history")
    op.drop_index("ix_orders_reminder_due", table_name="orders")
    op.create_index(
        "ix_orders_reminder_due",
        "orders",
        ["deadline"],
        postgresql_where=sa.text("state = 'RESERVED' AND reminder_sent_at IS NULL"),
    )
    op.drop_column("orders", "next_reminder_at")
