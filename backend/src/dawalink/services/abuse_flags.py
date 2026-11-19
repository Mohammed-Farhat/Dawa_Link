"""Something for an admin to look at (docs/04 SM-11, R-AB; docs/03 AS-7).

A flag is raised by code: a client whose messages keep tripping the injection guard, or
a client paused for no-shows. It holds IDs and counts, never a message or a name. An
admin dismisses it, records a warning, or suspends the account it is about; a suspension
goes through the same service as any other, with its effects and its audit event.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.sql import text as sql_text

from dawalink.db.models import AbuseFlag
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import FlagRule, FlagSeverity, FlagState, FlagSubject
from dawalink.services import admin_clients, admin_pharmacies, audit
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

ACTIONS = ("warn", "suspend")


def raise_no_show_pause(tx: Tx, client_id: uuid.UUID, counted: int) -> None:
    """R-AB: a client paused for no-shows is flagged, low. A second pause while the flag
    is open joins it."""
    flag = upsert(AbuseFlag).values(
        subject_type=FlagSubject.CLIENT.value,
        subject_id=client_id,
        rule=FlagRule.NO_SHOW_PAUSE.value,
        severity=FlagSeverity.LOW.value,
        evidence={"counted_no_shows": counted},
    )
    tx.session.execute(
        flag.on_conflict_do_update(
            index_elements=["subject_type", "subject_id", "rule"],
            index_where=sql_text("state = 'OPEN'"),
            set_={"evidence": flag.excluded.evidence},
        )
    )


def open_about(tx: Tx, client_id: uuid.UUID) -> Sequence[AbuseFlag]:
    """The flags about this client that nobody has handled, the high ones first, then
    the oldest. An admin reads a flag on the page of the account it is about: there is
    no list of flags on its own."""
    high_first = case((AbuseFlag.severity == FlagSeverity.HIGH.value, 0), else_=1)
    return (
        tx.session.execute(
            select(AbuseFlag)
            .where(
                AbuseFlag.subject_type == FlagSubject.CLIENT.value,
                AbuseFlag.subject_id == client_id,
                AbuseFlag.state == FlagState.OPEN.value,
            )
            .order_by(high_first, AbuseFlag.created_at, AbuseFlag.id)
        )
        .scalars()
        .all()
    )


def open_counts(tx: Tx) -> tuple[int, int]:
    """How many flags are open, and how many of them are high."""
    row = tx.session.execute(
        select(
            func.count(), func.count().filter(AbuseFlag.severity == FlagSeverity.HIGH.value)
        ).where(AbuseFlag.state == FlagState.OPEN.value)
    ).one()
    return int(row[0]), int(row[1])


def _open(tx: Tx, flag_id: uuid.UUID) -> AbuseFlag:
    flag = tx.session.execute(
        select(AbuseFlag)
        .where(AbuseFlag.id == flag_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if flag is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown flag.")
    if flag.state != FlagState.OPEN.value:
        raise ServiceError(Code.CHANGED_SINCE, "This flag was already handled.")
    return flag


def _close(
    tx: Tx, flag: AbuseFlag, admin_id: uuid.UUID, state: FlagState, action: str | None, reason: str
) -> None:
    flag.state, flag.action = state.value, action
    flag.resolved_by, flag.resolved_at = admin_id, tx.now
    audit.record(
        tx,
        Actor.ADMIN,
        "abuse_flag." + (action or "dismiss"),
        "abuse_flag",
        flag.id,
        actor_id=admin_id,
        before={"state": FlagState.OPEN.value},
        after={"state": flag.state, "action": action},
        reason=reason,
    )


def dismiss(tx: Tx, admin_id: uuid.UUID, flag_id: uuid.UUID, *, reason: str) -> AbuseFlag:
    reason = audit.required_reason(reason)
    flag = _open(tx, flag_id)
    _close(tx, flag, admin_id, FlagState.DISMISSED, None, reason)
    return flag


def act(tx: Tx, admin_id: uuid.UUID, flag_id: uuid.UUID, *, action: str, reason: str) -> AbuseFlag:
    """`warn` records that the admin warned the account's owner (by a reply to their
    escalation, or outside DawaLink); `suspend` suspends the account, with everything a
    suspension does (SM-1, SM-2)."""
    reason = audit.required_reason(reason)
    if action not in ACTIONS:
        raise ServiceError(Code.VALIDATION_ERROR, "Unknown action.", field="action")
    flag = _open(tx, flag_id)
    if action == "suspend":
        if flag.subject_type == FlagSubject.CLIENT.value:
            admin_clients.suspend(tx, admin_id, flag.subject_id, reason=reason)
        else:
            admin_pharmacies.suspend(tx, admin_id, flag.subject_id, reason=reason)
    _close(tx, flag, admin_id, FlagState.ACTIONED, action, reason)
    return flag
