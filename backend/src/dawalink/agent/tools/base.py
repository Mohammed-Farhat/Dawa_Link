"""What every tool shares (docs/07 §4.1).

- **Typed inputs.** A tool's arguments are a Pydantic model; anything else is refused with
  `INVALID_ARGUMENTS`, and the model can correct itself.
- **Identity comes from the turn, never from the model.** The client and the conversation
  are in `Turn`; every ID the model passes is checked against them.
- **Errors are results.** A rule that says no becomes `{"ok": false, "error_code": ...}`:
  the model can explain it or try something else.
- **Explicit outputs.** A tool returns its own output model, never a row or a service
  object, so nothing reaches the model that wasn't chosen to (INV-8, INV-10, INV-23, INV-24).
"""

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent import display
from dawalink.agent.llm import ToolSpec
from dawalink.agent.state import CaseState
from dawalink.db.models import ClientProfile, Conversation, Product
from dawalink.domain.clock import Clock
from dawalink.domain.vocabulary import AgentMode
from dawalink.services import catalog, email, travel
from dawalink.services.context import Tx, unit_of_work
from dawalink.services.errors import ServiceError
from dawalink.services.travel import Location, RoutingService

log = structlog.get_logger(__name__)


class ToolError(StrEnum):
    """Refusals that belong to the tools themselves, beside the services' codes (docs/06 §3.2)."""

    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    TOOL_LIMIT_REACHED = "TOOL_LIMIT_REACHED"
    LOCATION_NEEDED = "LOCATION_NEEDED"
    NOT_SAME_MEDICINE = "NOT_SAME_MEDICINE"
    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    NOTHING_TO_CHANGE = "NOTHING_TO_CHANGE"
    FOLLOWUP_NOT_ALLOWED = "FOLLOWUP_NOT_ALLOWED"
    AREA_NOT_FOUND = "AREA_NOT_FOUND"
    AREA_AMBIGUOUS = "AREA_AMBIGUOUS"
    ASK_PHARMACIST_FIRST = "ASK_PHARMACIST_FIRST"
    OTHER_BRANDS_NOT_AGREED = "OTHER_BRANDS_NOT_AGREED"


def _medicine(tx: Tx, product_id: uuid.UUID) -> str:
    return catalog.medicine_group(tx.session.get_one(Product, product_id))


def note_asked(turn: "Turn", tx: Tx, product_id: uuid.UUID) -> None:
    """Remembers the client's medicine: the first product of a medicine searched in a chat.

    A later search of another brand of it doesn't replace it. That keeps a brand "another
    brand" even when the agent searches it by itself afterwards (R-C10).
    """
    asked = turn.state.asked_product_ids
    medicine = _medicine(tx, product_id)
    if all(_medicine(tx, earlier) != medicine for earlier in asked):
        asked.append(product_id)


def is_another_brand_in_chat(turn: "Turn", tx: Tx, product_id: uuid.UUID) -> bool:
    """Is this product another brand of a medicine the client asked for in this chat?"""
    medicine = _medicine(tx, product_id)
    return any(
        earlier != product_id and _medicine(tx, earlier) == medicine
        for earlier in turn.state.asked_product_ids
    )


class Refused(Exception):
    """A tool's own refusal: a code the model can react to, and a short hint."""

    def __init__(self, code: ToolError, hint: str, **details: Any) -> None:
        super().__init__(hint)
        self.code, self.hint, self.details = code, hint, details


class Arguments(BaseModel):
    """A tool's input. Unknown arguments are refused, so a typo isn't silently ignored."""

    model_config = ConfigDict(extra="forbid")


class Output(BaseModel):
    """A tool's result: only the fields written here ever reach the model."""

    model_config = ConfigDict(extra="forbid")


@dataclass
class Turn:
    """What a tool knows about the turn it runs in. Set by code; the model can't change it."""

    sessions: sessionmaker[Session]
    clock: Clock
    client_id: uuid.UUID
    conversation_id: uuid.UUID
    run_id: uuid.UUID
    mode: AgentMode
    request_id: uuid.UUID | None
    # The working memory. Tools write the code-owned parts (plans, cards, listings shown).
    state: CaseState
    routing: RoutingService | None = None
    # Removes personal details from free text the model wrote (an escalation's summary).
    clean: Callable[[str], str] = str
    # Stable across a retry of the same turn, so a write tool finds its own earlier work.
    key: str = ""
    # True when a message the client wrote started this turn. Only then can the client
    # have asked for something in their own words (a worker turn has no such message).
    by_client: bool = False
    # The cards this turn's tools created, in order.
    created_proposals: list[uuid.UUID] = field(default_factory=list)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments: type[Arguments]
    run: Callable[[Turn, Tx, Any], Output]
    modes: frozenset[AgentMode]
    # What the chat shows while this tool runs ("Searching…"), if anything (docs/07 §3.2).
    progress: str | None = None
    # Work to do before the tool's transaction opens: asking the routing service.
    prepare: Callable[[Turn, Any], None] | None = None

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.arguments.model_json_schema())


