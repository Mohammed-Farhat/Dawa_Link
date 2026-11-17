"""The admin's side of a pharmacy's account (docs/04 SM-1; docs/03 AS-3, AS-4).

An admin approves, rejects or asks for more information, and corrects a pharmacy's
details. Three things hold everywhere here:

- **an approval is of what the admin saw.** A pharmacy that waits can still correct its
  details, so [Approve] carries the version of the details that were on the screen, and
  is refused if they changed since;
- **only a registration whose email was confirmed is in the queue** (R-AU7): until then
  nobody has shown that the address is theirs;
- **the audit log never quotes a detail.** It names the fields that changed and holds
  the admin's reason; the current values are on the pharmacy's page.

An admin never touches a pharmacy's stock or prices (A-D7): nothing here does.
"""

import hashlib
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.selectable import Exists

from dawalink.catalog.composition import normalize
from dawalink.db.models import AuditEvent, District, Order, Pharmacy, User
from dawalink.domain import pharmacy_details as details_rules
from dawalink.domain.accounts import PHARMACY_MACHINE, PharmacyStatus
from dawalink.domain.orders import OrderState
from dawalink.domain.state_machine import Actor, TransitionNotAllowed
from dawalink.services import (
    audit,
    early_release,
    matching,
    notify,
    orders,
    pharmacies,
    pharmacy_profile,
)
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError


@dataclass(frozen=True)
class Listed:
    pharmacy: Pharmacy
    district: str
    # The pharmacy moved its address or its pin after approval, and no admin has looked.
    pin_to_check: bool


@dataclass(frozen=True)
class Detail:
    pharmacy: Pharmacy
    district: str
    # The login's email: a business contact, shown to the admin who checks the registration.
    email: str
    # What [Approve] sends back: the details as they were when this was read.
    version: str
    # Other pharmacies registered at the same address (SM-1's duplicate check). A licence,
    # a phone and an email can't be shared at all: the database refuses a second one.
    same_address: list[Pharmacy]
    # When the pharmacy last changed its own phone number, if it ever did (the owner, Q42).
    phone_changed_at: datetime | None
    # When it last changed its own address or pin (the owner, Q45), and whether an admin
    # has looked at the pin since.
    moved_at: datetime | None
    pin_to_check: bool


def details_version(pharmacy: Pharmacy) -> str:
    """A fingerprint of what an admin checks: name, licence, phone, address, pin."""
    checked = (
        pharmacy.name,
        pharmacy.license_number,
        pharmacy.phone,
        pharmacy.address,
        str(pharmacy.district_id),
        str(pharmacy.lat),
        str(pharmacy.lon),
    )
    return hashlib.sha256("\x1f".join(checked).encode()).hexdigest()[:16]


def _email_confirmed_clause() -> Exists:
    """The pharmacy's login followed the link of its confirmation email (R-AU7)."""
    return (
        select(User.id)
        .where(User.id == Pharmacy.owner_user_id, User.email_verified_at.is_not(None))
        .exists()
    )


def _pin_to_check_clause() -> ColumnElement[bool]:
    """An approved pharmacy moved, and no admin has looked at its pin since. (A pharmacy
    that never moved is not counted, whatever its record says: the demo pharmacies were
    never "checked" by anyone.)"""
    moved = (
        select(AuditEvent.id)
        .where(
            AuditEvent.entity_type == "pharmacy",
            AuditEvent.entity_id == Pharmacy.id,
            AuditEvent.action == pharmacy_profile.MOVED,
        )
        .exists()
    )
    return and_(
        Pharmacy.status == PharmacyStatus.APPROVED.value,
        Pharmacy.location_checked_at.is_(None),
        moved,
    )


def listed(
    tx: Tx,
    *,
    status: PharmacyStatus | None = None,
    query: str = "",
    offset: int = 0,
    limit: int = 50,
) -> list[Listed]:
    """Pharmacies for the admin's lists. With `PENDING` it is the approval queue, the
    registration that has waited longest first."""
    to_check = _pin_to_check_clause()
    statement = (
        select(Pharmacy, District.name, to_check)
        .join(District, District.id == Pharmacy.district_id)
        .where(_email_confirmed_clause())
    )
    if status is not None:
        statement = statement.where(Pharmacy.status == status.value)
    typed = query.strip()
    if typed:
        like = "%" + typed.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        statement = statement.where(
            or_(Pharmacy.name.ilike(like), Pharmacy.license_number.ilike(like))
        )
    order = (
        (Pharmacy.created_at, Pharmacy.id)
        if status is PharmacyStatus.PENDING
        # What needs a look comes first.
        else (to_check.desc(), func.lower(Pharmacy.name), Pharmacy.id)
    )
    rows = tx.session.execute(statement.order_by(*order).offset(offset).limit(limit))
    return [Listed(pharmacy, district, bool(check)) for pharmacy, district, check in rows]


