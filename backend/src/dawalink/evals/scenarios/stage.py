"""The stage a scenario plays on: one database, one clock, and every actor at the door a
real one uses.

- **The client** writes, taps and cancels through the API, exactly as the website does
  (`Person`). So the checks of the routes count too: the team's hold on a chat, the
  limits, the tap's re-validation.
- **A pharmacy** marks a box picked up or not available, and answers the agent's asks,
  through its own routes (`PharmacyActor`).
- **An admin** reads the escalations, replies and closes a case (`AdminActor`).
- **Time** moves when the scenario says so, and the worker's clock check and the agent's
  own turns then run until nothing is left (`Stage.settle`).

What happened is kept twice: as a transcript a person or a judge can read
(`Stage.transcript`), and as `Turn` objects with the agent's tool calls from the trace.
A scenario states what it expects with `Stage.check`.
"""

import json
import math
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent.guards.redact import redact
from dawalink.agent.llm.base import ChatModel
from dawalink.agent.pending import PendingTurns
from dawalink.agent.turn import Agent
from dawalink.db.models import (
    Claim,
    ClientProfile,
    Conversation,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    Escalation,
    InventoryItem,
    Order,
    Pharmacy,
    PharmacyHours,
    Product,
    RequestItem,
    SourcingRequest,
    User,
)
from dawalink.domain.clock import ManualClock, at_beirut, beirut, beirut_date
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.datasets import Match
from dawalink.evals.scenarios import faults
from dawalink.evals.scenarios.client_model import Brief, Lang, Line, next_message
from dawalink.evals.score_understanding import ToolUse, seen_in
from dawalink.services import auth
from dawalink.services.clock_check import ClockTasks
from dawalink.services.context import unit_of_work
from dawalink.sim import world
from dawalink.sim.engine import NoEmails

API = "/api/v1"
MONDAY = date(2026, 11, 16)  # the Monday the evaluation's world is written for
Level = Literal["component", "step", "trajectory", "end_to_end"]
Family = Literal[
    "task_success",
    "output_quality",
    "tool_use",
    "planning",
    "memory",
    "efficiency",
    "reliability",
    "safety",
]
# A text is one string for every language, or one per language: {"en": .., "az": .., "ar": ..}.
Text = str | Mapping[str, str]
_SHORT: dict[Lang, str] = {"english": "en", "arabizi": "az", "arabic": "ar"}
MAX_SETTLE_ROUNDS = 8
# The test client's own answer type: only its status, JSON and content are read.
Response = Any


class StageError(Exception):
    """The scenario asked the stage for something it can't do: a mistake in the scenario
    or in the harness, never a finding about the agent."""


@dataclass(frozen=True)
class Medicine:
    """One product of the catalog, found by the name a person would write."""

    id: uuid.UUID
    name: str  # as the Ministry writes it
    strength: str | None
    form: str | None
    pack: str | None
    needs_prescription: bool
    public_price_lbp: int
    equivalence_key: str | None
    search_name: str


@dataclass(frozen=True)
class Card:
    id: str
    # reserve, reserve_group, cancel, request_summary, other_brand, ... or a system card's type
    kind: str
    origin: str  # "proposal": made by a tool of the agent; "system": a template card
    title: str
    lines: tuple[str, ...]
    recommended: bool
    state: str  # open, used, expired
    button: str | None
    prescription_notice: bool
    item_keys: tuple[str, ...]  # the checkboxes of a [Reserve these] card
    item_labels: tuple[str, ...]
    has_call_number: bool
    data: Mapping[str, Any]
    box: Mapping[str, Any] | None

    def says(self) -> str:
        """The card in one line, as a person reads it."""
        parts = [self.kind, self.title, *self.lines, *self.item_labels]
        box = self.box or {}
        price, travel = box.get("price"), box.get("travel")
        if isinstance(price, dict) and price.get("lbp") is not None:
            parts.append(f"price: {price['lbp']:,} LBP")
        if box.get("expiry_date"):
            parts.append(f"expires: {box['expiry_date']}")
        if isinstance(travel, dict):
            about = "about " if travel.get("source") == "straight" else ""
            parts.append(
                f"travel: {about}{travel.get('car_min')} min by car, "
                f"{travel.get('walk_min')} on foot"
            )
        if self.recommended:
            parts.append("(recommended)")
        if self.prescription_notice:
            parts.append("(prescription needed)")
        if self.button:
            parts.append(f"[{self.button}]")
        return " | ".join(part for part in parts if part)

    def mentions(self, words: str) -> bool:
        return words.lower() in self.says().lower()


