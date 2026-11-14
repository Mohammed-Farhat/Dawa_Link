"""Reading pharmacies for the other services: opening hours and what a client may see."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select

from dawalink.db.models import District, Pharmacy, PharmacyHours
from dawalink.domain.opening_hours import OpenRange, WeeklyHours, closes_at, is_open
from dawalink.services.context import Tx


@dataclass(frozen=True)
class PharmacyCard:
    """What a client and the agent may know about a pharmacy. No coordinates (INV-24)."""

    id: uuid.UUID
    name: str
    address: str
    district: str
    governorate: str
    open_now: bool
    closes_at: datetime | None
    pickup_days: int


def weekly_hours(tx: Tx, pharmacy_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, WeeklyHours]:
    """Each pharmacy's weekly schedule. A pharmacy with no hours is closed every day."""
    by_pharmacy: dict[uuid.UUID, list[list[OpenRange]]] = {
        pharmacy_id: [[] for _ in range(7)] for pharmacy_id in pharmacy_ids
    }
    rows = tx.session.execute(
        select(PharmacyHours)
        .where(PharmacyHours.pharmacy_id.in_(pharmacy_ids))
        .order_by(PharmacyHours.pharmacy_id, PharmacyHours.weekday, PharmacyHours.open_minute)
    ).scalars()
    for row in rows:
        by_pharmacy[row.pharmacy_id][row.weekday].append(
            OpenRange(row.open_minute, row.close_minute)
        )
    return {
        pharmacy_id: WeeklyHours(tuple(tuple(day) for day in week))
        for pharmacy_id, week in by_pharmacy.items()
    }


def cards(
    tx: Tx, pharmacy_ids: Sequence[uuid.UUID], hours: dict[uuid.UUID, WeeklyHours]
) -> dict[uuid.UUID, PharmacyCard]:
    rows = tx.session.execute(
        select(Pharmacy, District.name, District.governorate)
        .join(District, District.id == Pharmacy.district_id)
        .where(Pharmacy.id.in_(pharmacy_ids))
    ).all()
    return {
        pharmacy.id: PharmacyCard(
            id=pharmacy.id,
            name=pharmacy.name,
            address=pharmacy.address,
            district=district,
            governorate=governorate,
            open_now=is_open(hours[pharmacy.id], tx.now),
            closes_at=closes_at(hours[pharmacy.id], tx.now),
            pickup_days=pharmacy.pickup_days,
        )
        for pharmacy, district, governorate in rows
    }


def day_hours(hours: WeeklyHours, day: date) -> str:
    """The opening hours of one day, as "08:00-13:00, 16:00-21:00", or "closed"."""
    ranges = hours.on(day)
    if not ranges:
        return "closed"
    return ", ".join(
        f"{r.opens // 60:02d}:{r.opens % 60:02d}-{r.closes // 60:02d}:{r.closes % 60:02d}"
        for r in ranges
    )


def hours_text(tx: Tx, pharmacy_id: uuid.UUID, day: date | None) -> str | None:
    """A pharmacy's opening hours on one day, as "08:00-13:00, 16:00-21:00"."""
    if day is None:
        return None
    ranges = weekly_hours(tx, [pharmacy_id])[pharmacy_id].on(day)
    return ", ".join(
        f"{r.opens // 60:02d}:{r.opens % 60:02d}-{r.closes // 60:02d}:{r.closes % 60:02d}"
        for r in ranges
    )