def pins_to_check_count(tx: Tx) -> int:
    return tx.session.execute(
        select(func.count())
        .select_from(Pharmacy)
        .where(_pin_to_check_clause(), _email_confirmed_clause())
    ).scalar_one()


def waiting_count(tx: Tx) -> int:
    return tx.session.execute(
        select(func.count())
        .select_from(Pharmacy)
        .where(Pharmacy.status == PharmacyStatus.PENDING.value, _email_confirmed_clause())
    ).scalar_one()


def _known(tx: Tx, pharmacy_id: uuid.UUID, *, lock: bool = False) -> Pharmacy:
    """A pharmacy an admin may look at: one whose email was confirmed."""
    statement = select(Pharmacy).where(Pharmacy.id == pharmacy_id, _email_confirmed_clause())
    if lock:
        statement = statement.with_for_update(of=Pharmacy).execution_options(populate_existing=True)
    pharmacy = tx.session.execute(statement).scalar()
    if pharmacy is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown pharmacy.")
    return pharmacy


def detail(tx: Tx, pharmacy_id: uuid.UUID) -> Detail:
    pharmacy = _known(tx, pharmacy_id)
    owner = tx.session.get_one(User, pharmacy.owner_user_id)
    district = tx.session.get_one(District, pharmacy.district_id)
    wanted = normalize(pharmacy.address)
    same_address = [
        other
        for other in tx.session.execute(
            select(Pharmacy).where(
                Pharmacy.id != pharmacy.id,
                Pharmacy.district_id == pharmacy.district_id,
                # One an admin can open: an unconfirmed registration is nobody yet.
                _email_confirmed_clause(),
            )
        ).scalars()
        if normalize(other.address) == wanted
    ]

    def last(action: str) -> datetime | None:
        return tx.session.execute(
            select(func.max(AuditEvent.occurred_at)).where(
                AuditEvent.entity_type == "pharmacy",
                AuditEvent.entity_id == pharmacy.id,
                AuditEvent.action == action,
            )
        ).scalar()

    moved_at = last(pharmacy_profile.MOVED)
    return Detail(
        pharmacy=pharmacy,
        district=district.name,
        email=owner.email,
        version=details_version(pharmacy),
        same_address=same_address,
        phone_changed_at=last(pharmacy_profile.PHONE_CHANGED),
        moved_at=moved_at,
        pin_to_check=(
            pharmacy.status == PharmacyStatus.APPROVED.value
            and pharmacy.location_checked_at is None
            and moved_at is not None
        ),
    )


def _changed_since(message: str) -> ServiceError:
    return ServiceError(Code.CHANGED_SINCE, message)


def _move(pharmacy: Pharmacy, target: PharmacyStatus) -> PharmacyStatus:
    """Checks SM-1 for an admin and moves the pharmacy. Returns where it was."""
    before = PharmacyStatus(pharmacy.status)
    try:
        PHARMACY_MACHINE.check(before, target, Actor.ADMIN)
    except TransitionNotAllowed:
        # Another admin acted first, or the screen is old.
        raise _changed_since("This pharmacy's status changed: look at it again.") from None
    pharmacy.status = target.value
    return before


def approve(tx: Tx, admin_id: uuid.UUID, pharmacy_id: uuid.UUID, *, seen: str) -> Pharmacy:
    """PENDING → APPROVED (SM-1): the inventory and the listings unlock, and the pin
    counts as checked. `seen` is the version of the details the admin had on the screen."""
    pharmacy = _known(tx, pharmacy_id, lock=True)
    if details_version(pharmacy) != seen:
        raise _changed_since("The pharmacy corrected its details: look at them again.")
    before = _move(pharmacy, PharmacyStatus.APPROVED)
    pharmacy.approved_at = tx.now
    pharmacy.location_checked_at, pharmacy.location_checked_by = tx.now, admin_id
    pharmacy.info_requested, pharmacy.status_reason = False, None
    audit.record(
        tx,
        Actor.ADMIN,
        "pharmacy.approve",
        "pharmacy",
        pharmacy.id,
        actor_id=admin_id,
        before={"status": before.value},
        after={"status": pharmacy.status},
    )
    notify.notify(
        tx,
        pharmacy.owner_user_id,
        notify.Template.APPROVED,
        {"pharmacy_name": pharmacy.name},
        event=f"pharmacy:{pharmacy.id}:approved",
    )
    return pharmacy


