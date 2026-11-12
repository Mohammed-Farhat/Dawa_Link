"""Conversations, cards and the agent's own records (docs/05 §3.6, ADR-001).

Our tables are the source of truth for a conversation: LangGraph keeps nothing between turns.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dawalink.db.base import Base
from dawalink.db.columns import BigKey, CreatedAt, Moment, UuidKey, check, references, values_check
from dawalink.db.models.sourcing import RoundedCoordinate
from dawalink.domain.vocabulary import (
    AgentMode,
    ConversationKind,
    ConversationStatus,
    LocationSource,
    MessageAuthor,
    MessageKind,
    ProposalKind,
    ReportState,
    RunOutcome,
    TurnTrigger,
)


class Conversation(Base):
    """A client's chat, or the thread of one sourcing request."""

    __tablename__ = "conversations"
    __table_args__ = (
        values_check("kind", ConversationKind),
        values_check("status", ConversationStatus),
        values_check("loc_source", LocationSource),
        check("request_only_for_its_kind", "(kind = 'request') = (request_id IS NOT NULL)"),
        check("turn_attempts_not_negative", "turn_attempts >= 0"),
        # One active chat per client (decision log D9).
        Index(
            "uq_conversations_one_active_chat",
            "client_id",
            unique=True,
            postgresql_where=text("kind = 'chat' AND status = 'ACTIVE'"),
        ),
        Index("ix_conversations_client_id", "client_id"),
        # What the clock check looks for.
        Index(
            "ix_conversations_pending_turn",
            "pending_turn_at",
            postgresql_where=text("pending_turn_at IS NOT NULL"),
        ),
        Index(
            "ix_conversations_followup",
            "followup_at",
            postgresql_where=text("followup_at IS NOT NULL"),
        ),
        Index("ix_conversations_last_activity", "last_activity_at"),
    )

    id: Mapped[UuidKey]
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    kind: Mapped[str] = mapped_column(Text)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, references("sourcing_requests.id"), unique=True
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'ACTIVE'"))
    # The agent's working memory. The location is deliberately NOT in here (INV-24).
    case_state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    loc_lat: Mapped[Decimal | None] = mapped_column(RoundedCoordinate)
    loc_lon: Mapped[Decimal | None] = mapped_column(RoundedCoordinate)
    loc_source: Mapped[str | None] = mapped_column(Text)
    loc_set_at: Mapped[datetime | None] = mapped_column(Moment)
    # One agent turn at a time: whoever holds the lease runs the turn (docs/04 R-AG2).
    turn_lease_until: Mapped[datetime | None] = mapped_column(Moment)
    turn_owner: Mapped[str | None] = mapped_column(Text)
    # A decision event waiting for a turn, and how often that turn was tried (R-AG4).
    pending_turn_at: Mapped[datetime | None] = mapped_column(Moment)
    turn_attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    # One follow-up the agent scheduled for itself.
    followup_at: Mapped[datetime | None] = mapped_column(Moment)
    last_activity_at: Mapped[datetime] = mapped_column(Moment)
    created_at: Mapped[CreatedAt]


class AgentRun(Base):
    """One agent turn: what it cost and how it ended. No personal data, so it is kept."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        values_check("mode", AgentMode),
        values_check("trigger", TurnTrigger),
        values_check("outcome", RunOutcome),
        Index("ix_agent_runs_conversation_id", "conversation_id"),
        Index("ix_agent_runs_request_id", "request_id"),
        Index("ix_agent_runs_started_at", "started_at"),
    )

    id: Mapped[UuidKey]
    # Emptied, not deleted, when the conversation is purged after 30 days.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, references("conversations.id", ondelete="SET NULL")
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("sourcing_requests.id"))
    mode: Mapped[str] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(Moment)
    ended_at: Mapped[datetime | None] = mapped_column(Moment)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    tokens_out: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), server_default=text("0"))
    tool_calls: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    tool_errors: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    retries: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    outcome: Mapped[str | None] = mapped_column(Text)
    langfuse_trace_id: Mapped[str | None] = mapped_column(Text)


class AgentToolCall(Base):
    """One tool call of a turn: tool failure rates without depending on Langfuse."""

    __tablename__ = "agent_tool_calls"
    __table_args__ = (Index("ix_agent_tool_calls_agent_run_id", "agent_run_id"),)

    id: Mapped[BigKey]
    agent_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("agent_runs.id"))
    tool: Mapped[str] = mapped_column(Text)
    ok: Mapped[bool] = mapped_column(Boolean)
    error_code: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[CreatedAt]


class ChatMessage(Base):
    """One message. Personal details are removed before it is stored (INV-10)."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        values_check("author", MessageAuthor),
        values_check("kind", MessageKind),
        UniqueConstraint("conversation_id", "seq"),
    )

    id: Mapped[BigKey]
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, references("conversations.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    author: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    text_redacted: Mapped[str | None] = mapped_column(Text)
    # Proposal IDs for the agent's cards; template data for system cards.
    cards: Mapped[list[Any] | None] = mapped_column(JSONB)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("agent_runs.id"))
    created_at: Mapped[CreatedAt]


class Proposal(Base):
    """A card created by a tool. A tap sends this row's ID, and nothing else is trusted."""

    __tablename__ = "proposals"
    __table_args__ = (
        values_check("kind", ProposalKind),
        Index("ix_proposals_conversation_id", "conversation_id"),
        Index("ix_proposals_client_id", "client_id"),
    )

    id: Mapped[UuidKey]
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, references("conversations.id", ondelete="CASCADE")
    )
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    kind: Mapped[str] = mapped_column(Text)
    # Exactly what the card shows; the card is rendered from this.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("agent_runs.id"))
    expires_at: Mapped[datetime] = mapped_column(Moment)
    used_at: Mapped[datetime | None] = mapped_column(Moment)
    created_at: Mapped[CreatedAt]


class AnswerReport(Base):
    """A reply a client marked as wrong. Its redacted snapshot outlives the chat (DB-D9)."""

    __tablename__ = "answer_reports"
    __table_args__ = (
        values_check("state", ReportState),
        check("comment_length", "comment IS NULL OR char_length(comment) <= 500"),
        Index("ix_answer_reports_state", "state"),
    )

    id: Mapped[UuidKey]
    message_id: Mapped[int | None] = mapped_column(
        BigInteger, references("chat_messages.id", ondelete="SET NULL")
    )
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text, server_default=text("'NEW'"))
    category: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("users.id"))
    exported_at: Mapped[datetime | None] = mapped_column(Moment)
    created_at: Mapped[CreatedAt]
