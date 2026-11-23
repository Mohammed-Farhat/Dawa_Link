"""A reply a client marked as wrong, and what an admin does with it (docs/04 SM-10;
docs/03 CS-9, AS-8).

The thumbs-down keeps **a copy** of the reply and of the few messages before it. The
copy outlives the chat, which is deleted after 30 days (DB-D9), and it holds no personal
details: the client's and the agent's messages were stored without them (INV-10), a team
reply (stored as typed) is cleaned when it is copied, and the client's comment has them
removed by the caller before it comes here.

A confirmed report can be added to the regression cases: the export is what the team
turns into tests (docs/08 §5, A-D6).
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from dawalink.db.models import AgentRun, AnswerReport, ChatMessage, Proposal
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import (
    MessageAuthor,
    MessageKind,
    ReportCategory,
    ReportReason,
    ReportState,
)
from dawalink.services import audit, conversations, paging
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

Clean = Callable[[str], str]
MAX_COMMENT = 500
# How many messages before the reply are kept with it.
CONTEXT_MESSAGES = 8


def cards_of(tx: Tx, message: ChatMessage) -> list[dict[str, Any]]:
    """What the cards under a message were: their kind and their title. Not their lines:
    a card's lines hold a pharmacy's address, which a pharmacy typed, and a copy that may
    be replayed to a model must never carry that (R-AG8)."""
    shown: list[dict[str, Any]] = []
    for card in message.cards or []:
        if isinstance(card, dict):
            shown.append({"origin": "system", "type": str(card.get("template", "status"))})
            continue
        try:
            proposal = tx.session.get(Proposal, uuid.UUID(str(card)))
        except ValueError:
            continue
        if proposal is not None and proposal.conversation_id == message.conversation_id:
            stored = proposal.payload.get("card", {})
            shown.append(
                {
                    "origin": "proposal",
                    "type": proposal.kind,
                    "title": str(stored.get("title", "")),
                    "recommended": bool(stored.get("recommended")),
                }
            )
    return shown


def _line(tx: Tx, message: ChatMessage, clean: Clean) -> dict[str, Any]:
    text = message.text_redacted
    if text and message.author == MessageAuthor.ADMIN.value:
        # A team reply is stored as typed: the copy that is kept and exported is cleaned.
        text = clean(text)
    return {
        "seq": message.seq,
        "author": message.author,
        "text": text,
        "cards": cards_of(tx, message),
        "quick_replies": [str(chip) for chip in (message.quick_replies or [])],
    }


def _snapshot(tx: Tx, conversation_kind: str, message: ChatMessage, clean: Clean) -> dict[str, Any]:
    before = (
        tx.session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == message.conversation_id,
                ChatMessage.seq < message.seq,
                ChatMessage.kind != MessageKind.EVENT.value,
            )
            .order_by(ChatMessage.seq.desc())
            .limit(CONTEXT_MESSAGES)
        )
        .scalars()
        .all()
    )
    run = tx.session.get(AgentRun, message.agent_run_id) if message.agent_run_id else None
    return {
        "conversation_kind": conversation_kind,
        "reply": _line(tx, message, clean),
        "context": [_line(tx, earlier, clean) for earlier in reversed(before)],
        "run": None
        if run is None
        else {
            "id": str(run.id),
            "mode": run.mode,
            "trigger": run.trigger,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "outcome": run.outcome,
            "guardrails": list(run.guardrails or []),
            "trace_id": run.langfuse_trace_id,
        },
    }


def reported_seqs(tx: Tx, client_id: uuid.UUID, messages: Sequence[ChatMessage]) -> set[int]:
    """Which of these messages the client has already reported."""
    ids = {message.id: message.seq for message in messages if message.author == "agent"}
    if not ids:
        return set()
    found = tx.session.execute(
        select(AnswerReport.message_id).where(
            AnswerReport.client_id == client_id, AnswerReport.message_id.in_(ids)
        )
    ).scalars()
    return {ids[message_id] for message_id in found if message_id in ids}


def report(
    tx: Tx,
    client_id: uuid.UUID,
    conversation_id: uuid.UUID,
    seq: int,
    *,
    reason: ReportReason,
    clean: Clean,
    comment: str | None = None,
) -> AnswerReport:
    """The client's thumbs-down on one of the agent's replies, once per reply.

    `comment` holds no personal details: the caller removes them first. `clean` removes
    them from a text: the copy uses it on a team reply, the one kind of message that is
    stored as typed.
    """
    comment = (comment or "").strip() or None
    if comment is not None and len(comment) > MAX_COMMENT:
        raise ServiceError(
            Code.VALIDATION_ERROR, "A comment has 500 characters at most.", field="comment"
        )
    conversations.own(tx, client_id, conversation_id)
    # The lock makes "once per reply" true for a double tap.
    conversation = conversations.locked(tx, conversation_id)
    message = tx.session.execute(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id, ChatMessage.seq == seq
        )
    ).scalar()
    if (
        message is None
        or message.author != MessageAuthor.AGENT.value
        or message.kind == MessageKind.EVENT.value
    ):
        raise ServiceError(Code.NOT_FOUND, "Only the assistant's replies can be reported.")
    already = tx.session.execute(
        select(AnswerReport.id).where(
            AnswerReport.message_id == message.id, AnswerReport.client_id == client_id
        )
    ).scalar()
    if already is not None:
        raise ServiceError(Code.ALREADY_REPORTED, "You already reported this reply.")
    created = AnswerReport(
        id=uuid.uuid4(),
        message_id=message.id,
        client_id=client_id,
        reason=reason.value,
        comment=comment,
        snapshot=_snapshot(tx, conversation.kind, message, clean),
        created_at=tx.now,
    )
    tx.session.add(created)
    tx.session.flush()
    audit.record(
        tx,
        Actor.CLIENT,
        "answer_report.new",
        "answer_report",
        created.id,
        actor_id=client_id,
        after={"state": created.state or ReportState.NEW.value, "reason": reason.value},
    )
    return created


# --- The admin's side (AS-8) --------------------------------------------------------------


@dataclass(frozen=True)
class Listed:
    rows: Sequence[AnswerReport]
    # The reports the same choice matches, whatever the page.
    total: int


def listed(
    tx: Tx, *, state: ReportState | None = ReportState.NEW, offset: int = 0, limit: int = 50
) -> Listed:
    """The reports, the newest first, with how many the choice matches in all."""
    statement = select(AnswerReport).order_by(AnswerReport.created_at.desc(), AnswerReport.id)
    if state is not None:
        statement = statement.where(AnswerReport.state == state.value)
    rows = tx.session.execute(statement.offset(offset).limit(limit)).scalars().all()
    return Listed(rows, paging.count_rows(tx, statement))


def new_count(tx: Tx) -> int:
    return tx.session.execute(
        select(func.count())
        .select_from(AnswerReport)
        .where(AnswerReport.state == ReportState.NEW.value)
    ).scalar_one()


def one(tx: Tx, report_id: uuid.UUID) -> AnswerReport:
    found = tx.session.get(AnswerReport, report_id)
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown report.")
    return found


def _new(tx: Tx, report_id: uuid.UUID) -> AnswerReport:
    found = tx.session.execute(
        select(AnswerReport)
        .where(AnswerReport.id == report_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown report.")
    if found.state != ReportState.NEW.value:
        raise ServiceError(Code.CHANGED_SINCE, "This report was already reviewed.")
    return found


def dismiss(tx: Tx, admin_id: uuid.UUID, report_id: uuid.UUID) -> AnswerReport:
    """[Not a problem]: NEW → DISMISSED."""
    found = _new(tx, report_id)
    found.state, found.reviewed_by = ReportState.DISMISSED.value, admin_id
    audit.record(
        tx,
        Actor.ADMIN,
        "answer_report.dismiss",
        "answer_report",
        found.id,
        actor_id=admin_id,
        before={"state": ReportState.NEW.value},
        after={"state": found.state},
    )
    return found


def confirm(
    tx: Tx,
    admin_id: uuid.UUID,
    report_id: uuid.UUID,
    *,
    category: ReportCategory,
    add_to_regression: bool,
) -> AnswerReport:
    """[Confirmed]: NEW → CONFIRMED, filed under a category. With `add_to_regression`
    it joins the cases the export gives (A-D6)."""
    found = _new(tx, report_id)
    found.state, found.reviewed_by = ReportState.CONFIRMED.value, admin_id
    found.category = category.value
    if add_to_regression:
        found.exported_at = tx.now
    audit.record(
        tx,
        Actor.ADMIN,
        "answer_report.confirm",
        "answer_report",
        found.id,
        actor_id=admin_id,
        before={"state": ReportState.NEW.value},
        after={
            "state": found.state,
            "category": found.category,
            "regression": add_to_regression,
        },
    )
    return found


def regression_cases(tx: Tx) -> list[dict[str, Any]]:
    """The confirmed reports that were added to the regression set, oldest first: what
    the team copies into `tests/regression/` or the regression dataset (docs/08 §5)."""
    rows = tx.session.execute(
        select(AnswerReport)
        .where(
            AnswerReport.state == ReportState.CONFIRMED.value,
            AnswerReport.exported_at.is_not(None),
        )
        .order_by(AnswerReport.created_at, AnswerReport.id)
    ).scalars()
    return [
        {
            "id": str(row.id),
            "category": row.category,
            "reason": row.reason,
            "comment": row.comment,
            "reported_at": row.created_at.isoformat(),
            **row.snapshot,
        }
        for row in rows
    ]