def check_pin(tx: Tx, admin_id: uuid.UUID, pharmacy_id: uuid.UUID) -> Pharmacy:
    """An admin looked at the pin on the map and it is on the address: after a pharmacy
    moved by itself (the owner, Q45). Saying it twice changes nothing."""
    pharmacy = _known(tx, pharmacy_id, lock=True)
    if pharmacy.location_checked_at is None:
        pharmacy.location_checked_at, pharmacy.location_checked_by = tx.now, admin_id
        audit.record(
            tx,
            Actor.ADMIN,
            "pharmacy.pin_checked",
            "pharmacy",
            pharmacy.id,
            actor_id=admin_id,
            after={"status": pharmacy.status, "pin_checked": True},
        )
    return pharmacy


def reject(tx: Tx, admin_id: uuid.UUID, pharmacy_id: uuid.UUID, *, reason: str) -> Pharmacy:
    """PENDING → REJECTED, with the reason the pharmacy reads (PN-3). It may correct its
    details and send the registration again."""
    reason = audit.required_reason(reason)
    pharmacy = _known(tx, pharmacy_id, lock=True)
    before = _move(pharmacy, PharmacyStatus.REJECTED)
    pharmacy.status_reason, pharmacy.info_requested = reason, False
    audit.record(
        tx,
        Actor.ADMIN,
        "pharmacy.reject",
        "pharmacy",
        pharmacy.id,
        actor_id=admin_id,
        before={"status": before.value},
        after={"status": pharmacy.status},
        reason=reason,
    )
    notify.notify(
        tx,
        pharmacy.owner_user_id,
        notify.Template.REJECTED,
        {"pharmacy_name": pharmacy.name, "team_message": reason},
        event=f"pharmacy:{pharmacy.id}:rejected:{tx.now.isoformat()}",
    )
    return pharmacy


def request_info(tx: Tx, admin_id: uuid.UUID, pharmacy_id: uuid.UUID, *, message: str) -> Pharmacy:
    """The registration stays PENDING; the pharmacy reads what is missing and corrects
    its details, which clears the mark (SM-1)."""
    message = audit.required_reason(message)
    pharmacy = _known(tx, pharmacy_id, lock=True)
    if pharmacy.status != PharmacyStatus.PENDING.value:
        raise _changed_since("This pharmacy's status changed: look at it again.")
    pharmacy.info_requested, pharmacy.status_reason = True, message
    audit.record(
        tx,
        Actor.ADMIN,
        "pharmacy.request_info",
        "pharmacy",
        pharmacy.id,
        actor_id=admin_id,
        after={"status": pharmacy.status, "info_requested": True},
        reason=message,
    )
    notify.notify(
        tx,
        pharmacy.owner_user_id,
        notify.Template.MORE_INFORMATION,
        {"pharmacy_name": pharmacy.name, "team_message": message},
        event=f"pharmacy:{pharmacy.id}:info:{tx.now.isoformat()}",
    )
    return pharmacy


def edit(
    tx: Tx,
    admin_id: uuid.UUID,
    pharmacy_id: uuid.UUID,
    *,
    reason: str,
    name: str | None = None,
    license_number: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    district_id: int | None = None,
    location: tuple[float, float] | None = None,
) -> Pharmacy:
    """An admin corrects a pharmacy's details, in any status (SM-1, audited).

    **Only what is sent is checked**, each field with the rule of the registration form
    (`domain/pharmacy_details.py`): the name is what the AI shows to clients (R-AG8), so
    it stays letters, digits and a few marks. A pin the admin moves counts as checked.
    """
    reason = audit.required_reason(reason)
    pharmacy = _known(tx, pharmacy_id, lock=True)
    weekly = pharmacies.weekly_hours(tx, [pharmacy.id])[pharmacy.id]
    before = pharmacy_profile.current(tx, pharmacy, weekly)
    typed: dict[str, str] = {}
    for field, clean, value in (
        ("name", details_rules.clean_name, name),
        ("license_number", details_rules.clean_license, license_number),
        ("phone", details_rules.clean_phone, phone),
        ("address", details_rules.clean_address, address),
    ):
        if value is None:
            continue
        try:
            typed[field] = clean(value)
        except ValueError as problem:
            raise ServiceError(Code.VALIDATION_ERROR, str(problem), field=field) from None
    after = replace(
        before,
        name=typed.get("name", before.name),
        license_number=typed.get("license_number", before.license_number),
        phone=typed.get("phone", before.phone),
        address=typed.get("address", before.address),
    )
    if district_id is not None:
        if tx.session.get(District, district_id) is None:
            raise ServiceError(Code.VALIDATION_ERROR, "Unknown district.", field="district_id")
        after = replace(after, district_id=district_id)
    if location is not None:
        lat, lon = location
        try:
            details_rules.check_pin(lat, lon)
        except ValueError as problem:
            raise ServiceError(Code.VALIDATION_ERROR, str(problem), field="location") from None
        after = replace(after, lat=Decimal(str(round(lat, 5))), lon=Decimal(str(round(lon, 5))))
    changed = pharmacy_profile.changed_fields(before, after)
    if not changed:
        return pharmacy
    if {"license_number", "phone"} & set(changed):
        pharmacy_profile.check_free(tx, after, own=pharmacy.id)
    pharmacy.name, pharmacy.license_number = after.name, after.license_number
    pharmacy.phone, pharmacy.address = after.phone, after.address
    pharmacy.district_id = after.district_id
    if {"lat", "lon"} & set(changed):
        pharmacy.lat, pharmacy.lon = after.lat, after.lon
        pharmacy.location_checked_at, pharmacy.location_checked_by = tx.now, admin_id
        pharmacy_profile.forget_travel_times(tx, pharmacy.id)
    try:
        tx.session.flush()
    except IntegrityError as problem:
        raise pharmacy_profile.taken(problem) from None
    audit.record(
        tx,
        Actor.ADMIN,
        "pharmacy.admin_edit",
        "pharmacy",
        pharmacy.id,
        actor_id=admin_id,
        after={"fields": changed, "status": pharmacy.status},
        reason=reason,
    )
    return pharmacy


