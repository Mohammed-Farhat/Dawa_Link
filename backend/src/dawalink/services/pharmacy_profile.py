"""A pharmacy's own details: registration, corrections while it waits, and its settings
(docs/04 SM-1; docs/03 PS-1, PS-2, PS-10).

Who may change what:
- **before approval** (PENDING or REJECTED) the pharmacy corrects anything it typed;
- **after approval** it changes its opening hours, its pickup time, **its phone number,
  its address and its pin** (the owner, 2026-11-16: an admin can't know that a pharmacy
  got a new number or moved). A moved pharmacy is listed at once: nothing waits for an
  admin. Its new pin is marked "to check", and an admin confirms it with one click.
  The name and the licence are what the agent shows and what the admin verified: only
  an admin changes them (docs/10 TM-D2, TH-59).

The audit log never holds a name, a licence or a phone number: it says which fields
changed, and the admin reads the current values on the pharmacy's page.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from dawalink.db.models import District, Pharmacy, PharmacyHours, TravelTimeCache
from dawalink.domain import pharmacy_details as details_rules
from dawalink.domain.accounts import PHARMACY_MACHINE, PharmacyStatus
from dawalink.domain.numbers import (
    PICKUP_TIME_MAX_DAYS,
    PICKUP_TIME_MIN_DAYS,
    TRAVEL_CACHE_TTL,
)
from dawalink.domain.opening_hours import MINUTES_PER_DAY, WeeklyHours
from dawalink.domain.state_machine import Actor
from dawalink.services import audit, notify
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

# The audit action of a pharmacy changing its own phone: the admin's page looks for it.
PHONE_CHANGED = "pharmacy.phone_changed"
# And of an approved pharmacy changing its own address, district or pin.
MOVED = "pharmacy.moved"
WHERE_FIELDS = ("address", "district_id", "lat", "lon")

# One opening range as the forms send it: (weekday, "08:00", "13:00"), Monday = 0.
HoursRow = tuple[int, str, str]


@dataclass(frozen=True)
class Details:
    """A registration, already checked and written the way it is stored."""

    name: str
    license_number: str
    phone: str
    address: str
    district_id: int
    lat: Decimal
    lon: Decimal
    pickup_days: int
    hours: WeeklyHours


def _refuse(field: str, problem: Exception | str) -> ServiceError:
    return ServiceError(Code.VALIDATION_ERROR, str(problem), field=field)


def checked_hours(rows: Sequence[HoursRow]) -> WeeklyHours:
    """Up to two ranges a day, in order, and at least one open day (R-T2)."""
    by_weekday: dict[int, list[tuple[str, str]]] = {}
    for weekday, opens, closes in rows:
        by_weekday.setdefault(weekday, []).append((opens, closes))
    try:
        hours = WeeklyHours.of(by_weekday)
    except ValueError as problem:
        raise _refuse("hours", problem) from None
    if not any(hours.by_weekday):
        raise _refuse("hours", "A pharmacy is open at least one day a week.")
    return hours


def checked_pickup_days(pickup_days: int) -> int:
    if not PICKUP_TIME_MIN_DAYS <= pickup_days <= PICKUP_TIME_MAX_DAYS:
        raise _refuse("pickup_days", "The pickup time is 1, 2 or 3 days.")
    return pickup_days


def checked(
    tx: Tx,
    *,
    name: str,
    license_number: str,
    phone: str,
    address: str,
    district_id: int,
    lat: float,
    lon: float,
    pickup_days: int,
    hours: Sequence[HoursRow],
) -> Details:
    """Every field of a registration, or the first one that is wrong and why."""
    cleaned: dict[str, str] = {}
    for field, clean, value in (
        ("name", details_rules.clean_name, name),
        ("license_number", details_rules.clean_license, license_number),
        ("phone", details_rules.clean_phone, phone),
        ("address", details_rules.clean_address, address),
    ):
        try:
            cleaned[field] = clean(value)
        except ValueError as problem:
            raise _refuse(field, problem) from None
    if tx.session.get(District, district_id) is None:
        raise _refuse("district_id", "Unknown district.")
    try:
        details_rules.check_pin(lat, lon)
    except ValueError as problem:
        raise _refuse("location", problem) from None
    return Details(
        name=cleaned["name"],
        license_number=cleaned["license_number"],
        phone=cleaned["phone"],
        address=cleaned["address"],
        district_id=district_id,
        # About one metre: a pharmacy's pin is public, like its address.
        lat=Decimal(str(round(lat, 5))),
        lon=Decimal(str(round(lon, 5))),
        pickup_days=checked_pickup_days(pickup_days),
        hours=checked_hours(hours),
    )


def check_free(tx: Tx, details: Details, *, own: uuid.UUID | None = None) -> None:
    """A licence and a phone number belong to one pharmacy (SM-1)."""
    statement = select(Pharmacy.license_number, Pharmacy.phone).where(
        or_(Pharmacy.license_number == details.license_number, Pharmacy.phone == details.phone)
    )
    if own is not None:
        statement = statement.where(Pharmacy.id != own)
    for license_number, _phone in tx.session.execute(statement):
        if license_number == details.license_number:
            raise ServiceError(
                Code.LICENSE_TAKEN, "A pharmacy with this licence number is already registered."
            )
        raise ServiceError(
            Code.PHONE_TAKEN, "A pharmacy with this phone number is already registered."
        )


def taken(problem: IntegrityError) -> ServiceError:
    """Two registrations at the same moment: the database's own rule caught the second."""
    if "license_number" in str(problem.orig):
        return ServiceError(
            Code.LICENSE_TAKEN, "A pharmacy with this licence number is already registered."
        )
    return ServiceError(
        Code.PHONE_TAKEN, "A pharmacy with this phone number is already registered."
    )


