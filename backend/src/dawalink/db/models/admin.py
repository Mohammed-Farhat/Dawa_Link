"""What admins work on: escalations and abuse flags (docs/05 §3.7).

There is no priority column here or anywhere else: who gets scarce stock first can't be
changed by anyone (docs/04 R-PRI4, ADR-003).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dawalink.db.base import Base
from dawalink.db.columns import CreatedAt, Moment, UuidKey, check, references, values_check
from dawalink.domain.vocabulary import (
    EscalationReason,
    EscalationState,
    FlagRule,
    FlagSeverity,
    FlagState,
    FlagSubject,
)


class Escalation(Base):
    """A client's case handed to a person (docs/04 SM-9)."""

    __tablename__ = "escalations"
    __table_args__ = (
        values_check("reason", EscalationReason),
        values_check("state", EscalationState),
        check("summary_length", "char_length(summary) <= 300"),
        # One open escalation per client; a new one is appended to `notes`.
        Index(
            "uq_escalations_one_open",
            "client_id",
            unique=True,
            postgresql_where=text("state <> 'RESOLVED'"),
        ),
    )

    id: Mapped[UuidKey]
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    # Emptied when the conversation is purged; the escalation itself is kept.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, references("conversations.id", ondelete="SET NULL")
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("sourcing_requests.id"))
    reason: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    notes: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    state: Mapped[str] = mapped_column(Text, server_default=text("'OPEN'"))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("users.id"))
    created_at: Mapped[CreatedAt]
    resolved_at: Mapped[datetime | None] = mapped_column(Moment)


class AbuseFlag(Base):
    """Something for an admin to look at (docs/04 SM-11). Evidence holds IDs only."""

    __tablename__ = "abuse_flags"
    __table_args__ = (
        values_check("subject_type", FlagSubject),
        values_check("rule", FlagRule),
        values_check("severity", FlagSeverity),
        values_check("state", FlagState),
        # A second flag for the same thing joins the open one.
        Index(
            "uq_abuse_flags_one_open",
            "subject_type",
            "subject_id",
            "rule",
            unique=True,
            postgresql_where=text("state = 'OPEN'"),
        ),
    )

    id: Mapped[UuidKey]
    subject_type: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    rule: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    state: Mapped[str] = mapped_column(Text, server_default=text("'OPEN'"))
    action: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("users.id"))
    created_at: Mapped[CreatedAt]
    resolved_at: Mapped[datetime | None] = mapped_column(Moment)
