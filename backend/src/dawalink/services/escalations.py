"""Handing a client's case to a person (docs/04 SM-9).

An escalation gives nobody any power over who gets stock: a person can reply and help,
and that is all (R-PRI4). A client has one open escalation at a time; a second ask is
added to it as a note, and it shows as a new ask on the admin's screens.

The admin's side is here too: reply, then close. A first reply says by itself that
someone is on it (OPEN → IN_PROGRESS); there is no separate "I take it" (the owner,
2026-11-19). **A reply is a message in the client's conversation**, signed "DawaLink
team", stored as the admin typed it. It never starts an agent turn.

**Once the team has replied, the chat is between the client and the team** (the owner,
2026-11-22): the client's messages there go to the team, and the assistant answers
again when the admin closes the case, or N-55 after the team's last reply there
(`held_by_team`). Nothing new is stored for it: it is worked out from the case's state
and the notes the replies leave (`{"kind": "replied", …}`).

What a case's `notes` hold (jsonb, appended to, never rewritten):
- an ask added later: `{"reason", "summary", "at", "conversation_id", "request_id"}`;
- `{"kind": "answered_in", …}`: a reply went to a chat the case did not come from;
- `{"kind": "replied", "conversation_id", "seq", "at"}`: one per team reply, `at` on the
  app's clock (R-T11);
- `{"kind": "contested_order", "order_id"}`: the reservation of a contested missed pickup.
"""

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import and_, func, select

from dawalink.db.models import ChatMessage, Conversation, Escalation, SourcingRequest
from dawalink.domain.accounts import ClientStatus
from dawalink.domain.numbers import TEAM_HOLD
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import (
    EscalationReason,
    EscalationState,
    MessageAuthor,
    MessageKind,
)
from dawalink.services import audit, clients, conversations, events, notify, paging
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

MAX_SUMMARY = 300
MAX_REPLY = 500  # SM-9
MAX_NOTE = 500
# How much of each conversation an admin reads with an escalation (A-D4: redacted).
THREAD_MESSAGES = 60
# Notes of another kind than "said later": where a reply went, each reply (see `reply`),
# and the reservation a contested missed pickup is about (see `escalate`).
ANSWERED_IN = "answered_in"
REPLIED = "replied"
CONTESTED = "contested_order"
_OWN_KINDS = (ANSWERED_IN, REPLIED, CONTESTED)
# An order number as the contest's summary writes it (`R-7K3Q2F`).
ORDER_REF = re.compile(r"\bR-[0-9A-Z]{6}\b")
# The card a chat gets when the team closes the case (rendered by the website).
TEAM_CLOSED_CARD = "team_closed"
# The card a chat gets when the team's hold ended by itself (N-55) and the client writes
# again: the assistant answers from here on.
ASSISTANT_BACK_CARD = "assistant_back"
_HAND_BACK_CARDS = (TEAM_CLOSED_CARD, ASSISTANT_BACK_CARD)


@dataclass(frozen=True)
class Escalated:
    escalation_id: uuid.UUID
    # True when the client already had an open escalation and this one joined it.
    appended: bool


# --- What a case's notes say ---------------------------------------------------------------


@dataclass(frozen=True)
class Ask:
    """One time the client was handed to a person: the case's own, or one added later."""

    reason: str
    summary: str
    # On the app's clock. None only for a note written before asks were dated.
    at: datetime | None
    conversation_id: uuid.UUID | None
    # Where it stands among the case's notes: -1 for the case's own, else its index.
    # Notes are only ever appended, so a higher place is a later one.
    place: int


@dataclass(frozen=True)
class TeamReply:
    """One reply of DawaLink's team, as the case remembers it."""

    conversation_id: uuid.UUID
    # The reply's number in that conversation: what the client wrote after it is newer.
    seq: int
    at: datetime  # the app's clock
    place: int