def _write_hours(tx: Tx, pharmacy_id: uuid.UUID, hours: WeeklyHours) -> None:
    tx.session.execute(delete(PharmacyHours).where(PharmacyHours.pharmacy_id == pharmacy_id))
    for weekday, ranges in enumerate(hours.by_weekday):
        for seq, opening in enumerate(ranges, start=1):
            tx.session.add(
                PharmacyHours(
                    pharmacy_id=pharmacy_id,
                    weekday=weekday,
                    seq=seq,
                    open_minute=opening.opens,
                    close_minute=opening.closes,
                )
            )


def _clock(minute: int) -> str:
    return "24:00" if minute == MINUTES_PER_DAY else f"{minute // 60:02d}:{minute % 60:02d}"


def hours_rows(hours: WeeklyHours) -> list[HoursRow]:
    """The schedule as the forms read and send it."""
    return [
        (weekday, _clock(opening.opens), _clock(opening.closes))
        for weekday, ranges in enumerate(hours.by_weekday)
        for opening in ranges
    ]


def create(tx: Tx, owner_user_id: uuid.UUID, details: Details) -> Pharmacy:
    """A new pharmacy, PENDING. It reaches the admin's queue once its email is confirmed
    (R-AU7): until then nobody has shown that the address is theirs."""
    check_free(tx, details)
    pharmacy = Pharmacy(
        id=uuid.uuid4(),
        owner_user_id=owner_user_id,
        name=details.name,
        address=details.address,
        license_number=details.license_number,
        phone=details.phone,
        district_id=details.district_id,
        lat=details.lat,
        lon=details.lon,
        pickup_days=details.pickup_days,
        status=PharmacyStatus.PENDING.value,
    )
    tx.session.add(pharmacy)
    try:
        tx.session.flush()
    except IntegrityError as problem:
        raise taken(problem) from None
    _write_hours(tx, pharmacy.id, details.hours)
    audit.record(
        tx,
        Actor.PHARMACY,
        "pharmacy.registered",
        "pharmacy",
        pharmacy.id,
        actor_id=pharmacy.id,
        after={"status": pharmacy.status, "email_confirmed": False},
    )
    return pharmacy


def email_confirmed(tx: Tx, pharmacy: Pharmacy) -> None:
    """The pharmacy confirmed its email: it is in the admin's queue from now (PN-1)."""
    audit.record(
        tx,
        Actor.PHARMACY,
        "pharmacy.in_queue",
        "pharmacy",
        pharmacy.id,
        actor_id=pharmacy.id,
        after={"status": pharmacy.status, "email_confirmed": True},
    )
    notify.notify(
        tx,
        pharmacy.owner_user_id,
        notify.Template.REGISTRATION_RECEIVED,
        {"pharmacy_name": pharmacy.name},
        event=f"pharmacy:{pharmacy.id}:registered",
    )


