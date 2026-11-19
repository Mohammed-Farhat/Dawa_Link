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
    SEARCH_HISTORY_RETENTION,
    STALE_INVENTORY_AFTER,
    TRAVEL_CACHE_TTL,
    VERIFICATION_LINK_VALID,
)
from dawalink.services.context import Tx
from dawalink.services.notify import Template, notify

LAST_RUN_KEY = "daily_tasks_last_run"
CHECKS_KEY = "daily_checks"
# IDs kept from one check: enough to start looking; the count says how many there are.
MOST_IDS = 20

# INV-2: an item's reserved units are the units its open orders hold (docs/05 §4).
STOCK_OFF = (
    "SELECT ii.id FROM inventory_items ii "
    "LEFT JOIN orders o ON o.inventory_item_id = ii.id AND o.state IN ('OFFERED', 'RESERVED') "
    "GROUP BY ii.id HAVING ii.qty_reserved <> COALESCE(SUM(o.qty_locked), 0) "
    "ORDER BY ii.id"
)
# INV-18, for open requests: an item's secured units are its reserved or picked-up units,
# and it is SECURED exactly when they cover its quantity.
REQUESTS_OFF = (
    "SELECT ri.id FROM request_items ri "
    "JOIN sourcing_requests r ON r.id = ri.request_id AND r.state = 'OPEN' "
    "LEFT JOIN orders o ON o.request_item_id = ri.id AND o.state IN ('RESERVED', 'PICKED_UP') "
    "GROUP BY ri.id, ri.qty, ri.qty_secured, ri.state "
    "HAVING ri.qty_secured <> COALESCE(SUM(CASE WHEN o.state = 'RESERVED' THEN o.qty_locked "
    "                                         ELSE o.qty_picked_up END), 0) "
    "    OR (ri.state = 'SECURED') <> (ri.qty_secured >= ri.qty) "
    "ORDER BY ri.id"
)


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


def books_that_are_off(tx: Tx) -> dict[str, list[str]]:
    """The boxes and request items whose counts don't add up (INV-2, INV-18; docs/09 FO-3).

    Every change to these counts happens in one transaction with what it counts, so this
    should always find nothing. It is the check that would notice a bug that got past the
    tests. **It changes nothing:** a wrong count is looked into by hand.
    """
    return {
        "stock_off": [str(row[0]) for row in tx.session.execute(text(STOCK_OFF))],
        "requests_off": [str(row[0]) for row in tx.session.execute(text(REQUESTS_OFF))],
    }


def last_checks(tx: Tx) -> dict[str, Any]:
    """What the last daily run found: `{day, stock_off, requests_off, ..._count,
    retention_failed_days}`. Empty before the first run."""
    found = tx.session.execute(select(AppState.value).where(AppState.key == CHECKS_KEY)).scalar()
    return dict(found) if isinstance(found, dict) else {}


def keep_checks(
    tx: Tx, day: date, off: dict[str, list[str]], *, retention_failed: bool | None
) -> dict[str, Any]:
    """Stores the day's findings for the admins' Health page. `retention_failed` is None
    when there was no purge to try; the days in a row are counted here (FO-4)."""
    before = int(last_checks(tx).get("retention_failed_days", 0))
    failed_days = 0 if not retention_failed else before + 1
    kept = {
        "day": day.isoformat(),
        "stock_off": off["stock_off"][:MOST_IDS],
        "stock_off_count": len(off["stock_off"]),
        "requests_off": off["requests_off"][:MOST_IDS],
        "requests_off_count": len(off["requests_off"]),
        "retention_failed_days": failed_days,
    }
    statement = upsert(AppState).values(key=CHECKS_KEY, value=kept)
    tx.session.execute(
        statement.on_conflict_do_update(
            index_elements=[AppState.key], set_={"value": statement.excluded.value}
        )
    )
    return kept