def _moment(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def said_later(escalation: Escalation) -> list[dict[str, Any]]:
    """The later escalations of the same client that joined this one (SM-9)."""
    return [
        note
        for note in escalation.notes
        if isinstance(note, dict) and note.get("kind") not in _OWN_KINDS
    ]


def asks(escalation: Escalation) -> list[Ask]:
    """Every ask of the case, the first one first."""
    found = [
        Ask(
            escalation.reason,
            escalation.summary,
            escalation.created_at,
            escalation.conversation_id,
            place=-1,
        )
    ]
    for place, note in enumerate(escalation.notes):
        if isinstance(note, dict) and note.get("kind") not in _OWN_KINDS:
            found.append(
                Ask(
                    str(note.get("reason", "")),
                    str(note.get("summary", "")),
                    _moment(note.get("at")),
                    _uuid(note.get("conversation_id")),
                    place=place,
                )
            )
    return found


def team_replies(escalation: Escalation) -> list[TeamReply]:
    """The team's replies the case remembers, the first one first. A reply sent before
    replies were remembered (2026-11-23) is in the chat, not here."""
    found = []
    for place, note in enumerate(escalation.notes):
        if isinstance(note, dict) and note.get("kind") == REPLIED:
            conversation_id, at = _uuid(note.get("conversation_id")), _moment(note.get("at"))
            if conversation_id is not None and at is not None:
                found.append(TeamReply(conversation_id, int(note.get("seq", 0)), at, place))
    return found


def _new_ask_since_reply(escalation: Escalation) -> bool:
    replies = team_replies(escalation)
    return bool(replies) and asks(escalation)[-1].place > replies[-1].place


# --- Opening a case -------------------------------------------------------------------------


def escalate(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    reason: EscalationReason,
    summary: str,
    conversation_id: uuid.UUID | None = None,
    request_id: uuid.UUID | None = None,
    actor: Actor = Actor.AGENT,
    contested_order: uuid.UUID | None = None,
) -> Escalated:
    """Opens an escalation, or adds to the client's open one.

    `summary` holds no personal details: the caller removes them first. Asking again with
    the same reason and summary before the team has answered changes nothing, so a turn
    that is retried doesn't write its escalation twice (R-AG6). After a reply of the
    team, the same words are a new ask, and are added.

    A case opened by a button ([I picked it up]) has no conversation: the first ask that
    joins it from a chat gives it that chat, so that the admin reads it there and the
    replies go there.

    `contested_order`: the reservation of a contested missed pickup (R-N3). The case
    remembers it in its notes, so that its page shows that reservation and how it ended,
    whatever else the client has going (B#61). An ID names no person.

    A client whose case is closed (RESOLVED) gets a new case.
    """
    summary = summary.strip()
    if not summary or len(summary) > MAX_SUMMARY:
        raise ServiceError(Code.VALIDATION_ERROR, "A summary has 1 to 300 characters.")
    # The client's profile is the first lock (docs/05 §6). A deletion holds it until its
    # open cases are closed, so a turn that was running when the client deleted their
    # account opens nothing afterwards: there is nobody left to answer (R-AU10).
    client = clients.profile(tx, client_id, lock=True)
    if client.status == ClientStatus.DELETED.value:
        raise ServiceError(Code.NOT_FOUND, "Unknown client.")
    current = tx.session.execute(
        select(Escalation)
        .where(Escalation.client_id == client_id, Escalation.state != "RESOLVED")
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    about = [_contested_note(contested_order)] if contested_order else []
    if current is None:
        created = Escalation(
            id=uuid.uuid4(),
            client_id=client_id,
            conversation_id=conversation_id,
            request_id=request_id,
            reason=reason.value,
            summary=summary,
            notes=about,
            created_at=tx.now,
        )
        tx.session.add(created)
        tx.session.flush()
        audit.record(
            tx,
            actor,
            "escalation.open",
            "escalation",
            created.id,
            after={"state": "OPEN", "reason": reason.value},
        )
        return Escalated(created.id, appended=False)

    replies = team_replies(current)
    since = replies[-1].place if replies else -2
    said = [(ask.reason, ask.summary) for ask in asks(current) if ask.place > since]
    if (reason.value, summary) not in said:
        current.notes = [
            *current.notes,
            {
                "reason": reason.value,
                "summary": summary,
                "at": tx.now.isoformat(),
                "conversation_id": str(conversation_id) if conversation_id else None,
                "request_id": str(request_id) if request_id else None,
            },
        ]
        audit.record(
            tx,
            actor,
            "escalation.append",
            "escalation",
            current.id,
            after={"reason": reason.value, "notes": len(current.notes)},
        )
    if current.conversation_id is None and conversation_id is not None:
        # A case from a button takes the chat the client asked in (see above).
        current.conversation_id = conversation_id
        if current.request_id is None:
            current.request_id = request_id
    if about and about[0] not in current.notes:
        # A contest added to a case of another kind is about its own reservation too.
        current.notes = [*current.notes, *about]
    return Escalated(current.id, appended=True)


def _contested_note(order_id: uuid.UUID) -> dict[str, str]:
    return {"kind": CONTESTED, "order_id": str(order_id)}


def contested_orders(escalation: Escalation) -> list[uuid.UUID]:
    """The reservations this case's contested missed pickups are about, as the client
    pressed them; empty for a case of another kind, or a complaint made before the case
    remembered them."""
    return [
        uuid.UUID(str(note["order_id"]))
        for note in escalation.notes
        if isinstance(note, dict) and note.get("kind") == CONTESTED
    ]


def refs_in_complaints(escalation: Escalation) -> list[str]:
    """The order numbers a complaint of this case quotes, opened as one or added later.

    For a contest made before the case remembered its reservation: the contest's summary
    always names the order ("…collected order R-7K3Q2F…"). A complaint the assistant
    wrote about something else names none, so it shows no missed pickup."""
    complaint = EscalationReason.COMPLAINT.value
    said = [escalation.summary] if escalation.reason == complaint else []
    said += [
        str(note.get("summary", ""))
        for note in said_later(escalation)
        if note.get("reason") == complaint
    ]
    return sorted({ref for text in said for ref in ORDER_REF.findall(text)})


# --- Whether the team has the chat (the owner, 2026-11-22) ----------------------------------


def _in_progress(tx: Tx, client_id: uuid.UUID) -> Escalation | None:
    """The client's case that the team has answered and not closed: there is one open
    case per client at most (`uq_escalations_one_open`)."""
    return tx.session.execute(
        select(Escalation).where(
            Escalation.client_id == client_id,
            Escalation.state == EscalationState.IN_PROGRESS.value,
        )
    ).scalar()


def _hold_ends(escalation: Escalation, conversation_id: uuid.UUID) -> datetime | None:
    """When the team's hold on this conversation ends by itself: N-55 after the team's
    last reply there. None when the team never replied there."""
    there = [
        reply for reply in team_replies(escalation) if reply.conversation_id == conversation_id
    ]
    return there[-1].at + TEAM_HOLD if there else None


def team_hold_ends_at(tx: Tx, conversation_id: uuid.UUID) -> datetime | None:
    """When the team's hold on this conversation ends by itself, or None when it is not
    held now. See `held_by_team`."""
    conversation = tx.session.get(Conversation, conversation_id)
    if conversation is None:
        return None
    if conversation.kind == "chat" and conversation.status != "ACTIVE":
        # An earlier chat is read, never written in: there is nothing to hold.
        return None
    escalation = _in_progress(tx, conversation.client_id)
    if escalation is None:
        return None
    ends = _hold_ends(escalation, conversation_id)
    return ends if ends is not None and tx.now < ends else None


def held_by_team(tx: Tx, conversation_id: uuid.UUID) -> bool:
    """True when the client's messages in this conversation go to DawaLink's team, and
    the assistant doesn't answer them (the owner, 2026-11-22; amends SM-9 and BLD-D34).

    Worked out from the tables, never stored: the conversation's client has a case that
    is IN_PROGRESS (the team replied and has not closed it), a reply of the team went to
    this conversation, and N-55 has not passed since the last one there (the app's clock).

    - OPEN (nobody replied yet): not held; the assistant still answers.
    - RESOLVED: not held.
    - An earlier chat (after [New chat]) is not held, and neither is the new chat until
      the team replies in it.
    - A case opened by a button, with no chat: nothing is held until the team replies;
      the reply goes to the client's chat, which is then held.
    - A reply sent before replies were remembered (2026-11-23) holds nothing.

    What the agent's side does with it: a held chat runs no agent turn for the client's
    messages; a held request's thread still re-plans on its events.
    """
    return team_hold_ends_at(tx, conversation_id) is not None


class AskState(StrEnum):
    """Where a client's ask for a person stands, for the agent (`person_ask`)."""

    NONE = "none"
    # Asked, and the team has not replied since the newest ask.
    ASKED = "asked"
    # The team replied after the newest ask, and the case is not closed.
    ANSWERED = "answered"
    # The newest case that touched this conversation was closed.
    CLOSED = "closed"


@dataclass(frozen=True)
class PersonAsk:
    state: AskState
    # ASKED: the newest ask; ANSWERED: the team's last reply (None for a reply sent
    # before replies were remembered); CLOSED: when it was closed. The app's clock.
    at: datetime | None
    escalation_id: uuid.UUID | None
    # This conversation is held by the team now (`held_by_team`).
    with_team: bool


def _conversations_of(escalation: Escalation) -> set[uuid.UUID]:
    """Every conversation the case came from, was asked in, or was answered in."""
    found = {ask.conversation_id for ask in asks(escalation) if ask.conversation_id}
    found |= {reply.conversation_id for reply in team_replies(escalation)}
    found |= set(_answered_in(escalation))
    return found


def person_ask(tx: Tx, client_id: uuid.UUID, conversation_id: uuid.UUID) -> PersonAsk:
    """Where the client's ask for a person stands, read from the tables (never from a
    flag kept in the agent's memory), for the agent to say the truth about it.

    - The client's open case counts whatever conversation it came from: there is one
      per client, and a person has it.
    - Else the newest closed case that touched this conversation: CLOSED, with when.
    - Else NONE.
    """
    open_case = tx.session.execute(
        select(Escalation).where(
            Escalation.client_id == client_id,
            Escalation.state != EscalationState.RESOLVED.value,
        )
    ).scalar()
    if open_case is not None:
        replies = team_replies(open_case)
        newest = asks(open_case)[-1]
        with_team = held_by_team(tx, conversation_id)
        if replies and replies[-1].place > newest.place:
            return PersonAsk(AskState.ANSWERED, replies[-1].at, open_case.id, with_team)
        if not replies and open_case.state == EscalationState.IN_PROGRESS.value:
            return PersonAsk(AskState.ANSWERED, None, open_case.id, with_team)
        return PersonAsk(AskState.ASKED, newest.at, open_case.id, with_team)
    closed = (
        tx.session.execute(
            select(Escalation)
            .where(
                Escalation.client_id == client_id,
                Escalation.state == EscalationState.RESOLVED.value,
            )
            .order_by(Escalation.resolved_at.desc().nulls_last(), Escalation.id)
        )
        .scalars()
        .all()
    )
    for case in closed:
        if conversation_id in _conversations_of(case):
            return PersonAsk(AskState.CLOSED, case.resolved_at, case.id, False)
    return PersonAsk(AskState.NONE, None, None, False)


# --- Which messages were written to the team ----------------------------------------------


def _hands_back(message: ChatMessage) -> bool:
    """A card that gives the chat back to the assistant."""
    return message.author == MessageAuthor.SYSTEM.value and any(
        isinstance(card, dict) and card.get("template") in _HAND_BACK_CARDS
        for card in message.cards or []
    )


# How far back the team's last reply or hand-back card is looked for, before the messages
# a turn reads (it reads the last 20, N-32). Further back than this, a chat counts as the
# assistant's.
_LOOK_BACK = 40


def _with_team_before(tx: Tx, conversation_id: uuid.UUID, before_seq: int) -> bool:
    """Did the team have the conversation just before message `before_seq`? True when the
    newest team reply or hand-back card before it is a team reply.

    A turn reads only its last messages: without this, a long exchange with the team
    pushes the team's reply out of that window, and the client's messages to the team
    would read as messages to the assistant (found by review, 2026-11-23).
    """
    earlier = tx.session.execute(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.seq < before_seq,
            ChatMessage.author.in_([MessageAuthor.ADMIN.value, MessageAuthor.SYSTEM.value]),
        )
        .order_by(ChatMessage.seq.desc())
        .limit(_LOOK_BACK)
    ).scalars()
    for message in earlier:
        if message.author == MessageAuthor.ADMIN.value:
            return True
        if _hands_back(message):
            return False
    return False


def to_the_team(tx: Tx, conversation_id: uuid.UUID, messages: Sequence[ChatMessage]) -> set[int]:
    """The `seq` of the client's messages, among these, that were written to DawaLink's
    team and not to the assistant: everything a client wrote after a team reply, until a
    card gave the chat back (the case was closed, or the hold ran out and the client
    wrote again).

    Only a hand-back card ends it, never a message of the assistant: in a request's
    thread the assistant still writes while the team has the thread (it re-plans on
    events), and what the client writes there is still the team's.

    Read from the messages themselves, oldest first, so nothing is stored: the agent's
    side never answers these messages, and shows them as said to the team.
    """
    found: set[int] = set()
    with_team = bool(messages) and _with_team_before(tx, conversation_id, messages[0].seq)
    for message in messages:
        if message.author == MessageAuthor.ADMIN.value:
            with_team = True
        elif _hands_back(message):
            with_team = False
        elif message.author == MessageAuthor.CLIENT.value and with_team:
            found.add(message.seq)
    return found


def team_has_the_last_word(
    tx: Tx, conversation_id: uuid.UUID, messages: Sequence[ChatMessage]
) -> bool:
    """The team replied in this conversation, and no card has given it back to the
    assistant since (`messages`: its last ones, oldest first)."""
    with_team = bool(messages) and _with_team_before(tx, conversation_id, messages[0].seq)
    for message in messages:
        if message.author == MessageAuthor.ADMIN.value:
            with_team = True
        elif _hands_back(message):
            with_team = False
    return with_team


# --- The admin's side (docs/03 AS-6) ------------------------------------------------------


@dataclass(frozen=True)
class Marks:
    """What the admin's list says about a case beside its first summary."""

    # Every reason of the case, the first one first, each once.
    reasons: list[str]
    # The newest ask: its summary and when (the app's clock).
    last_summary: str
    last_asked_at: datetime
    # The team's last reply, on the app's clock; None if none is remembered.
    last_replied_at: datetime | None
    # An ask came after the team's last reply: "New ask since your reply".
    new_ask_since_reply: bool
    # The client wrote in a chat the team replied in, after the team's last reply there:
    # when the newest such message was stored. None otherwise.
    client_wrote_at: datetime | None
    # While the team has a chat of this case: when the assistant answers again by
    # itself (N-55). None when no chat is held.
    hold_ends_at: datetime | None

    @property
    def needs_the_team(self) -> bool:
        return self.new_ask_since_reply or self.client_wrote_at is not None


def _newest_client_messages(
    tx: Tx, conversation_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, datetime]]:
    """Each conversation's newest message of the client: its number and when it was
    stored. One query for all of them."""
    ids = set(conversation_ids)
    if not ids:
        return {}
    newest = (
        select(ChatMessage.conversation_id, func.max(ChatMessage.seq).label("seq"))
        .where(
            ChatMessage.conversation_id.in_(ids),
            ChatMessage.author == MessageAuthor.CLIENT.value,
        )
        .group_by(ChatMessage.conversation_id)
        .subquery()
    )
    rows = tx.session.execute(
        select(ChatMessage.conversation_id, ChatMessage.seq, ChatMessage.created_at).join(
            newest,
            and_(
                ChatMessage.conversation_id == newest.c.conversation_id,
                ChatMessage.seq == newest.c.seq,
            ),
        )
    ).all()
    return {row.conversation_id: (int(row.seq), row.created_at) for row in rows}