def _locked(tx: Tx, pharmacy_id: uuid.UUID) -> Pharmacy:
    return tx.session.execute(
        select(Pharmacy).where(Pharmacy.id == pharmacy_id).with_for_update()
    ).scalar_one()


def current(tx: Tx, pharmacy: Pharmacy, hours: WeeklyHours) -> Details:
    """What is stored now, to lay a partial change over."""
    return Details(
        name=pharmacy.name,
        license_number=pharmacy.license_number,
        phone=pharmacy.phone,
        address=pharmacy.address,
        district_id=pharmacy.district_id,
        lat=pharmacy.lat,
        lon=pharmacy.lon,
        pickup_days=pharmacy.pickup_days,
        hours=hours,
    )


# The details that are text a person typed: the audit log names them, never quotes them.
TYPED_FIELDS = ("name", "license_number", "phone", "address", "district_id", "lat", "lon")


def changed_fields(before: Details, after: Details) -> list[str]:
    """Which typed details differ: what an audit event says about an edit."""
    return [field for field in TYPED_FIELDS if getattr(before, field) != getattr(after, field)]


def forget_travel_times(tx: Tx, pharmacy_id: uuid.UUID) -> None:
    """The pin moved: the road times counted to the old one are no longer true.

    They are keyed by pharmacy, so without this the agent would weigh the old street for
    up to a day (N-43). They are made stale, not deleted: the app's login may not delete
    them, and the daily purge takes them away.
    """
    tx.session.execute(
        update(TravelTimeCache)
        .where(TravelTimeCache.pharmacy_id == pharmacy_id)
        .values(computed_at=tx.now - 2 * TRAVEL_CACHE_TTL)
    )


def checked_place(
    tx: Tx,
    before: Details,
    *,
    address: str | None,
    district_id: int | None,
    location: tuple[float, float] | None,
) -> Details:
    """`before` with a new address, district or pin, each checked as at registration."""
    after = before
    if address is not None:
        try:
            after = replace(after, address=details_rules.clean_address(address))
        except ValueError as problem:
            raise _refuse("address", problem) from None
    if district_id is not None:
        if tx.session.get(District, district_id) is None:
            raise _refuse("district_id", "Unknown district.")
        after = replace(after, district_id=district_id)
    if location is not None:
        lat, lon = location
        try:
            details_rules.check_pin(lat, lon)
        except ValueError as problem:
            raise _refuse("location", problem) from None
        after = replace(after, lat=Decimal(str(round(lat, 5))), lon=Decimal(str(round(lon, 5))))
    return after


def change_registration(tx: Tx, pharmacy_id: uuid.UUID, details: Details) -> Pharmacy:
    """A pharmacy that waits, or was rejected, corrects what it typed (PS-2)."""
    pharmacy = _locked(tx, pharmacy_id)
    status = PharmacyStatus(pharmacy.status)
    if status not in (PharmacyStatus.PENDING, PharmacyStatus.REJECTED):
        raise ServiceError(
            Code.PHARMACY_NOT_APPROVED,
            "After approval, only DawaLink's team changes these details.",
            status=status.value,
        )
    check_free(tx, details, own=pharmacy_id)
    before = current(tx, pharmacy, details.hours)
    pharmacy.name = details.name
    pharmacy.license_number = details.license_number
    pharmacy.phone = details.phone
    pharmacy.address = details.address
    pharmacy.district_id = details.district_id
    if (pharmacy.lat, pharmacy.lon) != (details.lat, details.lon):
        # A moved pin has to be looked at again.
        pharmacy.lat, pharmacy.lon = details.lat, details.lon
        pharmacy.location_checked_at = pharmacy.location_checked_by = None
    pharmacy.pickup_days = details.pickup_days
    # The admin asked for something: the pharmacy has now answered.
    pharmacy.info_requested = False
    try:
        tx.session.flush()
    except IntegrityError as problem:
        raise taken(problem) from None
    _write_hours(tx, pharmacy_id, details.hours)
    audit.record(
        tx,
        Actor.PHARMACY,
        "pharmacy.registration_edit",
        "pharmacy",
        pharmacy_id,
        actor_id=pharmacy_id,
        after={"fields": changed_fields(before, details), "status": pharmacy.status},
    )
    return pharmacy


