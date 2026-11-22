"""a client deletes their account

The owner, 2026-11-20: "Delete my account" (it was postponed, decision log D4). A client
deletes their own account from their profile (docs/04 R-AU10). The user row stays,
emptied of everything personal, because reservations, the books and the audit log point
at it; the profile says DELETED and when. What the app's login may not delete (the
chats, the notifications, the emails) is erased by the clean-up soon after, and
`emptied_at` says when it was.

An email queued for a deleted account is never sent: it becomes DROPPED, a state of its
own, so it is neither a lie ("sent") nor an alert ("dead").

Going back refuses while a deleted account exists: its row would fit none of the
statuses left, and nothing could say it was deleted.

Revision ID: f3c8a1d6b920
Revises: e5b0c3a9d417
Create Date: 2026-11-20 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c8a1d6b920"
down_revision: str | None = "e5b0c3a9d417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLIENT_STATUSES_BEFORE = "status IN ('UNVERIFIED', 'ACTIVE', 'PAUSED', 'SUSPENDED')"
CLIENT_STATUSES = "status IN ('UNVERIFIED', 'ACTIVE', 'PAUSED', 'SUSPENDED', 'DELETED')"
OUTBOX_STATES_BEFORE = "state IN ('QUEUED', 'SENT', 'FAILED', 'DEAD')"
OUTBOX_STATES = "state IN ('QUEUED', 'SENT', 'FAILED', 'DEAD', 'DROPPED')"


def upgrade() -> None:
    op.add_column(
        "client_profiles", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "client_profiles", sa.Column("emptied_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_constraint(op.f("ck_client_profiles_status_values"), "client_profiles", type_="check")
    op.create_check_constraint(
        op.f("ck_client_profiles_status_values"), "client_profiles", CLIENT_STATUSES
    )
    op.create_check_constraint(
        op.f("ck_client_profiles_deleted_has_a_moment"),
        "client_profiles",
        "(status = 'DELETED') = (deleted_at IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_client_profiles_emptied_after_deleted"),
        "client_profiles",
        "emptied_at IS NULL OR deleted_at IS NOT NULL",
    )
    op.create_index(
        "ix_client_profiles_to_empty",
        "client_profiles",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("status = 'DELETED' AND emptied_at IS NULL"),
    )
    op.drop_constraint(op.f("ck_email_outbox_state_values"), "email_outbox", type_="check")
    op.create_check_constraint(op.f("ck_email_outbox_state_values"), "email_outbox", OUTBOX_STATES)


def downgrade() -> None:
    deleted = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM client_profiles WHERE status = 'DELETED'"))
        .scalar_one()
    )
    if deleted:
        raise RuntimeError(
            f"{deleted} deleted account(s) exist: going back would leave them with no status."
        )
    op.execute("UPDATE email_outbox SET state = 'DEAD' WHERE state = 'DROPPED'")
    op.drop_constraint(op.f("ck_email_outbox_state_values"), "email_outbox", type_="check")
    op.create_check_constraint(
        op.f("ck_email_outbox_state_values"), "email_outbox", OUTBOX_STATES_BEFORE
    )
    op.drop_index(
        "ix_client_profiles_to_empty",
        table_name="client_profiles",
        postgresql_where=sa.text("status = 'DELETED' AND emptied_at IS NULL"),
    )
    op.drop_constraint(
        op.f("ck_client_profiles_emptied_after_deleted"), "client_profiles", type_="check"
    )
    op.drop_constraint(
        op.f("ck_client_profiles_deleted_has_a_moment"), "client_profiles", type_="check"
    )
    op.drop_constraint(op.f("ck_client_profiles_status_values"), "client_profiles", type_="check")
    op.create_check_constraint(
        op.f("ck_client_profiles_status_values"), "client_profiles", CLIENT_STATUSES_BEFORE
    )
    op.drop_column("client_profiles", "emptied_at")
    op.drop_column("client_profiles", "deleted_at")