def marks(tx: Tx, rows: Sequence[Escalation]) -> dict[uuid.UUID, Marks]:
    """The marks of the admin's list for these cases. Three queries at most."""
    last_reply_in: dict[uuid.UUID, dict[uuid.UUID, TeamReply]] = {}
    for row in rows:
        if row.state == EscalationState.IN_PROGRESS.value:
            last_reply_in[row.id] = {reply.conversation_id: reply for reply in team_replies(row)}
    replied_in = {conversation for there in last_reply_in.values() for conversation in there}
    newest = _newest_client_messages(tx, replied_in)
    # The chats the client still writes in (not an earlier one): only these can be held.
    writable = (
        set(
            tx.session.execute(
                select(Conversation.id).where(
                    Conversation.id.in_(replied_in),
                    (Conversation.kind == "request") | (Conversation.status == "ACTIVE"),
                )
            ).scalars()
        )
        if replied_in
        else set()
    )
    found: dict[uuid.UUID, Marks] = {}
    for row in rows:
        every = asks(row)
        replies = team_replies(row)
        wrote = [
            newest[conversation][1]
            for conversation, reply in last_reply_in.get(row.id, {}).items()
            if conversation in newest and newest[conversation][0] > reply.seq
        ]
        # As `held_by_team` says it, for each chat the team replied in: the latest end.
        holds = [
            reply.at + TEAM_HOLD
            for conversation, reply in last_reply_in.get(row.id, {}).items()
            if conversation in writable and tx.now < reply.at + TEAM_HOLD
        ]
        hold = max(holds) if holds else None
        found[row.id] = Marks(
            reasons=list(dict.fromkeys(ask.reason for ask in every)),
            last_summary=every[-1].summary,
            last_asked_at=max((ask.at for ask in every if ask.at), default=row.created_at),
            last_replied_at=replies[-1].at if replies else None,
            new_ask_since_reply=_new_ask_since_reply(row),
            client_wrote_at=max(wrote) if wrote else None,
            hold_ends_at=hold,
        )
    return found


