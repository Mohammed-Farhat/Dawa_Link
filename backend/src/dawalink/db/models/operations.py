"""Emails, notifications, the audit log, the travel-time cache and system values (docs/05 §3.8).

There is no jobs table: the clock check reads the deadlines stored on the rows themselves.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Index, Integer, Numeric, SmallInteger, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dawalink.db.base import Base
from dawalink.db.columns import (
    BigKey,
    CreatedAt,
    Moment,
    UpdatedAt,
    check,
    references,
    values_check,
)
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import OutboxState, TravelMode, TravelSource


class EmailOutbox(Base):
    """An email to send. The address is looked up when sending, never stored here."""

    __tablename__ = "email_outbox"
    __table_args__ = (
        values_check("state", OutboxState),
        check("attempts_not_negative", "attempts >= 0"),
        Index(
            "ix_email_outbox_due",
            "next_attempt_at",
            postgresql_where=text("state IN ('QUEUED', 'FAILED')"),
        ),
    )

    id: Mapped[BigKey]
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    template: Mapped[str] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # The same event never produces two emails to the same person.
    dedupe_key: Mapped[str] = mapped_column(Text, unique=True)
    state: Mapped[str] = mapped_column(Text, server_default=text("'QUEUED'"))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(Moment)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    sent_at: Mapped[datetime | None] = mapped_column(Moment)


class Notification(Base):
    """An in-app notification (docs/04 R-NT)."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", text("created_at DESC")),)

    id: Mapped[BigKey]
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    dedupe_key: Mapped[str] = mapped_column(Text, unique=True)
    read_at: Mapped[datetime | None] = mapped_column(Moment)
    created_at: Mapped[CreatedAt]


class AuditEvent(Base):
    """Who changed what. Append-only: a trigger rejects every update, and the app can't delete.

    `before` and `after` hold IDs and states only, never a name, an email or a phone number.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        values_check("actor_type", Actor),
        Index("ix_audit_events_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )

    id: Mapped[BigKey]
    occurred_at: Mapped[datetime] = mapped_column(Moment)
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # For example `order.reserve`, `claim.allocate`, `pii.view`, `clock.advance`.
    action: Mapped[str] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)


class TravelTimeCache(Base):
    """A travel time from a rounded client location to a pharmacy (docs/04 R-RT1)."""

    __tablename__ = "travel_time_cache"
    __table_args__ = (
        values_check("mode", TravelMode),
        values_check("source", TravelSource),
        check("minutes_not_negative", "minutes >= 0"),
        Index("ix_travel_time_cache_computed_at", "computed_at"),
    )

    pharmacy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, references("pharmacies.id", ondelete="CASCADE"), primary_key=True
    )
    # The client's rounded location, as "lat,lon".
    origin_cell: Mapped[str] = mapped_column(Text, primary_key=True)
    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    minutes: Mapped[int] = mapped_column(Integer)
    km: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    source: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(Moment)


class AppState(Base):
    """A few system values: when the daily tasks last ran, and the demo clock's offset."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[UpdatedAt]