def resubmit(tx: Tx, pharmacy_id: uuid.UUID) -> Pharmacy:
    """REJECTED → PENDING: back in the admin's queue (SM-1)."""
    pharmacy = _locked(tx, pharmacy_id)
    status = PharmacyStatus(pharmacy.status)
    if status is not PharmacyStatus.REJECTED:
        raise ServiceError(
            Code.PHARMACY_NOT_APPROVED,
            "Only a rejected registration can be sent again.",
            status=status.value,
        )
    PHARMACY_MACHINE.check(status, PharmacyStatus.PENDING, Actor.PHARMACY)
    pharmacy.status = PharmacyStatus.PENDING.value
    audit.record(
        tx,
        Actor.PHARMACY,
        "pharmacy.resubmitted",
        "pharmacy",
        pharmacy_id,
        actor_id=pharmacy_id,
        before={"status": status.value, "reason": pharmacy.status_reason},
        after={"status": pharmacy.status},
    )
    pharmacy.status_reason = None
    return pharmacy


def change_settings(
    tx: Tx,
    pharmacy_id: uuid.UUID,
    current_hours: WeeklyHours,
    *,
    hours: Sequence[HoursRow] | None = None,
    pickup_days: int | None = None,
    phone: str | None = None,
    address: str | None = None,
    district_id: int | None = None,
    location: tuple[float, float] | None = None,
) -> Pharmacy:
    """An approved pharmacy changes its hours, its pickup time, its phone, or where it
    is (PS-10).

    Reservations already made keep the deadline they were given (R-T5): a client was told
    "pick up by Tuesday 21:00", and that stays true.

    The phone is the number clients dial from an "another brand" card, so it has the
    shape of a Lebanese number, belongs to one pharmacy, and every change leaves an audit
    event of its own that the admin sees on the pharmacy's page (docs/10 TH-59).

    **A new address or pin counts at once** (the owner, 2026-11-16, Q45): clients see it,
    and travel times are counted to the new pin. The pin is no longer "checked by an
    admin" until one looks at it again, and that gates nothing.
    """
    pharmacy = _locked(tx, pharmacy_id)
    status = PharmacyStatus(pharmacy.status)
    if status is not PharmacyStatus.APPROVED:
        raise ServiceError(
            Code.PHARMACY_NOT_APPROVED,
            "Settings can be changed once the pharmacy is approved.",
            status=status.value,
        )
    before = current(tx, pharmacy, current_hours)
    after = before
    if hours is not None:
        after = replace(after, hours=checked_hours(hours))
        _write_hours(tx, pharmacy_id, after.hours)
    if pickup_days is not None:
        after = replace(after, pickup_days=checked_pickup_days(pickup_days))
        pharmacy.pickup_days = after.pickup_days
    if phone is not None:
        try:
            after = replace(after, phone=details_rules.clean_phone(phone))
        except ValueError as problem:
            raise _refuse("phone", problem) from None
    if after.phone != before.phone:
        check_free(tx, after, own=pharmacy_id)
        pharmacy.phone = after.phone
        try:
            tx.session.flush()
        except IntegrityError as problem:
            raise taken(problem) from None
        audit.record(
            tx,
            Actor.PHARMACY,
            PHONE_CHANGED,
            "pharmacy",
            pharmacy_id,
            actor_id=pharmacy_id,
            after={"fields": ["phone"]},
        )
    after = checked_place(tx, after, address=address, district_id=district_id, location=location)
    moved = [field for field in WHERE_FIELDS if getattr(before, field) != getattr(after, field)]
    if moved:
        pharmacy.address, pharmacy.district_id = after.address, after.district_id
        pharmacy.lat, pharmacy.lon = after.lat, after.lon
        pharmacy.location_checked_at = pharmacy.location_checked_by = None
        if {"lat", "lon"} & set(moved):
            forget_travel_times(tx, pharmacy_id)
        audit.record(
            tx,
            Actor.PHARMACY,
            MOVED,
            "pharmacy",
            pharmacy_id,
            actor_id=pharmacy_id,
            after={"fields": moved},
        )
    if hours is not None or pickup_days is not None:
        audit.record(
            tx,
            Actor.PHARMACY,
            "pharmacy.settings",
            "pharmacy",
            pharmacy_id,
            actor_id=pharmacy_id,
            before={"pickup_days": before.pickup_days, "hours": hours_rows(before.hours)},
            after={"pickup_days": after.pickup_days, "hours": hours_rows(after.hours)},
        )
    return pharmacy
