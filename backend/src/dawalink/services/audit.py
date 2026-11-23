"""Every state change writes exactly one audit event naming its actor (docs/04 INV-13).

`before` and `after` hold states, quantities and IDs only: never a name, an email, a phone
number or a location.

**Reading the log (AS-11).** An admin reads it as sentences: who, what happened, the page
it is about, the fields that changed. `shown` prepares that from the stored rows, and
keeps the rule of the log as it reads it: **the fields that changed are named, never
their values.** What it gives of `before` and `after` is
- the names of the fields that changed (`changed`);
- a move between two of the app's own states (`state_from`, `state_to`), never a text a
  person typed;
- how many things an action ended ("3 offers cancelled": `counts`);
- a code the app chose from its own list (an escalation's reason: `code`).
Quantities, prices, dates, hours and the clock's offset stay in the table.
"""

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from sqlalchemy import Select, or_, select

from dawalink.db.models import (
    AbuseFlag,
    AuditEvent,
    Claim,
    ClientProfile,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    Escalation,
    InventoryItem,
    InventoryUpload,
    Order,
    Pharmacy,
    RequestItem,
    SourcingRequest,
    User,
)
from dawalink.domain.audit_actions import KINDS, AuditAction
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import (
    ClaimKind,
    EscalationReason,
    FlagSubject,
    ReportReason,
    UserRole,
)
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.paging import count_rows

MAX_REASON = 300


def required_reason(text: str | None) -> str:
    """The few words an admin gives for an action: every admin change has them (SM-1,
    SM-2). They are kept in the audit log, so they name no person."""
    reason = (text or "").strip()
    if not reason:
        raise ServiceError(Code.REASON_REQUIRED, "Say why, in a few words.")
    if len(reason) > MAX_REASON:
        raise ServiceError(
            Code.VALIDATION_ERROR, "A reason has 300 characters at most.", field="reason"
        )
    return reason