@dataclass
class Turn:
    """What followed one thing the client wrote (or, with `said=None`, what the agent did
    on its own after an event)."""

    conversation: str
    said: str | None
    status: int = 200  # the API's answer to the message
    error: str | None = None  # the API's error code, when it refused the message
    with_team: bool = False  # the message went to DawaLink's team: no agent turn
    reply: str = ""  # the agent's words (several replies joined by a blank line)
    cards: list[Card] = field(default_factory=list)  # under the agent's replies
    quick_replies: list[str] = field(default_factory=list)
    system_cards: list[Card] = field(default_factory=list)  # template cards, no model
    team_said: list[str] = field(default_factory=list)  # a person of DawaLink's team
    tools: list[ToolUse] = field(default_factory=list)  # from the trace, in order
    agent_turns: int = 0  # how many agent turns ran
    outcomes: list[str] = field(default_factory=list)  # each turn's outcome in the trace
    seconds: float = 0.0
    cost_usd: float = 0.0
    model_calls: int = 0
    seqs: list[int] = field(default_factory=list)  # the seq of each agent reply

    def called(self, name: str) -> list[ToolUse]:
        return [tool for tool in self.tools if tool.name == name]

    def tool_names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    @property
    def kinds(self) -> list[str]:
        return [card.kind for card in self.cards]

    def card(self, kind: str) -> Card | None:
        """The card of this kind to act on: the recommended one, else the first."""
        mine = [card for card in self.cards if card.kind == kind]
        return next((card for card in mine if card.recommended), mine[0] if mine else None)

    @property
    def answered(self) -> bool:
        return self.agent_turns > 0 and bool(self.reply)


@dataclass(frozen=True)
class Tap:
    status: int
    error: str | None
    kind: str | None
    refs: tuple[str, ...]  # the order numbers of what was reserved
    request_ref: str | None
    message: str
    turns: tuple[Turn, ...]  # what the agent did because of the tap

    @property
    def ok(self) -> bool:
        return self.status < 400


@dataclass(frozen=True)
class Check:
    id: str
    ok: bool
    level: Level
    family: Family
    detail: str = ""
    auto: bool = False  # added to every scenario by code, not written by the scenario


def _error_code(response: Response) -> str | None:
    if response.status_code < 400:
        return None
    try:
        return str(response.json()["error"]["code"])
    except Exception:
        return f"HTTP_{response.status_code}"


def _card(raw: Mapping[str, Any]) -> Card:
    lines = tuple(
        ": ".join(str(value) for value in line.values() if value not in (None, "", [], {}))
        if isinstance(line, dict)
        else str(line)
        for line in raw.get("lines") or []
    )
    items = raw.get("selectable_items") or []
    return Card(
        id=str(raw["card_id"]),
        kind=str(raw["type"]),
        origin=str(raw["origin"]),
        title=str(raw.get("title") or ""),
        lines=lines,
        recommended=bool(raw.get("recommended")),
        state=str(raw.get("state")),
        button=raw.get("action_label"),
        prescription_notice=bool(raw.get("prescription_notice")),
        item_keys=tuple(str(item["item_key"]) for item in items),
        item_labels=tuple(str(item["label"]) for item in items),
        has_call_number=bool(raw.get("call_number")),
        data=raw.get("data") or {},
        box=raw.get("box"),
    )


class _Actor:
    def __init__(self, stage: "Stage", user_id: uuid.UUID) -> None:
        self.stage = stage
        self.user_id = user_id
        with unit_of_work(stage.sessions, stage.clock) as tx:
            token = auth.start_session(tx, tx.session.get_one(User, user_id)).token
        self._auth = {"Authorization": f"Bearer {token}"}

    def api(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        key: bool = False,
    ) -> Response:
        """Any route of the API, as this actor. `key=True` adds an idempotency key."""
        headers = dict(self._auth)
        if key:
            headers["Idempotency-Key"] = uuid.uuid4().hex
        return self.stage.http.request(
            method, f"{API}{path}", json=json, params=dict(params or {}), headers=headers
        )

    def _must(self, response: Response, what: str) -> Any:
        if response.status_code >= 400:
            raise StageError(f"{what}: {response.status_code} {_error_code(response)}")
        return response.json() if response.content else None