@dataclass(frozen=True)
class ToolOutcome:
    name: str
    ok: bool
    error_code: str | None
    content: dict[str, Any]
    latency_ms: int

    def as_json(self) -> str:
        return json.dumps(self.content, ensure_ascii=False, separators=(",", ":"), default=str)


def _plain(value: Any) -> Any:
    """A service error's detail, written the way the model is given everything else."""
    if isinstance(value, datetime):
        return display.when(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID | Decimal | StrEnum):
        return str(value)
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def _refusal(code: str, hint: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    content: dict[str, Any] = {"ok": False, "error_code": code, "hint": hint}
    if details:
        content["details"] = _plain(details)
    return content


def _problems(error: ValidationError) -> list[dict[str, str]]:
    """Which arguments are wrong and why, without echoing the values back."""
    return [
        {"argument": ".".join(str(part) for part in item["loc"]), "problem": item["msg"]}
        for item in error.errors()[:5]
    ]


def run_tool(
    turn: Turn, tools: dict[str, Tool], name: str, arguments: dict[str, Any]
) -> ToolOutcome:
    """Runs one tool call and turns whatever happens into a result (docs/07 §4.1, §8)."""
    started = time.monotonic()

    def outcome(ok: bool, code: str | None, content: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(name, ok, code, content, int((time.monotonic() - started) * 1000))

    tool = tools.get(name)
    if tool is None:
        return outcome(
            False,
            ToolError.UNKNOWN_TOOL,
            _refusal(ToolError.UNKNOWN_TOOL, "There is no such tool. Use one of the tools given."),
        )
    try:
        parsed = tool.arguments.model_validate(arguments)
    except ValidationError as error:
        return outcome(
            False,
            ToolError.INVALID_ARGUMENTS,
            _refusal(
                ToolError.INVALID_ARGUMENTS,
                "Some arguments are wrong. Fix them and call the tool again.",
                {"problems": _problems(error)},
            ),
        )
    try:
        if tool.prepare is not None:
            tool.prepare(turn, parsed)
        result = _in_a_transaction(turn, tool, parsed)
    except ServiceError as error:
        return outcome(
            False, error.code.value, _refusal(error.code.value, str(error), error.details)
        )
    except Refused as error:
        return outcome(
            False, error.code.value, _refusal(error.code.value, error.hint, error.details)
        )
    except Exception:
        # The model gets a code; the reason goes to the log with the run's ID.
        log.exception("tool_failed", tool=name, run_id=str(turn.run_id))
        return outcome(
            False,
            ToolError.INTERNAL_ERROR,
            _refusal(ToolError.INTERNAL_ERROR, "This tool failed. Try something else."),
        )
    return outcome(True, None, {"ok": True, **result.model_dump(mode="json", exclude_none=True)})


def _in_a_transaction(turn: Turn, tool: Tool, parsed: Arguments) -> Output:
    """One tool call is one transaction. A serialization conflict is tried once more."""
    for attempt in (1, 2):
        try:
            with unit_of_work(turn.sessions, turn.clock) as tx:
                return tool.run(turn, tx, parsed)
        except DBAPIError as error:
            conflict = getattr(error.orig, "sqlstate", None) in ("40001", "40P01")
            if attempt == 2 or not conflict:
                raise
    raise AssertionError("unreachable")


# --- What several tools need -----------------------------------------------------------


def location_of(tx: Tx, turn: Turn) -> Location:
    """Where this conversation's client is: the location shared from the phone, the area
    they named in chat, or else the profile's district.

    It is read here, by code, for every tool call. It is never part of the case state or
    of a tool's output, so it can't reach the model (INV-24).
    """
    conversation = tx.session.get_one(Conversation, turn.conversation_id)
    known = travel.conversation_location(tx, conversation)
    if known is not None:
        return known
    profile = tx.session.get(ClientProfile, turn.client_id)
    if profile is not None and profile.district_id is not None:
        return travel.district_location(tx, profile.district_id)
    raise Refused(
        ToolError.LOCATION_NEEDED,
        "The client's location isn't known. Ask them which area or town they are in, or to "
        "tap 'Use my location'.",
    )


def rate(tx: Tx) -> Decimal | None:
    """The LBP per USD rate of the newest price list (R-C3)."""
    return email.display_rate(tx)


def road_times_first(
    turn: Turn, pharmacies_of: Callable[[Tx], list[uuid.UUID]], *, between: bool = False
) -> None:
    """Asks the routing service for the road times a tool is about to need.

    Three short steps, and no transaction is open while the routing service answers. If
    it fails or isn't configured, the tool simply works with straight-line estimates.
    """
    if turn.routing is None:
        return
    with unit_of_work(turn.sessions, turn.clock) as tx:
        try:
            origin = location_of(tx, turn)
        except Refused:
            return  # the tool itself will say that the location is needed
        wanted = travel.missing(tx, origin, pharmacies_of(tx), between=between)
    rows = travel.fetch(turn.routing, wanted)
    if rows:
        with unit_of_work(turn.sessions, turn.clock) as tx:
            travel.store(tx, rows)