def record(
    tx: Tx,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    *,
    actor_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    tx.session.add(
        AuditEvent(
            occurred_at=tx.now,
            actor_type=actor.value,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
            reason=reason,
        )
    )


# --- Reading the log ---------------------------------------------------------------------------


def _filtered(
    *,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    action: str | None,
    kind: str | None,
    actor_type: Actor | None,
) -> Select[AuditEvent]:
    """The log with the admin's choices, before any place in it is chosen."""
    statement = select(AuditEvent)
    if entity_type:
        statement = statement.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        statement = statement.where(AuditEvent.entity_id == entity_id)
    if action:
        statement = statement.where(
            AuditEvent.action.startswith(action, autoescape=True)
            if action.endswith(".")
            else AuditEvent.action == action
        )
    if kind:
        starts = KINDS.get(kind, ())
        if not starts:
            raise ServiceError(Code.VALIDATION_ERROR, "Unknown kind of action.", field="kind")
        statement = statement.where(
            or_(*[AuditEvent.action.startswith(start, autoescape=True) for start in starts])
        )
    if actor_type is not None:
        statement = statement.where(AuditEvent.actor_type == actor_type.value)
    return statement


def listed(
    tx: Tx,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    action: str | None = None,
    kind: str | None = None,
    actor_type: Actor | None = None,
    before_id: int | None = None,
    offset: int = 0,
    limit: int = 50,
) -> Sequence[AuditEvent]:
    """The audit log, newest first (AS-11). `action` matches a whole action
    ("pharmacy.approve") or everything of one kind ("pharmacy."); `kind` is one of the
    families of `KINDS`. `before_id` keeps the events older than that one; `offset` then
    skips that many of what is left (numbered pages)."""
    statement = _filtered(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        kind=kind,
        actor_type=actor_type,
    )
    if before_id is not None:
        statement = statement.where(AuditEvent.id < before_id)
    return (
        tx.session.execute(statement.order_by(AuditEvent.id.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )


def listed_total(
    tx: Tx,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    action: str | None = None,
    kind: str | None = None,
    actor_type: Actor | None = None,
) -> int:
    """How many events the same choices match, wherever the page is (`before_id` and
    `offset` are places in the list, not choices)."""
    return count_rows(
        tx,
        _filtered(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            kind=kind,
            actor_type=actor_type,
        ),
    )


# --- What a row of the log says, in words ------------------------------------------------------

# The keys of `before` and `after` that hold one of the app's own states, never a text.
_STATE_KEYS = ("state", "status", "listing_control")
# A state is a code of the app: capitals and underscores ("IN_PROGRESS"). Anything else in
# such a key is not shown.
_A_STATE = re.compile(r"^[A-Z][A-Z_]{0,39}$")
# A field's name, as the code writes it ("qty_on_hand").
_A_FIELD = re.compile(r"^[a-z][a-z_]{0,39}$")
# How many things an action ended or touched: a count, never the value of a field.
_COUNT_KEYS = (
    "offers_cancelled",
    "asks_withdrawn",
    "orders_cancelled",
    "requests_closed",
    "watches_ended",
    "flags_closed",
    "escalations_closed",
    "boxes",
    "cases",
    "items",
    "asks",
)
# Keys that are neither a field of the thing nor shown: IDs and bookkeeping.
_NOT_A_FIELD = frozenset({*_STATE_KEYS, *_COUNT_KEYS, "outcome", "fields", "reason"})
# The events whose `after` holds a code the app chose from a list of its own, and that
# list. Only these: `before.reason` of a resubmitted registration is a text an admin typed.
_CODES: dict[str, tuple[str, type[StrEnum]]] = {
    AuditAction.ESCALATION_OPEN.value: ("reason", EscalationReason),
    AuditAction.ESCALATION_APPEND.value: ("reason", EscalationReason),
    AuditAction.ANSWER_REPORT_NEW.value: ("reason", ReportReason),
    AuditAction.CLAIM_CREATE.value: ("kind", ClaimKind),
}


@dataclass(frozen=True)
class Who:
    """Who did it, as an admin may read it: an admin or a pharmacy by name, a client by
    an ID only, the assistant or the system by what they are."""

    kind: Literal["admin", "pharmacy", "client", "agent", "system"]
    name: str | None = None
    # A pharmacy's or a client's ID, for the link to their page.
    id: uuid.UUID | None = None


@dataclass(frozen=True)
class Subject:
    """The page of the console an event is about, when there is one."""

    kind: Literal["pharmacy", "client", "escalation", "reports", "clock"]
    id: uuid.UUID | None = None


@dataclass(frozen=True)
class Shown:
    event: AuditEvent
    who: Who
    subject: Subject | None
    changed: list[str] = field(default_factory=list)
    state_from: str | None = None
    state_to: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    code: str | None = None


def _state(side: dict[str, Any] | None, key: str) -> str | None:
    value = (side or {}).get(key)
    return value if isinstance(value, str) and _A_STATE.match(value) else None


def _states(event: AuditEvent) -> tuple[str | None, str | None]:
    """From which state to which, when the event moved one. A closed request says how it
    ended (its `outcome`), which is what a person wants to know."""
    if event.action == AuditAction.REQUEST_CLOSE.value:
        return _state(event.before, "state"), _state(event.after, "outcome")
    for key in _STATE_KEYS:
        if key in (event.before or {}) or key in (event.after or {}):
            return _state(event.before, key), _state(event.after, key)
    return None, None


def _changed(event: AuditEvent) -> list[str]:
    """The names of the fields that changed: the list the code wrote, or the fields whose
    value differs between `before` and `after`. Never a value."""
    before, after = event.before or {}, event.after or {}
    named = after.get("fields")
    if isinstance(named, list):
        keys = [str(name) for name in named]
    else:
        keys = [
            key
            for key, value in after.items()
            if key in before and before[key] != value and key not in _NOT_A_FIELD
        ]
    return [key for key in keys if _A_FIELD.match(key)]


def _counts(event: AuditEvent) -> dict[str, int]:
    after = event.after or {}
    return {
        key: after[key]
        for key in _COUNT_KEYS
        if isinstance(after.get(key), int) and not isinstance(after.get(key), bool)
    }


def _code(event: AuditEvent) -> str | None:
    known = _CODES.get(event.action)
    if known is None:
        return None
    key, codes = known
    value = (event.after or {}).get(key)
    return value if value in {member.value for member in codes} else None


def _ids(events: Iterable[AuditEvent], *types: str) -> list[uuid.UUID]:
    return list(
        {event.entity_id for event in events if event.entity_type in types and event.entity_id}
    )


class _Subjects:
    """Finds the page each event is about: one query per kind of ID, for the whole page
    of the log, never one per row."""

    def __init__(self, tx: Tx, events: Sequence[AuditEvent]):
        self.tx = tx
        # What each kind of ID leads to: a pharmacy, or a client.
        self.pharmacy_of: dict[uuid.UUID, uuid.UUID] = {}
        self.client_of: dict[uuid.UUID, uuid.UUID] = {}
        self.escalations: set[uuid.UUID] = set()
        self.case_client: dict[uuid.UUID, uuid.UUID] = {}
        self._read(events)
        # Only pages that open: a pharmacy whose email was never confirmed (or whose
        # registration was deleted) has none for an admin, nor has a client never made.
        self.open_pharmacies = self._pharmacies_that_open(set(self.pharmacy_of.values()))
        self.open_clients = self._clients_that_open(set(self.client_of.values()))

    def _pairs(self, statement: Select[uuid.UUID, uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        return {row[0]: row[1] for row in self.tx.session.execute(statement) if row[1]}

    def _read(self, events: Sequence[AuditEvent]) -> None:
        session = self.tx.session
        for pharmacy_id in _ids(events, "pharmacy"):
            self.pharmacy_of[pharmacy_id] = pharmacy_id
        for client_id in _ids(events, "client"):
            self.client_of[client_id] = client_id
        # A pharmacy's boxes, its stock files and the asks it answers lead to it.
        of_a_pharmacy: tuple[tuple[Any, str], ...] = (
            (InventoryItem, "inventory_item"),
            (InventoryUpload, "inventory_upload"),
            (EarlyReleaseAsk, "early_release_ask"),
        )
        for model, kind in of_a_pharmacy:
            ids = _ids(events, kind)
            if ids:
                self.pharmacy_of |= self._pairs(
                    select(model.id, model.pharmacy_id).where(model.id.in_(ids))
                )
        # A client's reservations, waits, requests and early-release asks lead to them.
        of_a_client: tuple[tuple[Any, str], ...] = (
            (Order, "order"),
            (Claim, "claim"),
            (SourcingRequest, "sourcing_request"),
            (EarlyReleaseRequest, "early_release_request"),
        )
        for model, kind in of_a_client:
            ids = _ids(events, kind)
            if ids:
                self.client_of |= self._pairs(
                    select(model.id, model.client_id).where(model.id.in_(ids))
                )
        items = _ids(events, "request_item")
        if items:
            self.client_of |= self._pairs(
                select(RequestItem.id, SourcingRequest.client_id)
                .join(SourcingRequest, SourcingRequest.id == RequestItem.request_id)
                .where(RequestItem.id.in_(items))
            )
        flags = _ids(events, "abuse_flag")
        if flags:
            for flag_id, subject_type, subject_id in session.execute(
                select(AbuseFlag.id, AbuseFlag.subject_type, AbuseFlag.subject_id).where(
                    AbuseFlag.id.in_(flags)
                )
            ):
                if subject_type == FlagSubject.PHARMACY.value:
                    self.pharmacy_of[flag_id] = subject_id
                else:
                    self.client_of[flag_id] = subject_id
        # A login leads to the client or the pharmacy it is; an admin's to nothing.
        users = _ids(events, "user")
        if users:
            self.client_of |= {
                user_id: user_id
                for (user_id,) in session.execute(
                    select(ClientProfile.user_id).where(ClientProfile.user_id.in_(users))
                )
            }
            self.pharmacy_of |= self._pairs(
                select(Pharmacy.owner_user_id, Pharmacy.id).where(Pharmacy.owner_user_id.in_(users))
            )
        cases = _ids(events, "escalation")
        if cases:
            # A case is its own page; its client is who asked, when the row doesn't say.
            self.case_client = self._pairs(
                select(Escalation.id, Escalation.client_id).where(Escalation.id.in_(cases))
            )
            self.escalations = set(self.case_client)

    def _pharmacies_that_open(self, ids: set[uuid.UUID]) -> set[uuid.UUID]:
        if not ids:
            return set()
        # The admin's page of a pharmacy opens only once its email is confirmed (R-AU7,
        # `admin_pharmacies._known`).
        return set(
            self.tx.session.execute(
                select(Pharmacy.id)
                .join(User, User.id == Pharmacy.owner_user_id)
                .where(Pharmacy.id.in_(ids), User.email_verified_at.is_not(None))
            ).scalars()
        )

    def _clients_that_open(self, ids: set[uuid.UUID]) -> set[uuid.UUID]:
        if not ids:
            return set()
        # A deleted client's page still opens: it is their ID and past reservations.
        return set(
            self.tx.session.execute(
                select(ClientProfile.user_id).where(ClientProfile.user_id.in_(ids))
            ).scalars()
        )

    def client_behind(self, event: AuditEvent, subject: Subject | None) -> uuid.UUID | None:
        """The client an event is about, for a client's row that doesn't hold their ID
        (`escalation.open`, `claim.state`): its page's client, or its case's."""
        if subject is not None and subject.kind == "client":
            return subject.id
        if event.entity_type == "escalation" and event.entity_id is not None:
            return self.case_client.get(event.entity_id)
        return None

    def of(self, event: AuditEvent) -> Subject | None:
        if event.entity_type == "app_state":
            return Subject("clock")
        if event.entity_type == "answer_report":
            return Subject("reports", event.entity_id)
        found = event.entity_id
        if found is None:
            return None
        if event.entity_type == "escalation":
            return Subject("escalation", found) if found in self.escalations else None
        pharmacy = self.pharmacy_of.get(found)
        if pharmacy is not None and pharmacy in self.open_pharmacies:
            return Subject("pharmacy", pharmacy)
        client = self.client_of.get(found)
        if client is not None and client in self.open_clients:
            return Subject("client", client)
        return None


# A pharmacy found by its ID or its login's: its own ID and its name.
_PharmacyNames = dict[uuid.UUID, tuple[uuid.UUID, str]]


def _actors(events: Sequence[AuditEvent], actor: Actor) -> set[uuid.UUID]:
    return {e.actor_id for e in events if e.actor_type == actor.value and e.actor_id}


def _names(tx: Tx, events: Sequence[AuditEvent]) -> tuple[dict[uuid.UUID, str], _PharmacyNames]:
    """The admins' names and the pharmacies' names, for who did what: one query each.

    Only for rows an admin or a pharmacy did, and an admin's name only of a user who is
    an admin: a client's name is never read here (an admin sees a client as an ID)."""
    admins = _actors(events, Actor.ADMIN)
    pharmacies = _actors(events, Actor.PHARMACY)
    admin_names: dict[uuid.UUID, str] = {}
    if admins:
        found = tx.session.execute(
            select(User.id, User.full_name).where(
                User.id.in_(admins), User.role == UserRole.ADMIN.value
            )
        )
        admin_names = dict(found.tuples().all())
    pharmacy_names: _PharmacyNames = {}
    if pharmacies:
        # A pharmacy's events name it by its own ID, but its password events by its
        # login's (`auth.py`): both lead to the pharmacy.
        for pharmacy_id, owner_id, name in tx.session.execute(
            select(Pharmacy.id, Pharmacy.owner_user_id, Pharmacy.name).where(
                or_(Pharmacy.id.in_(pharmacies), Pharmacy.owner_user_id.in_(pharmacies))
            )
        ):
            pharmacy_names[pharmacy_id] = (pharmacy_id, name)
            pharmacy_names[owner_id] = (pharmacy_id, name)
    return admin_names, pharmacy_names


def _who(
    event: AuditEvent,
    client_behind: uuid.UUID | None,
    admin_names: dict[uuid.UUID, str],
    pharmacy_names: _PharmacyNames,
) -> Who:
    actor = event.actor_type
    if actor == Actor.ADMIN.value:
        return Who("admin", admin_names.get(event.actor_id) if event.actor_id else None)
    if actor == Actor.PHARMACY.value:
        found = pharmacy_names.get(event.actor_id) if event.actor_id else None
        return Who("pharmacy", found[1], found[0]) if found else Who("pharmacy")
    if actor == Actor.CLIENT.value:
        # Some of a client's events don't hold their ID; the thing it is about does.
        return Who("client", None, event.actor_id or client_behind)
    if actor == Actor.AGENT.value:
        return Who("agent")
    return Who("system")


def shown(tx: Tx, events: Sequence[AuditEvent]) -> list[Shown]:
    """A page of the log as the admin reads it (see the module's docstring)."""
    subjects = _Subjects(tx, events)
    admin_names, pharmacy_names = _names(tx, events)
    rows = []
    for event in events:
        subject = subjects.of(event)
        state_from, state_to = _states(event)
        rows.append(
            Shown(
                event=event,
                who=_who(
                    event, subjects.client_behind(event, subject), admin_names, pharmacy_names
                ),
                subject=subject,
                changed=_changed(event),
                state_from=state_from,
                state_to=state_to,
                counts=_counts(event),
                code=_code(event),
            )
        )
    return rows