@dataclass(frozen=True)
class Listed:
    rows: Sequence[Escalation]
    # The cases the same choice matches, whatever the page.
    total: int


def listed(
    tx: Tx, *, state: EscalationState | None = None, offset: int = 0, limit: int = 50
) -> Listed:
    """Escalations to work on. Without `state`, the ones that are not resolved.

    - **Closed cases** (`RESOLVED`): the newest closed first.
    - **Cases to work on**: emergency claims first (any of the case's asks); then the
      ones that wait for the team: never answered, a new ask since the team's reply, or
      the client wrote since it; then the answered, quiet ones. Inside each group, the
      one whose newest ask is the oldest comes first: it has waited longest.

    Cases to work on are sorted here, not in the database: what they wait for is in
    their notes and their chats. There is one per client at most, and they are closed
    when done, so they are few.
    """
    if state is EscalationState.RESOLVED:
        statement = (
            select(Escalation)
            .where(Escalation.state == EscalationState.RESOLVED.value)
            .order_by(Escalation.resolved_at.desc().nulls_last(), Escalation.id)
        )
        rows = tx.session.execute(statement.offset(offset).limit(limit)).scalars().all()
        return Listed(rows, paging.count_rows(tx, statement))

    statement = select(Escalation)
    if state is None:
        statement = statement.where(Escalation.state != EscalationState.RESOLVED.value)
    else:
        statement = statement.where(Escalation.state == state.value)
    every = tx.session.execute(statement).scalars().all()
    known = marks(tx, every)
    emergency = EscalationReason.EMERGENCY_CLAIM.value

    def order(row: Escalation) -> tuple[int, int, datetime, str]:
        mark = known[row.id]
        waits = row.state == EscalationState.OPEN.value or mark.needs_the_team
        return (
            0 if emergency in mark.reasons else 1,
            0 if waits else 1,
            mark.last_asked_at,
            str(row.id),
        )

    ordered = sorted(every, key=order)
    return Listed(ordered[offset : offset + limit], len(ordered))


