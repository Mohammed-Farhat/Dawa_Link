"""The agent's working memory for one conversation: `case_state` (docs/07 §6.2).

A small JSON document on the conversation row. Code updates it from tool results; the
model may change only the fields of `CaseNotes`, through its final `reply`. The client's
location is never in here, so it can never be part of a prompt (INV-24).
"""

import json
import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dawalink.domain.numbers import CASE_STATE_MAX_BYTES

Language = Literal["arabizi", "arabic", "english", "mixed"]
Preference = Literal["fewest_trips", "cheapest", "nearest", "walkable"]
Currency = Literal["LBP", "USD"]

MAX_NOTES = 5
MAX_SITUATION_NOTES = 3
MAX_FOCUS_ITEMS = 5
MAX_SHOWN_LISTINGS = 30
MAX_ASKED_MEDICINES = 20
MAX_PLANS_KEPT = 3


class Money(BaseModel):
    """An amount as the client said it. Code converts it; the model never does."""

    model_config = ConfigDict(extra="forbid")

    amount: float = Field(gt=0, le=1_000_000_000)
    currency: Currency


class FocusItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    qty: int = Field(default=1, ge=1, le=3)
    days_of_use: int = Field(default=1, ge=1, le=365)
    note: str = Field(default="", max_length=80)


class PlanPick(BaseModel):
    """One box of a stored plan: enough to build the card later, and nothing more."""

    product_id: uuid.UUID
    listing_id: uuid.UUID
    qty: int
    price_lbp: int
    days_of_use: int
    request_item_id: uuid.UUID | None = None


class PlanGroup(BaseModel):
    pharmacy_id: uuid.UUID
    picks: list[PlanPick]


class PlanRef(BaseModel):
    """A plan `plan_basket` returned, kept so `propose_plan` can turn it into cards."""

    pickup_day: date
    groups: list[PlanGroup]


class CaseState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Written by the agent, through `reply.case_notes`.
    language: Language | None = None
    preference: Preference | None = None
    budget: Money | None = None
    alternatives_ok: bool | None = None
    items_in_focus: list[FocusItem] = Field(default_factory=list)
    pickup_day: date | None = None
    situation_notes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    # Written by code.
    shown_listing_ids: list[uuid.UUID] = Field(default_factory=list)
    open_proposal_ids: list[uuid.UUID] = Field(default_factory=list)
    # The client's medicines in this chat: for each medicine, the first product that was
    # searched. Any other brand of one of them is "another brand" for the rest of the
    # chat: shown, never proposed for reserving unless the client asks for it (R-C10).
    asked_product_ids: list[uuid.UUID] = Field(default_factory=list)
    plans: dict[str, PlanRef] = Field(default_factory=dict)
    escalated: bool = False
    followups_used: int = 0
    # The newest message the last turn read. What came after it is what the next
    # turn answers, even if it arrived while that turn was still running.
    read_up_to: int = 0


class CaseNotes(BaseModel):
    """What the model may change in the case state (docs/07 §6.2)."""

    model_config = ConfigDict(extra="forbid")

    language: Language | None = None
    preference: Preference | None = None
    budget: Money | None = None
    pickup_day: date | None = None
    situation_notes: list[str] | None = Field(default=None, max_length=MAX_SITUATION_NOTES)
    alternatives_ok: bool | None = None
    items_in_focus: list[FocusItem] | None = Field(default=None, max_length=MAX_FOCUS_ITEMS)
    add_note: str | None = Field(default=None, max_length=200)
    remove_note_index: int | None = Field(default=None, ge=0)


def load(raw: dict[str, Any] | None) -> CaseState:
    """The stored state. One that can't be read any more starts empty: it is only memory."""
    try:
        return CaseState.model_validate(raw or {})
    except ValidationError:
        return CaseState()


def apply_notes(state: CaseState, notes: CaseNotes | None, clean: Any) -> CaseState:
    """The state after the model's notes. `clean` removes personal details from free text."""
    if notes is None:
        return state
    changed = state.model_copy(deep=True)
    for field in ("language", "preference", "budget", "pickup_day", "alternatives_ok"):
        value = getattr(notes, field)
        if value is not None:
            setattr(changed, field, value)
    if notes.items_in_focus is not None:
        changed.items_in_focus = [
            item.model_copy(update={"note": clean(item.note)}) for item in notes.items_in_focus
        ]
    if notes.situation_notes is not None:
        changed.situation_notes = [clean(note)[:80] for note in notes.situation_notes]
    if notes.remove_note_index is not None and notes.remove_note_index < len(changed.notes):
        del changed.notes[notes.remove_note_index]
    if notes.add_note:
        changed.notes = [*changed.notes, clean(notes.add_note)][-MAX_NOTES:]
    return changed


def tidy(state: CaseState, today: date) -> CaseState:
    """What code keeps in order: a pickup day that has passed, and the size (N-33)."""
    tidied = state.model_copy(deep=True)
    if tidied.pickup_day is not None and tidied.pickup_day < today:
        tidied.pickup_day = None
    tidied.shown_listing_ids = tidied.shown_listing_ids[-MAX_SHOWN_LISTINGS:]
    tidied.asked_product_ids = tidied.asked_product_ids[-MAX_ASKED_MEDICINES:]
    while len(tidied.plans) > MAX_PLANS_KEPT:
        del tidied.plans[next(iter(tidied.plans))]
    # Too big: the oldest of what code remembers goes first, then the agent's notes.
    for shrink in (_drop_plans, _drop_shown, _drop_notes):
        if size(tidied) <= CASE_STATE_MAX_BYTES:
            break
        shrink(tidied)
    return tidied


def _drop_plans(state: CaseState) -> None:
    state.plans = {}


def _drop_shown(state: CaseState) -> None:
    state.shown_listing_ids = []


def _drop_notes(state: CaseState) -> None:
    state.notes = []
    state.situation_notes = []
    state.items_in_focus = state.items_in_focus[:1]


def dump(state: CaseState) -> dict[str, Any]:
    return state.model_dump(mode="json", exclude_defaults=True)


def size(state: CaseState) -> int:
    return len(json.dumps(dump(state), separators=(",", ":")).encode())


def for_model(state: CaseState) -> dict[str, Any]:
    """What the model is shown of the state: its own notes, and the cards still open."""
    shown = state.model_dump(
        mode="json",
        exclude_defaults=True,
        exclude={
            "shown_listing_ids",
            "asked_product_ids",
            "plans",
            "followups_used",
            "read_up_to",
        },
    )
    if state.plans:
        shown["plan_ids"] = list(state.plans)
    return shown