class Person(_Actor):
    """A client, at the website."""

    def __init__(self, stage: "Stage", who: world.SimClient) -> None:
        super().__init__(stage, who.id)
        self.who = who
        self.chat: str | None = None
        self._seen_seq: dict[str, int] = {}
        self._seen_traces: dict[str, int] = {}
        self._lines: dict[str, list[Line]] = {}
        self.turns: list[Turn] = []
        self.left: str | None = None  # why the played client stopped writing

    # --- the chat ------------------------------------------------------------------------

    def open_chat(self, *, share_location: bool = True) -> str:
        """Opens the assistant. With `share_location` the phone's location is shared, as
        after "Use my location"; without, the agent has what the profile says."""
        ref = self._must(self.api("GET", "/conversations/active-chat"), "open the chat")
        self.chat = str(ref["conversation_id"])
        if share_location:
            self._must(
                self.api(
                    "PUT",
                    f"/conversations/{self.chat}/location",
                    json={"lat": self.who.lat, "lon": self.who.lon},
                ),
                "share the location",
            )
        return self.chat

    def new_chat(self) -> str:
        ref = self._must(self.api("POST", "/conversations/new-chat"), "start a new chat")
        self.chat = str(ref["conversation_id"])
        self.stage.note("client", "pressed [New chat]")
        return self.chat

    def say(self, text: Text, *, in_request: str | None = None) -> Turn:
        """Writes one message, in the chat or in a request's thread (`in_request`: its
        number, `Q-...`), and waits for what follows."""
        words = self.stage.t(text)
        conversation = self.stage.thread_of(in_request) if in_request else self.chat
        if conversation is None:
            conversation = self.open_chat()
        response = self.api(
            "POST",
            f"/conversations/{conversation}/messages",
            json={"text": words, "client_message_id": str(uuid.uuid4())},
        )
        with_team = False
        if response.status_code == 202:
            with_team = bool(response.json().get("with_team"))
            if not with_team:
                self.stage.run_worker()  # a thread's turn is the worker's
        return self._collect(
            conversation,
            said=words,
            status=response.status_code,
            error=_error_code(response),
            with_team=with_team,
        )

    def converse(
        self,
        *,
        until: Callable[[Turn], bool] | None = None,
        max_messages: int = 4,
        brief: Brief | None = None,
        in_request: str | None = None,
    ) -> list[Turn]:
        """The played client keeps writing, from the scenario's brief, until `until` says
        so (by default: until the agent shows a card), it leaves, or `max_messages`."""
        conversation = self.stage.thread_of(in_request) if in_request else self.chat
        if conversation is None:
            conversation = self.open_chat()
        done = until or (lambda turn: bool(turn.cards))
        turns: list[Turn] = []
        for _ in range(max_messages):
            said = next_message(
                self.stage.client_model,
                brief or self.stage.brief,
                self.stage.lang,
                self._lines.get(conversation, []),
            )
            if said.left:
                self.left = said.why or "left"
                self.stage.note("client", f"stopped writing ({self.left})")
                break
            turn = self.say(said.text, in_request=in_request)
            turns.append(turn)
            if done(turn) or turn.error is not None:
                break
        return turns

    def answer(self, *, brief: Brief | None = None, in_request: str | None = None) -> Turn | None:
        """The played client writes exactly one message: its answer to what the agent
        last said. None when it chose to stop."""
        turns = self.converse(
            until=lambda _: True, max_messages=1, brief=brief, in_request=in_request
        )
        return turns[0] if turns else None

    # --- taps ----------------------------------------------------------------------------

    def tap(self, card: Card | str, *, items: Sequence[str] | None = None) -> Tap:
        """Presses a card's button. `card` is the card, or a kind: then it is the newest
        open card of that kind (the recommended one when several came together)."""
        if isinstance(card, str):
            found = self._open_card(card)
            if found is None:
                raise StageError(f"No open card of kind {card!r} to tap.")
            card = found
        response = self.api(
            "POST",
            f"/proposals/{card.id}/execute",
            json={"selected_item_keys": list(items) if items is not None else None},
            key=True,
        )
        body = response.json() if response.status_code < 400 else {}
        refs = tuple(str(made["ref"]) for made in body.get("reservations") or [])
        self.stage.note(
            "client",
            f'tapped [{card.button or card.kind}] on the card "{card.title}": '
            + (
                (body.get("message") or "done")
                if response.status_code < 400
                else f"refused ({_error_code(response)})"
            ),
        )
        turns = tuple(self.stage.settle())
        return Tap(
            response.status_code,
            _error_code(response),
            body.get("kind"),
            refs,
            body.get("request_ref"),
            str(body.get("message") or ""),
            turns,
        )

    def _open_card(self, kind: str) -> Card | None:
        for turn in reversed(self.turns):
            mine = [card for card in turn.cards if card.kind == kind and card.state == "open"]
            if mine:
                return next((card for card in mine if card.recommended), mine[0])
        return None

    # --- the rest of the website -----------------------------------------------------------

    def reservations(self) -> list[dict[str, Any]]:
        return list(self._must(self.api("GET", "/reservations"), "list reservations")["items"])

    def cancel(self, ref: str) -> Response:
        """[Cancel] on a reservation's ticket (not through the chat)."""
        order_id = self.stage.order_id(ref)
        response = self.api("POST", f"/reservations/{order_id}/cancel")
        self.stage.note("client", f"cancelled reservation {ref} on its ticket")
        self.stage.settle()
        return response

    def offers(self) -> list[dict[str, Any]]:
        return list(self._must(self.api("GET", "/offers"), "list offers")["items"])

    def accept_offer(
        self, offer_id: str | None = None, *, pickup_day: date | None = None
    ) -> Response:
        """[Accept and reserve] on an offer: the first one, or the one given; for the
        soonest day the offer allows, or `pickup_day`."""
        offers = self.offers()
        offer = next((o for o in offers if str(o["id"]) == offer_id), offers[0] if offers else None)
        if offer is None:
            raise StageError("There is no offer to accept.")
        day = pickup_day.isoformat() if pickup_day else offer["pickup_days_allowed"][0]
        response = self.api(
            "POST", f"/offers/{offer['id']}/accept", json={"pickup_day": day}, key=True
        )
        self.stage.note(
            "client",
            f"pressed [Accept and reserve] on the offer, to pick up on {day}"
            if response.status_code < 400
            else f"tried to accept the offer: refused ({_error_code(response)})",
        )
        self.stage.settle()
        return response

    def thumbs_down(self, turn: Turn, reason: str = "wrong_information") -> Response:
        seq = turn.seqs[-1]
        response = self.api(
            "POST",
            f"/conversations/{turn.conversation}/messages/{seq}/report",
            json={"reason": reason},
        )
        self.stage.note("client", f"pressed the thumbs-down on the last reply ({reason})")
        return response

    # --- reading what happened -------------------------------------------------------------

    def _collect(
        self,
        conversation: str,
        *,
        said: str | None,
        status: int = 200,
        error: str | None = None,
        with_team: bool = False,
    ) -> Turn:
        turn = Turn(conversation, said, status, error, with_team)
        lines = self._lines.setdefault(conversation, [])
        if said is not None:
            shown = redact(said).text
            self.stage.note(
                "client",
                shown if error is None else f"{shown}  [refused: {error}]",
                conversation=conversation,
            )
            if error is None:
                lines.append(Line("you", said))
        page = self._must(
            self.api(
                "GET",
                f"/conversations/{conversation}/messages",
                params={"after_seq": self._seen_seq.get(conversation, 0), "limit": 50},
            ),
            "read the messages",
        )
        replies: list[str] = []
        for message in page["messages"]:
            self._seen_seq[conversation] = max(
                self._seen_seq.get(conversation, 0), int(message["seq"])
            )
            author = message["author"]
            cards = [_card(raw) for raw in message.get("cards") or []]
            text = message.get("text") or ""
            if author == "client":
                continue
            if author == "agent":
                replies.append(text)
                turn.cards += [card for card in cards if card.origin == "proposal"]
                turn.system_cards += [card for card in cards if card.origin != "proposal"]
                turn.quick_replies += list(message.get("quick_replies") or [])
                turn.seqs.append(int(message["seq"]))
                self.stage.note(
                    "agent",
                    text,
                    conversation=conversation,
                    cards=[card.says() for card in cards],
                    quick_replies=list(message.get("quick_replies") or []),
                )
                lines.append(Line("assistant", text, tuple(card.says() for card in cards)))
            elif author == "admin":
                turn.team_said.append(text)
                self.stage.note("team", redact(text).text, conversation=conversation)
                lines.append(Line("team", text))
            else:
                turn.system_cards += cards
                words = text or "; ".join(card.says() for card in cards)
                self.stage.note("app", words, conversation=conversation)
                lines.append(Line("app", words))
        turn.reply = "\n\n".join(reply for reply in replies if reply)
        traced = self.stage.traced(conversation)
        fresh = traced[self._seen_traces.get(conversation, 0) :]
        self._seen_traces[conversation] = len(traced)
        for trace in fresh:
            seen = seen_in(trace)
            turn.tools += list(seen.tools)
            turn.agent_turns += 1
            turn.outcomes.append(seen.outcome)
            turn.seconds += seen.seconds
            turn.cost_usd += seen.cost_usd
            turn.model_calls += seen.model_calls
            self.stage.note(
                "trace",
                f"agent turn: outcome {seen.outcome}, {seen.model_calls} model calls, "
                f"{seen.seconds:.1f}s",
                conversation=conversation,
                tools=[
                    {
                        "name": tool.name,
                        "arguments": tool.arguments,
                        "ok": tool.ok,
                        "answer": tool.answer[:1500],
                    }
                    for tool in seen.tools
                ],
            )
        if said is not None or turn.agent_turns or turn.system_cards or turn.team_said:
            self.turns.append(turn)
            self.stage.turns.append(turn)
        return turn

    def catch_up(self) -> list[Turn]:
        """What appeared in this client's conversations since they were last read."""
        with self.stage.read() as session:
            conversations = [
                str(found)
                for found in session.execute(
                    select(Conversation.id)
                    .where(Conversation.client_id == self.user_id)
                    .order_by(Conversation.created_at, Conversation.id)
                ).scalars()
            ]
        news = []
        for conversation in conversations:
            turn = self._collect(conversation, said=None)
            if turn.agent_turns or turn.system_cards or turn.team_said or turn.reply:
                news.append(turn)
        return news