def open_counts(tx: Tx) -> tuple[int, int]:
    """How many escalations are not resolved, and how many of them are emergency claims."""
    row = tx.session.execute(
        select(
            func.count(),
            func.count().filter(Escalation.reason == EscalationReason.EMERGENCY_CLAIM.value),
        ).where(Escalation.state != EscalationState.RESOLVED.value)
    ).one()
    return int(row[0]), int(row[1])


def one(tx: Tx, escalation_id: uuid.UUID) -> Escalation:
    found = tx.session.get(Escalation, escalation_id)
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown escalation.")
    return found


def request_ref(tx: Tx, escalation: Escalation) -> str | None:
    if escalation.request_id is None:
        return None
    return tx.session.execute(
        select(SourcingRequest.ref).where(SourcingRequest.id == escalation.request_id)
    ).scalar()


def _answered_in(escalation: Escalation) -> dict[uuid.UUID, int]:
    """Other conversations a reply of this escalation went to, with the reply's number:
    the client had left the chat the escalation came from (`reply`)."""
    found: dict[uuid.UUID, int] = {}
    for note in escalation.notes:
        if isinstance(note, dict) and note.get("kind") == ANSWERED_IN:
            found.setdefault(uuid.UUID(str(note["conversation_id"])), int(note["from_seq"]))
    return found


