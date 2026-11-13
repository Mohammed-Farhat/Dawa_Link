"""The once-a-day tasks: retention and the stale-inventory reminder (docs/04 R-RET, N-16).

Retention runs with its own database login, which may delete what has passed its time and
nothing else (docs/05 §7). Every cutoff is computed from the app clock.
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as upsert

from dawalink.db.models import AppState, InventoryItem, Pharmacy
from dawalink.domain.numbers import (
    AUDIT_RETENTION,
    CONVERSATION_RETENTION,
    NOTIFICATION_RETENTION,
    STALE_INVENTORY_AFTER,
    TRAVEL_CACHE_TTL,
)
from dawalink.services.context import Tx
from dawalink.services.notify import Template, notify

LAST_RUN_KEY = "daily_tasks_last_run"


def due_today(tx: Tx) -> bool:
    """True once per Beirut day, even across restarts: the last run is stored."""
    last = tx.session.execute(select(AppState.value).where(AppState.key == LAST_RUN_KEY)).scalar()
    return last != tx.today.isoformat()


def mark_done(tx: Tx, day: date) -> None:
    statement = upsert(AppState).values(key=LAST_RUN_KEY, value=day.isoformat())
    tx.session.execute(
        statement.on_conflict_do_update(
            index_elements=[AppState.key], set_={"value": statement.excluded.value}
        )
    )


def purge(tx: Tx) -> dict[str, int]:
    """Deletes what has passed its retention time. Run with the retention login (R-RET)."""
    chat_cutoff = tx.now - CONVERSATION_RETENTION
    statements: dict[str, tuple[str, dict[str, Any]]] = {
        # A request's thread goes 30 days after the request closed; a chat, 30 days after
        # its last activity. Messages and proposals go with their conversation.
        "conversations": (
            "DELETE FROM conversations c WHERE (c.kind = 'chat' AND c.last_activity_at < :cutoff) "
            "OR (c.kind = 'request' AND EXISTS (SELECT 1 FROM sourcing_requests r "
            "    WHERE r.id = c.request_id AND r.closed_at < :cutoff))",
            {"cutoff": chat_cutoff},
        ),
        # The client's location is erased from what is kept (N-43).
        "request_locations": (
            "UPDATE sourcing_requests SET loc_lat = NULL, loc_lon = NULL, loc_source = NULL "
            "WHERE closed_at < :cutoff AND loc_lat IS NOT NULL",
            {"cutoff": chat_cutoff},
        ),
        "claim_locations": (
            "UPDATE claims SET loc_lat = NULL, loc_lon = NULL "
            "WHERE closed_at < :cutoff AND loc_lat IS NOT NULL",
            {"cutoff": chat_cutoff},
        ),
        "notifications": (
            "DELETE FROM notifications WHERE created_at < :cutoff",
            {"cutoff": tx.now - NOTIFICATION_RETENTION},
        ),
        "sessions": (
            "DELETE FROM sessions WHERE expires_at < :now OR revoked_at IS NOT NULL",
            {"now": tx.now},
        ),
        "verification_tokens": (
            "DELETE FROM email_verification_tokens WHERE expires_at < :now OR used_at IS NOT NULL",
            {"now": tx.now},
        ),
        "travel_times": (
            "DELETE FROM travel_time_cache WHERE computed_at < :cutoff",
            {"cutoff": tx.now - TRAVEL_CACHE_TTL},
        ),
        "claim_skips": ("DELETE FROM claim_skips WHERE skip_until < :now", {"now": tx.now}),
        "audit_events": (
            "DELETE FROM audit_events WHERE occurred_at < :cutoff",
            {"cutoff": tx.now - AUDIT_RETENTION},
        ),
    }
    return {
        name: tx.session.execute(text(statement), values).rowcount  # type: ignore[attr-defined]
        for name, (statement, values) in statements.items()
    }


def remind_stale_inventories(tx: Tx) -> int:
    """A pharmacy that hasn't touched its inventory for a week is reminded (N-16, PN-10)."""
    last_edit = (
        select(
            InventoryItem.pharmacy_id.label("pharmacy_id"),
            func.max(InventoryItem.last_edited_at).label("edited_at"),
        )
        .group_by(InventoryItem.pharmacy_id)
        .subquery()
    )
    stale = tx.session.execute(
        select(Pharmacy.id, Pharmacy.owner_user_id)
        .join(last_edit, last_edit.c.pharmacy_id == Pharmacy.id)
        .where(
            Pharmacy.status == "APPROVED", last_edit.c.edited_at < tx.now - STALE_INVENTORY_AFTER
        )
    ).all()
    week = tx.today - timedelta(days=tx.today.weekday())
    reminded = 0
    for pharmacy_id, owner in stale:
        # At most one reminder a week per pharmacy.
        if notify(tx, owner, Template.STALE_INVENTORY, {}, event=f"stale:{pharmacy_id}:{week}"):
            reminded += 1
    return reminded