class PharmacyActor(_Actor):
    """A pharmacist, in the pharmacy's portal."""

    def __init__(self, stage: "Stage", pharmacy: world.SimPharmacy) -> None:
        super().__init__(stage, pharmacy.owner_id)
        self.pharmacy = pharmacy

    def not_available(self, ref: str, *, units: int | None = None) -> Response:
        """[Not available] on a reservation: the box was sold at the counter."""
        response = self.api(
            "POST",
            f"/pharmacy/reservations/{self.stage.order_id(ref)}/not-available",
            json={"units": units},
        )
        self.stage.note("pharmacy", f"{self.pharmacy.name} marked {ref} [Not available]")
        self.stage.settle()
        return response

    def picked_up(self, ref: str) -> Response:
        response = self.api(
            "POST", f"/pharmacy/reservations/{self.stage.order_id(ref)}/picked-up", json={}
        )
        self.stage.note("pharmacy", f"{self.pharmacy.name} marked {ref} [Picked up]")
        self.stage.settle()
        return response

    def asks(self) -> list[dict[str, Any]]:
        """The agent's open asks to this pharmacy ("a client needs 2 packs…")."""
        found = self._must(self.api("GET", "/pharmacy/early-release-asks"), "list the asks")
        return list(found["items"] if isinstance(found, dict) else found)

    def accept_ask(self, ask_id: str, *, qty: int = 1, price_lbp: int | None = None) -> Response:
        """[Accept] on an ask, at the price the pharmacy types (the public price less a
        quarter when none is given)."""
        if price_lbp is None:
            with self.stage.read() as session:
                ask = session.get_one(EarlyReleaseAsk, uuid.UUID(ask_id))
                public = session.get_one(Product, ask.product_id).public_price_lbp
            price_lbp = int(public * 0.75)
        response = self.api(
            "POST",
            f"/pharmacy/early-release-asks/{ask_id}/accept",
            json={"qty": qty, "price_lbp": price_lbp},
        )
        self.stage.note(
            "pharmacy",
            f"{self.pharmacy.name} accepted the ask ({qty} at {price_lbp} LBP)"
            if response.status_code < 400
            else f"{self.pharmacy.name} tried to accept the ask: {_error_code(response)}",
        )
        self.stage.settle()
        return response

    def decline_ask(self, ask_id: str, reason: str = "keeping_it") -> Response:
        response = self.api(
            "POST", f"/pharmacy/early-release-asks/{ask_id}/decline", json={"reason": reason}
        )
        self.stage.note("pharmacy", f"{self.pharmacy.name} declined the ask ({reason})")
        self.stage.settle()
        return response

    def add_stock(self, medicine: Medicine, *, days: int = 120, qty: int = 2) -> Response:
        """A new box typed in the inventory: listed at once when its expiry is within the
        pharmacy's rule, and offered to whoever waits for it."""
        response = self.api(
            "POST",
            "/pharmacy/inventory/items",
            json={
                "product_id": str(medicine.id),
                "batch": f"N{uuid.uuid4().hex[:8].upper()}",
                "expiry_date": (self.stage.today + timedelta(days=days)).isoformat(),
                "qty": qty,
            },
        )
        self.stage.note(
            "pharmacy",
            f"{self.pharmacy.name} added {qty} box(es) of {medicine.name} "
            f"({days} days before expiry)",
        )
        self.stage.settle()
        return response