def thread_parts(tx: Tx, escalation: Escalation) -> list[list[ChatMessage]]:
    """The conversations of the case, each as it is stored, in the order they joined it:
    the one the case came from, then each chat a later ask came from, whole, and each
    chat a reply went to, from the reply on. Each shows its newest `THREAD_MESSAGES`.

    The client's and the agent's messages are without personal details (INV-10), the
    team's own replies as they were typed. Internal events are left out.

    **This is the only way an admin reads a chat** (A-D4), with the report of an answer:
    there is no list of conversations for admins.
    """

    def messages(conversation_id: uuid.UUID, from_seq: int) -> list[ChatMessage]:
        newest_first = (
            tx.session.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.seq >= from_seq,
                    ChatMessage.kind != MessageKind.EVENT.value,
                )
                .order_by(ChatMessage.seq.desc())
                .limit(THREAD_MESSAGES)
            )
            .scalars()
            .all()
        )
        return list(reversed(newest_first))

    # (conversation, from which message), the first time each joins the case.
    wanted: dict[uuid.UUID, int] = {}
    if escalation.conversation_id is not None:  # None: a button's case, or purged
        wanted[escalation.conversation_id] = 0
    for note in escalation.notes:
        if not isinstance(note, dict):
            continue
        if note.get("kind") == ANSWERED_IN:
            joined, from_seq = _uuid(note.get("conversation_id")), int(note.get("from_seq", 0))
        elif note.get("kind") in _OWN_KINDS:
            continue
        else:
            joined, from_seq = _uuid(note.get("conversation_id")), 0
        if joined is not None:
            wanted.setdefault(joined, from_seq)
    parts = [messages(conversation_id, from_seq) for conversation_id, from_seq in wanted.items()]
    # A chat purged after its 30 days has no messages left: nothing to show of it.
    return [part for part in parts if part]