def suspend(tx: Tx, admin_id: uuid.UUID, pharmacy_id: uuid.UUID, *, reason: str) -> Pharmacy:
    """APPROVED → SUSPENDED (SM-1). Its listings stop being visible at once (a listing is
    visible only while its pharmacy is approved, INV-16). The offers that hold one of its
    boxes are cancelled, and the asks it had not answered are withdrawn. **What clients
    have already reserved is kept**: the pharmacy can still hand those boxes over.
    """
    reason = audit.required_reason(reason)
    pharmacy = _known(tx, pharmacy_id, lock=True)
    before = _move(pharmacy, PharmacyStatus.SUSPENDED)
    if before is not PharmacyStatus.APPROVED:
        raise _changed_since("Only an approved pharmacy can be suspended.")
    pharmacy.status_reason = reason
    offered = list(
        tx.session.execute(
            select(Order.id).where(
                Order.pharmacy_id == pharmacy.id, Order.state == OrderState.OFFERED.value
            )
        ).scalars()
    )
    cancelled = 0
    for order_id in offered:
        done = orders.cancel_by_system(tx, order_id, reason="the pharmacy was suspended")
        cancelled += done is not None
    withdrawn = early_release.withdraw_asks_of_pharmacy(tx, pharmacy.id)
    audit.record(
        tx,
        Actor.ADMIN,
        "pharmacy.suspend",
        "pharmacy",
        pharmacy.id,
        actor_id=admin_id,
        before={"status": before.value},
        after={
            "status": pharmacy.status,
            "offers_cancelled": cancelled,
            "asks_withdrawn": withdrawn,
        },
        reason=reason,
    )
    notify.notify(
        tx,
        pharmacy.owner_user_id,
        notify.Template.ACCOUNT_CHANGED,
        {"pharmacy_name": pharmacy.name, "account_state": "suspended", "team_message": reason},
        event=f"pharmacy:{pharmacy.id}:suspended:{tx.now.isoformat()}",
    )
    return pharmacy


def reinstate(tx: Tx, admin_id: uuid.UUID, pharmacy_id: uuid.UUID, *, reason: str) -> Pharmacy:
    """SUSPENDED → APPROVED (SM-1): its listings are visible again, and the clients who
    wait for a medicine it has are served (R-PRI1)."""
    reason = audit.required_reason(reason)
    pharmacy = _known(tx, pharmacy_id, lock=True)
    before = PharmacyStatus(pharmacy.status)
    if before is not PharmacyStatus.SUSPENDED:
        raise _changed_since("Only a suspended pharmacy can be reinstated.")
    _move(pharmacy, PharmacyStatus.APPROVED)
    pharmacy.status_reason = None
    for group in matching.groups_with_waiting_claims(tx):
        matching.defer(tx, group)
    audit.record(
        tx,
        Actor.ADMIN,
        "pharmacy.reinstate",
        "pharmacy",
        pharmacy.id,
        actor_id=admin_id,
        before={"status": before.value},
        after={"status": pharmacy.status},
        reason=reason,
    )
    notify.notify(
        tx,
        pharmacy.owner_user_id,
        notify.Template.ACCOUNT_CHANGED,
        {"pharmacy_name": pharmacy.name, "account_state": "active again", "team_message": reason},
        event=f"pharmacy:{pharmacy.id}:reinstated:{tx.now.isoformat()}",
    )
    return pharmacy