class AdminActor(_Actor):
    """Someone of DawaLink's team, in the admin console."""

    def escalations(self, state: str | None = None) -> list[dict[str, Any]]:
        params = {"state": state} if state else {}
        found = self._must(self.api("GET", "/admin/escalations", params=params), "escalations")
        return list(found["items"])

    def reply(self, escalation_id: str, text: Text) -> Response:
        words = self.stage.t(text)
        response = self.api(
            "POST", f"/admin/escalations/{escalation_id}/reply", json={"text": words}
        )
        self.stage.note("team", f"(admin replies) {redact(words).text}")
        self.stage.settle()
        return response

    def close(self, escalation_id: str, note: str = "") -> Response:
        response = self.api(
            "POST", f"/admin/escalations/{escalation_id}/resolve", json={"note": note}
        )
        self.stage.note("team", "(admin pressed [Close this case])")
        self.stage.settle()
        return response


class Faults:
    """Failures a scenario switches on (see `faults.py`)."""

    def __init__(self, stage: "Stage", model: faults.FlakyModel) -> None:
        self._stage = stage
        self._model = model

    def _key(self) -> faults.Key:
        return faults.key_of(self._stage.sessions, self._stage.client.user_id)

    def tool(self, name: str, *, times: int | None = 1) -> None:
        """The next `times` calls of this tool fail as a crash does (`None`: every call)."""
        faults.break_tool(self._key(), name, times=times)
        self._stage.note("fault", f"the tool {name} fails " + (f"{times}x" if times else "always"))

    def model(self, *, calls: int) -> None:
        """The model's provider doesn't answer the next `calls` calls."""
        self._model.fail_next = calls
        self._stage.note("fault", f"the model's provider fails its next {calls} call(s)")

    def clear(self) -> None:
        faults.mend_tools(self._key())
        self._model.fail_next = 0
        self._stage.note("fault", "every fault is cleared")