def thread(tx: Tx, escalation: Escalation) -> Sequence[ChatMessage]:
    """`thread_parts`, one after the other."""
    return [message for part in thread_parts(tx, escalation) for message in part]


def _locked(tx: Tx, escalation_id: uuid.UUID) -> Escalation:
    found = tx.session.execute(
        select(Escalation)
        .where(Escalation.id == escalation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown escalation.")
    return found


def _still_open(escalation: Escalation) -> None:
    if escalation.state == EscalationState.RESOLVED.value:
        raise ServiceError(Code.CHANGED_SINCE, "This escalation is already resolved.")


def _writable(tx: Tx, conversation_id: uuid.UUID | None) -> Conversation | None:
    """The conversation if the client still sees it as theirs: a chat they write in
    now, or a request's thread (it stays on the request's page after the request
    closes). An earlier chat, put away by [New chat], is not."""
    if conversation_id is None:
        return None
    found = tx.session.get(Conversation, conversation_id)
    if found is not None and (found.kind == "request" or found.status == "ACTIVE"):
        return found
    return None


def _where_to_answer(tx: Tx, escalation: Escalation) -> Conversation:
    """The conversation the client will read the reply in, locked.

    The newest ask's conversation first, then the older ones, then the case's own: the
    client is where they asked last. A chat the client has left for a new one is no
    longer on their screen: the reply then goes to the chat they have now.
    """
    newest_first = [ask.conversation_id for ask in reversed(asks(escalation))]
    for conversation_id in newest_first:
        found = _writable(tx, conversation_id)
        if found is not None:
            return conversations.locked(tx, found.id)
    return conversations.locked(tx, conversations.active_chat(tx, escalation.client_id).id)


def reply(tx: Tx, admin_id: uuid.UUID, escalation_id: uuid.UUID, *, text: str) -> ChatMessage:
    """An admin answers the client: a "DawaLink team" message, and CN-14 (SM-9).

    **The text is stored as the admin typed it** (the owner, 2026-11-16, Q46: a person may
    have to give a phone number). It is the one message kind stored that way: whatever
    reads it for the model, a trace or an export cleans it first. The reply changes
    nothing else: **no order, no offer, no priority** (R-PRI4), and no agent turn.

    The case remembers the reply (`{"kind": "replied", …}`, on the app's clock): from it
    on, the client's messages in that conversation go to the team (`held_by_team`).
    """
    text = text.strip()
    if not text or len(text) > MAX_REPLY:
        raise ServiceError(Code.VALIDATION_ERROR, "A reply has 1 to 500 characters.", field="text")
    # The escalation first, the conversation last: the global lock order (docs/05 §6).
    escalation = _locked(tx, escalation_id)
    _still_open(escalation)
    conversation = _where_to_answer(tx, escalation)
    message = conversations.append(
        tx,
        conversation,
        author=MessageAuthor.ADMIN.value,
        kind=MessageKind.TEXT.value,
        text=text,
    )
    added: list[dict[str, Any]] = []
    if conversation.id != escalation.conversation_id and conversation.id not in _answered_in(
        escalation
    ):
        # Remembered, so that the admin's page shows the reply and what follows it.
        added.append(
            {"kind": ANSWERED_IN, "conversation_id": str(conversation.id), "from_seq": message.seq}
        )
    added.append(
        {
            "kind": REPLIED,
            "conversation_id": str(conversation.id),
            "seq": message.seq,
            "at": tx.now.isoformat(),
        }
    )
    escalation.notes = [*escalation.notes, *added]
    before = escalation.state
    escalation.state = EscalationState.IN_PROGRESS.value
    audit.record(
        tx,
        Actor.ADMIN,
        "escalation.reply",
        "escalation",
        escalation.id,
        actor_id=admin_id,
        before={"state": before},
        after={"state": escalation.state, "message_seq": message.seq},
    )
    notify.notify(
        tx,
        escalation.client_id,
        notify.Template.TEAM_REPLIED,
        {
            "conversation_id": str(conversation.id),
            "request_id": str(conversation.request_id) if conversation.request_id else None,
        },
        event=f"escalation:{escalation.id}:reply:{message.seq}",
    )
    return message


def _told_of_the_close(escalation: Escalation) -> list[uuid.UUID]:
    """Where the client is told that the case is closed: every conversation the team
    replied in; with no reply, the newest one the client asked in. Each once."""
    replied = [reply.conversation_id for reply in team_replies(escalation)]
    if replied:
        return list(dict.fromkeys(replied))
    newest = [ask.conversation_id for ask in reversed(asks(escalation)) if ask.conversation_id]
    return newest[:1]


def resolve(tx: Tx, admin_id: uuid.UUID, escalation_id: uuid.UUID, *, note: str) -> Escalation:
    """→ RESOLVED: the case is closed. A note of what was done may go with it; the
    replies already say most of it, so it is not asked for (the owner, 2026-11-19).

    The team's hold on the client's chat ends with it (`held_by_team`): the chat gets one
    `team_closed` card, which says the assistant answers again. Only a chat the client
    still sees gets it (never an earlier chat, never a new one made for it); a case from
    a button that nobody answered has no chat, and gets none. A case already closed is
    refused, so a second close posts nothing.

    The client may be escalated again afterwards: that opens a new one.
    """
    note = note.strip()
    if len(note) > MAX_NOTE:
        raise ServiceError(
            Code.VALIDATION_ERROR, "A note has 500 characters at most.", field="note"
        )
    escalation = _locked(tx, escalation_id)
    _still_open(escalation)
    before = escalation.state
    escalation.state = EscalationState.RESOLVED.value
    escalation.resolution_note = note or None
    escalation.resolved_by, escalation.resolved_at = admin_id, tx.now
    audit.record(
        tx,
        Actor.ADMIN,
        "escalation.resolve",
        "escalation",
        escalation.id,
        actor_id=admin_id,
        before={"state": before},
        after={"state": escalation.state},
    )
    # The escalation is locked first, each conversation last (docs/05 §6).
    for conversation_id in _told_of_the_close(escalation):
        if _writable(tx, conversation_id) is None:
            continue
        events.post_card(tx, conversation_id, TEAM_CLOSED_CARD)
        # Locked (by the card's own append), so a turn that is putting this chat's waiting
        # event off until the hold's end can't write over what follows.
        conversation = conversations.locked(tx, conversation_id)
        if conversation.pending_turn_at is not None and conversation.pending_turn_at > tx.now:
            # An event waited while the team had the chat (the turn was put off until
            # the hold's end): the assistant looks at it now.
            conversation.pending_turn_at = tx.now
    return escalation