# A registration nobody confirmed, by its pharmacist's user row. All four conditions are
# counted in real time, like the link itself (R-T11):
# - the pharmacy still waits, and its email was never confirmed;
# - it was made longer ago than a link lasts;
# - no link is still good (another one asked for at hour 23 is good until hour 47);
# - no confirmation email still waits to be sent (the mail server was down).
UNCONFIRMED_PHARMACISTS = """
    SELECT u.id FROM users u
    JOIN pharmacies p ON p.owner_user_id = u.id
    WHERE u.role = 'pharmacist' AND u.email_verified_at IS NULL AND p.status = 'PENDING'
      AND u.created_at < :made_before
      AND NOT EXISTS (
          SELECT 1 FROM email_verification_tokens t
          WHERE t.user_id = u.id AND t.used_at IS NULL AND t.expires_at > :now)
      AND NOT EXISTS (
          SELECT 1 FROM email_outbox e
          WHERE e.user_id = u.id AND e.template = :confirm AND e.state IN ('QUEUED', 'FAILED'))
    ORDER BY u.id
    FOR UPDATE OF u
"""
# What can hang on such a registration, children first. A pharmacy that was never approved
# has no stock, no reservation and no ask; its pharmacist never got past the status page.
_OF_A_REGISTRATION = (
    "DELETE FROM pharmacy_hours WHERE pharmacy_id IN "
    "(SELECT id FROM pharmacies WHERE owner_user_id = ANY(:users))",
    "DELETE FROM email_verification_tokens WHERE user_id = ANY(:users)",
    "DELETE FROM email_outbox WHERE user_id = ANY(:users)",
    "DELETE FROM notifications WHERE user_id = ANY(:users)",
    "DELETE FROM sessions WHERE user_id = ANY(:users)",
    "DELETE FROM pharmacies WHERE owner_user_id = ANY(:users)",
    "DELETE FROM users WHERE id = ANY(:users)",
)
CONFIRM_EMAIL = "CN-1"


def purge_unconfirmed_registrations(tx: Tx) -> int:
    """Deletes the pharmacy registrations whose email was never confirmed and whose link
    has expired (the owner, 2026-11-17, Q49). Returns how many.

    A licence number and a phone belong to one pharmacy. Without this, someone who typed a
    pharmacy's licence and never confirmed would keep the real pharmacy out for ever
    (docs/10 RR-18). The real one simply registers again.

    The user rows are locked first: a pharmacist who asks for a new link at this very
    moment waits, and finds the registration gone, never half of it.
    """
    users = [
        row[0]
        for row in tx.session.execute(
            text(UNCONFIRMED_PHARMACISTS),
            {
                "made_before": tx.real_now - VERIFICATION_LINK_VALID,
                "now": tx.real_now,
                "confirm": CONFIRM_EMAIL,
            },
        )
    ]
    if users:
        for statement in _OF_A_REGISTRATION:
            tx.session.execute(text(statement), {"users": users})
    return len(users)


def purge(tx: Tx) -> dict[str, int]:
    """Deletes what has passed its retention time. Run with the retention login (R-RET)."""
    unconfirmed = purge_unconfirmed_registrations(tx)
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
        # What a client searched says something about their health: it is not kept long.
        "search_history": (
            "DELETE FROM search_history WHERE searched_at < :cutoff",
            {"cutoff": tx.now - SEARCH_HISTORY_RETENTION},
        ),
        "notifications": (
            "DELETE FROM notifications WHERE created_at < :cutoff",
            {"cutoff": tx.now - NOTIFICATION_RETENTION},
        ),
        # Logins are counted in real time (R-T11): a session that is still good must
        # survive a demo clock that was moved a week ahead.
        "sessions": (
            "DELETE FROM sessions WHERE expires_at < :now OR revoked_at IS NOT NULL",
            {"now": tx.real_now},
        ),
        "verification_tokens": (
            "DELETE FROM email_verification_tokens WHERE expires_at < :now OR used_at IS NOT NULL",
            {"now": tx.real_now},
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
    return {"unconfirmed_registrations": unconfirmed} | {
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