class Stage:
    """One scenario's world. See the module's docstring, and `cases/README.md` for how a
    scenario is written."""

    def __init__(
        self,
        *,
        lang: Lang,
        http: TestClient,
        sessions: sessionmaker[Session],
        setup_sessions: sessionmaker[Session],
        clock: ManualClock,
        agent: Agent,
        lands: world.World,
        client_model: ChatModel,
        flaky: faults.FlakyModel,
        traces: Path,
        brief: Brief,
        client_district: str,
    ) -> None:
        self.lang: Lang = lang
        self.http = http
        self.sessions = sessions
        self._setup_sessions = setup_sessions
        self.clock = clock
        self.agent = agent
        self.lands = lands
        self.client_model = client_model
        self.brief = brief
        self._traces = traces
        self.transcript: list[dict[str, Any]] = []
        self.checks: list[Check] = []
        self.turns: list[Turn] = []
        self._people: dict[int, Person] = {}
        self._tasks = ClockTasks(sessions, clock, mailer=NoEmails(), batch=500)
        with self.read() as session:
            self._catalog = CatalogNames.load(session)
        self.client = self.person(district=client_district)
        self.fault = Faults(self, flaky)
        self._admin: AdminActor | None = None

    # --- words -----------------------------------------------------------------------------

    def t(self, text: Text) -> str:
        """The text in this run's language."""
        if isinstance(text, str):
            return text
        short = _SHORT[self.lang]
        if short not in text:
            raise StageError(f"This text has no {short!r} version: {dict(text)}")
        return text[short]

    def note(self, who: str, text: str, **more: Any) -> None:
        self.transcript.append(
            {"at": beirut(self.clock.now()).strftime("%a %H:%M"), "who": who, "text": text}
            | {key: value for key, value in more.items() if value not in (None, [], "")}
        )

    def check(self, id: str, ok: bool, *, level: Level, family: Family, detail: str = "") -> bool:
        """States one thing this scenario expects. `detail` says what was seen instead."""
        self.checks.append(Check(id, bool(ok), level, family, "" if ok else detail))
        return bool(ok)

    # --- people ----------------------------------------------------------------------------

    def person(self, *, district: str | None = None, n: int | None = None) -> Person:
        """A client. The first of `district` (or number `n`) who isn't on the stage yet."""
        for who in self.lands.clients:
            if who.n in self._people and who.n != n:
                continue
            if n is not None and who.n != n:
                continue
            if district is not None and who.district != district:
                continue
            if who.n not in self._people:
                self._people[who.n] = Person(self, who)
            return self._people[who.n]
        raise StageError(f"No free client in {district!r} (n={n}).")

    def pharmacy(self, pharmacy: world.SimPharmacy) -> PharmacyActor:
        return PharmacyActor(self, pharmacy)

    @property
    def admin(self) -> AdminActor:
        if self._admin is None:
            admin_id = uuid.uuid4()
            with self.setup() as session:
                session.execute(
                    insert(User),
                    [
                        {
                            "id": admin_id,
                            "email": "admin@sim.dawalink.test",
                            "password_hash": world.NO_PASSWORD,
                            "role": "admin",
                            "full_name": "Sim Admin",
                            "email_verified_at": self.clock.now(),
                            # An admin row must hold a two-factor secret; nobody logs in
                            # with this one (the stage makes its session itself).
                            "totp_secret": b"sim-invented-not-a-secret",
                        }
                    ],
                )
            self._admin = AdminActor(self, admin_id)
        return self._admin

    # --- the catalog and the shelves ---------------------------------------------------------

    def medicine(self, name: str, strength: str | None = None, form: str | None = None) -> Medicine:
        """The product a person means by this name ("concor", "5mg")."""
        found = sorted(
            self._catalog.products_for(Match(name=name, strength=strength, form=form)), key=str
        )
        if not found:
            raise StageError(f"The catalog has no {name} {strength or ''} {form or ''}.")
        return self._medicine(found[0])

    def _medicine(self, product_id: uuid.UUID) -> Medicine:
        with self.read() as session:
            product = session.get_one(Product, product_id)
            return Medicine(
                product.id,
                product.moph_name,
                product.dosage_text,
                product.form_text,
                product.presentation_text,
                product.prescription_required,
                product.public_price_lbp,
                product.equivalence_key,
                product.search_name,
            )

    def same_medicine_ids(self, medicine: Medicine) -> set[uuid.UUID]:
        """Every catalog row that is this very medicine: the same name, ingredient,
        strength and form, whatever the box size or the maker (R-C10, "same name, same
        medicine")."""
        with self.read() as session:
            same = set(
                session.execute(
                    select(Product.id).where(
                        Product.search_name == medicine.search_name,
                        Product.equivalence_key == medicine.equivalence_key,
                    )
                ).scalars()
            )
        return same | {medicine.id}

    def other_brand_of(self, medicine: Medicine) -> Medicine:
        """Another brand with the same ingredient, strength and form (R-C10)."""
        with self.read() as session:
            other = session.execute(
                select(Product.id)
                .where(
                    Product.equivalence_key == medicine.equivalence_key,
                    Product.equivalence_key.is_not(None),
                    Product.search_name != medicine.search_name,
                    Product.controlled.is_(False),
                )
                .order_by(Product.moph_name, Product.id)
                .limit(1)
            ).scalar()
        if other is None:
            raise StageError(f"{medicine.name} has no other brand in the catalog.")
        return self._medicine(other)

    def pharmacies(self, district: str | None = None) -> list[world.SimPharmacy]:
        return [p for p in self.lands.pharmacies if district is None or p.district == district]

    def nearest(
        self, k: int = 1, *, to: Person | None = None, district: str | None = None
    ) -> list[world.SimPharmacy]:
        """The `k` pharmacies nearest to the client, in a straight line."""
        who = (to or self.client).who

        def far(pharmacy: world.SimPharmacy) -> float:
            return math.hypot(pharmacy.lat - who.lat, (pharmacy.lon - who.lon) * 0.83)

        return sorted(self.pharmacies(district), key=far)[:k]

    def stock(
        self,
        medicine: Medicine,
        pharmacy: world.SimPharmacy,
        *,
        days: int = 120,
        qty: int = 3,
        listing: Literal["LIVE", "LISTED", "PAUSED"] = "LIVE",
        price_lbp: int | None = None,
    ) -> uuid.UUID:
        """Puts a box on a pharmacy's shelf **before** the story starts: `days` until its
        expiry (181 to 270 is the early-release zone, private), `qty` units. Nobody is
        told and nothing is matched: use `PharmacyActor.add_stock` for stock that arrives
        while a client waits."""
        item_id = uuid.uuid4()
        with self.setup() as session:
            session.execute(
                insert(InventoryItem),
                [
                    {
                        "id": item_id,
                        "pharmacy_id": pharmacy.id,
                        "product_id": medicine.id,
                        "batch": f"S{item_id.hex[:8].upper()}",
                        "expiry_date": self.today + timedelta(days=days),
                        "qty_on_hand": qty,
                        "listing_control": listing,
                        "price_override_lbp": price_lbp,
                        "last_edited_at": self.clock.now(),
                    }
                ],
            )
        return item_id

    def set_pharmacy(
        self,
        pharmacy: world.SimPharmacy,
        *,
        auto_list_days: int | None = None,
        pickup_days: int | None = None,
        closed_today: bool = False,
    ) -> None:
        """Changes a pharmacy before the story starts: its listing rule (N-54), its pickup
        time, or no opening hours today."""
        values: dict[str, Any] = {}
        if auto_list_days is not None:
            values["auto_list_days"] = auto_list_days
        if pickup_days is not None:
            values["pickup_days"] = pickup_days
        with self.setup() as session:
            if values:
                session.execute(update(Pharmacy).where(Pharmacy.id == pharmacy.id).values(**values))
            if closed_today:
                session.execute(
                    delete(PharmacyHours).where(
                        PharmacyHours.pharmacy_id == pharmacy.id,
                        PharmacyHours.weekday == self.today.weekday(),
                    )
                )

    def forget_home(self, person: Person | None = None) -> None:
        """The client's profile says nowhere they live: with no shared location, the agent
        knows no place at all for them."""
        with self.setup() as session:
            session.execute(
                update(ClientProfile)
                .where(ClientProfile.user_id == (person or self.client).user_id)
                .values(district_id=None, home_area_id=None, home_lat=None, home_lon=None)
            )

    # --- time ------------------------------------------------------------------------------

    @property
    def now(self) -> datetime:
        return self.clock.now()

    @property
    def today(self) -> date:
        return beirut_date(self.clock.now())

    def advance(self, *, minutes: int = 0, hours: int = 0) -> list[Turn]:
        """Time passes; then everything due happens (`settle`)."""
        self.clock.advance(timedelta(minutes=minutes, hours=hours))
        self.note("clock", f"{hours * 60 + minutes} minutes pass")
        return self.settle()

    def run_worker(self) -> int:
        """One pass of the worker: the clock check's tasks, then the agent's waiting turns."""
        done = 0
        for step in (
            self._tasks.expire_offers,
            self._tasks.expire_reservations,
            self._tasks.expire_asks,
            self._tasks.resolve_early_release,
            self._tasks.send_pickup_reminders,
            self._tasks.lift_pauses,
            self._tasks.run_window_checks,
            self._tasks.end_windows,
            self._tasks.expire_watches,
            self._tasks.matching_sweep,
        ):
            while (acted := step()) > 0:
                done += acted
        done += PendingTurns(self.agent).run_pending_turns()
        return done

    def settle(self) -> list[Turn]:
        """Runs the worker until nothing is left, then returns what appeared in the
        clients' conversations (the agent's own turns, template cards, a team reply)."""
        for _ in range(MAX_SETTLE_ROUNDS):
            if self.run_worker() == 0:
                break
        news: list[Turn] = []
        for person in list(self._people.values()):
            news += person.catch_up()
        return news

    # --- reading the tables ------------------------------------------------------------------

    @contextmanager
    def read(self) -> Iterator[Session]:
        """A session to look at the tables with (the app's own login)."""
        with self.sessions() as session:
            yield session

    @contextmanager
    def setup(self) -> Iterator[Session]:
        """A session that may write anything, **for setting the scene only**: what happens
        in the story goes through an actor."""
        with self._setup_sessions() as session:
            yield session
            session.commit()

    def traced(self, conversation: str) -> list[dict[str, Any]]:
        path = self._traces / "turns.jsonl"
        if not path.exists():
            return []
        turns = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        return [t for t in turns if str(t["metadata"].get("conversation_id")) == conversation]

    def thread_of(self, request_ref: str) -> str:
        with self.read() as session:
            found = session.execute(
                select(Conversation.id)
                .join(SourcingRequest, SourcingRequest.id == Conversation.request_id)
                .where(SourcingRequest.ref == request_ref)
            ).scalar()
        if found is None:
            raise StageError(f"No request {request_ref}.")
        return str(found)

    def order_id(self, ref: str) -> uuid.UUID:
        with self.read() as session:
            found = session.execute(select(Order.id).where(Order.ref == ref)).scalar()
        if found is None:
            raise StageError(f"No reservation {ref}.")
        return found

    def orders(self, person: Person | None = None) -> list[dict[str, Any]]:
        """The client's reservations and offers, oldest first: `ref`, `state` (OFFERED,
        RESERVED, PICKED_UP, NOT_AVAILABLE, EXPIRED_NO_SHOW, CANCELLED_BY_CLIENT,
        CANCELLED_BY_SYSTEM), `medicine`, `product_id`, `pharmacy`, `pharmacy_id`, `qty`,
        `pickup_day`, `days_of_use`, `price_lbp`, `source`, `expiry_date`."""
        with self.read() as session:
            rows = session.execute(
                select(Order, Product.moph_name, Pharmacy.name, InventoryItem.expiry_date)
                .join(Product, Product.id == Order.product_id)
                .join(Pharmacy, Pharmacy.id == Order.pharmacy_id)
                .join(InventoryItem, InventoryItem.id == Order.inventory_item_id)
                .where(Order.client_id == (person or self.client).user_id)
                .order_by(Order.created_at, Order.id)
            ).all()
            return [
                {
                    "ref": order.ref,
                    "state": order.state,
                    "medicine": medicine,
                    "product_id": order.product_id,
                    "pharmacy": pharmacy,
                    "pharmacy_id": order.pharmacy_id,
                    "qty": order.qty_locked,
                    "pickup_day": order.pickup_day,
                    "days_of_use": order.days_of_use,
                    "price_lbp": order.price_snapshot_lbp,
                    "source": order.source,
                    "expiry_date": expiry,
                }
                for order, medicine, pharmacy, expiry in rows
            ]

    def claims(self, person: Person | None = None) -> list[dict[str, Any]]:
        """What the client waits for: `kind` (watch or request item), `source`, `state`,
        `product_id`, `medicine`, `qty_missing`, `days_of_use`, `max_price_lbp`."""
        with self.read() as session:
            rows = session.execute(
                select(Claim, Product.moph_name)
                .join(Product, Product.id == Claim.product_id)
                .where(Claim.client_id == (person or self.client).user_id)
                .order_by(Claim.created_at, Claim.id)
            ).all()
            return [
                {
                    "id": claim.id,
                    "kind": claim.kind,
                    "source": claim.source,
                    "state": claim.state,
                    "product_id": claim.product_id,
                    "medicine": medicine,
                    "qty_missing": claim.qty_missing,
                    "days_of_use": claim.days_of_use,
                    "max_price_lbp": claim.max_price_lbp,
                }
                for claim, medicine in rows
            ]

    def asks(self, person: Person | None = None) -> list[dict[str, Any]]:
        """The asks sent to pharmacies for this client: `id`, `state` (ASKED, ACCEPTED,
        DECLINED, EXPIRED, WITHDRAWN), `pharmacy_id`, `pharmacy`, `product_id`."""
        with self.read() as session:
            rows = session.execute(
                select(EarlyReleaseAsk, Pharmacy.name)
                .join(EarlyReleaseRequest, EarlyReleaseRequest.id == EarlyReleaseAsk.er_request_id)
                .join(Pharmacy, Pharmacy.id == EarlyReleaseAsk.pharmacy_id)
                .where(EarlyReleaseRequest.client_id == (person or self.client).user_id)
                .order_by(EarlyReleaseAsk.created_at, EarlyReleaseAsk.id)
            ).all()
            return [
                {
                    "id": str(ask.id),
                    "state": ask.state,
                    "pharmacy_id": ask.pharmacy_id,
                    "pharmacy": pharmacy,
                    "product_id": ask.product_id,
                }
                for ask, pharmacy in rows
            ]

    def requests(self, person: Person | None = None) -> list[dict[str, Any]]:
        """The client's sourcing requests: `ref`, `state` (OPEN, CLOSED), `outcome`, and
        `items`: each with `product_id`, `medicine`, `qty`, `qty_secured`, `state`."""
        with self.read() as session:
            found = []
            for request in session.execute(
                select(SourcingRequest)
                .where(SourcingRequest.client_id == (person or self.client).user_id)
                .order_by(SourcingRequest.created_at, SourcingRequest.id)
            ).scalars():
                items = session.execute(
                    select(RequestItem, Product.moph_name)
                    .join(Product, Product.id == RequestItem.product_id)
                    .where(RequestItem.request_id == request.id)
                    .order_by(RequestItem.position)
                ).all()
                found.append(
                    {
                        "ref": request.ref,
                        "state": request.state,
                        "outcome": request.outcome,
                        "ends_at": request.ends_at,
                        "items": [
                            {
                                "product_id": item.product_id,
                                "medicine": medicine,
                                "qty": item.qty,
                                "qty_secured": item.qty_secured,
                                "state": item.state,
                                "days_of_use": item.days_of_use,
                                "max_price_lbp": item.max_price_lbp,
                            }
                            for item, medicine in items
                        ],
                    }
                )
            return found

    def escalations(self, person: Person | None = None) -> list[dict[str, Any]]:
        """The client's cases for DawaLink's team: `id`, `reason` (client_asked_human,
        emergency_claim, complaint, ...), `state` (OPEN, IN_PROGRESS, RESOLVED), `summary`."""
        with self.read() as session:
            rows = session.execute(
                select(Escalation)
                .where(Escalation.client_id == (person or self.client).user_id)
                .order_by(Escalation.created_at, Escalation.id)
            ).scalars()
            return [
                {
                    "id": str(row.id),
                    "reason": row.reason,
                    "state": row.state,
                    "summary": row.summary,
                }
                for row in rows
            ]

    def stored_messages(self, conversation: str) -> list[dict[str, Any]]:
        """The conversation as the database keeps it (what the agent's memory is made of):
        `seq`, `author`, `kind`, `text`."""
        from dawalink.db.models import ChatMessage

        with self.read() as session:
            rows = session.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == uuid.UUID(conversation))
                .order_by(ChatMessage.seq)
            ).scalars()
            return [
                {"seq": m.seq, "author": m.author, "kind": m.kind, "text": m.text_redacted}
                for m in rows
            ]

    def case_state(self, conversation: str) -> dict[str, Any]:
        """The agent's working memory for this conversation (ADR-001)."""
        with self.read() as session:
            return dict(session.get_one(Conversation, uuid.UUID(conversation)).case_state or {})


def start_of(day: int, at: str) -> datetime:
    """`day` days after the evaluation's Monday (0 = Monday … 6 = Sunday), at "HH:MM" in Beirut."""
    hour, minute = at.split(":")
    return at_beirut(MONDAY + timedelta(days=day), time(int(hour), int(minute)))
