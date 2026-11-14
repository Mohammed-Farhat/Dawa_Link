"""The action tools: the few things the agent may do without a tap (docs/07 §4.4, R-RQ4).

Each is bounded by a rule in code: request hours, limits, three pharmacies at most, one
follow-up at a time. None of them reserves, accepts, cancels or decides who gets stock.
Called twice with the same arguments, each finds its own earlier work (R-AG6).
"""

import uuid
from datetime import timedelta

from pydantic import Field
from sqlalchemy import func, select

from dawalink.agent import display
from dawalink.agent.state import Money
from dawalink.agent.tools.base import (
    Arguments,
    Output,
    Refused,
    Tool,
    ToolError,
    Turn,
    location_of,
    rate,
)
from dawalink.agent.tools.propose import ASSISTANT, SOURCING
from dawalink.agent.tools.read import BOTH, Days, Qty
from dawalink.db.models import Claim, EarlyReleaseAsk, RequestItem, SourcingRequest
from dawalink.domain.numbers import FOLLOWUP_MAX, FOLLOWUP_MIN, MAX_FOLLOWUPS_PER_REQUEST
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import ClaimSource, EscalationReason
from dawalink.services import claims, conversations, early_release, escalations, requests
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

# --- create_watch ----------------------------------------------------------------------


class CreateWatch(Arguments):
    product_id: uuid.UUID
    qty: Qty = 1
    days_of_use: Days = 1
    include_alternatives: bool = Field(
        default=False, description="True only if the client agreed to other brands."
    )
    max_price: Money | None = None


class Watching(Output):
    watch_id: uuid.UUID
    ends_display: str
    already_watching: bool = False


def create_watch(turn: Turn, tx: Tx, args: CreateWatch) -> Watching:
    try:
        claim = claims.create_watch(
            tx,
            client_id=turn.client_id,
            product_id=args.product_id,
            location=location_of(tx, turn),
            source=ClaimSource.ASSISTANT,
            actor=Actor.AGENT,
            qty=args.qty,
            days_of_use=args.days_of_use,
            include_equivalents=args.include_alternatives,
            max_price_lbp=display.in_lbp(args.max_price, rate(tx)),
        )
    except ServiceError as error:
        if error.code is not Code.WATCH_EXISTS:
            raise
        # Asked twice (a retried turn, or the client asking again): the watch is there.
        existing = tx.session.get_one(Claim, error.details["watch_id"])
        return Watching(
            watch_id=existing.id, ends_display=display.when(existing.ends_at), already_watching=True
        )
    return Watching(watch_id=claim.id, ends_display=display.when(claim.ends_at))


# --- open_claim ------------------------------------------------------------------------


class OpenClaim(Arguments):
    request_item_id: uuid.UUID


class ClaimOpen(Output):
    claim_id: uuid.UUID
    ends_display: str


def open_claim(turn: Turn, tx: Tx, args: OpenClaim) -> ClaimOpen:
    owner = tx.session.execute(
        select(SourcingRequest.client_id)
        .join(RequestItem, RequestItem.request_id == SourcingRequest.id)
        .where(RequestItem.id == args.request_item_id)
    ).scalar()
    if owner != turn.client_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown request item.")
    claim = requests.open_claim(tx, args.request_item_id)
    return ClaimOpen(claim_id=claim.id, ends_display=display.when(claim.ends_at))


# --- request_early_release -------------------------------------------------------------


class RequestEarlyRelease(Arguments):
    claim_id: uuid.UUID = Field(description="A watch_id, or the claim_id of a request item.")


class Asked(Output):
    asked: int
    answers_by_display: str | None = None
    reason: str | None = None


def request_early_release(turn: Turn, tx: Tx, args: RequestEarlyRelease) -> Asked:
    claim = tx.session.get(Claim, args.claim_id)
    if claim is None or claim.client_id != turn.client_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown claim.")
    asked = early_release.request_early_release(
        tx, claim_id=claim.id, idempotency_key=f"{turn.key}:early-release:{claim.id}"
    )
    if asked.pharmacies_asked == 0 or asked.request_id is None:
        # All the model may know (R-E8): nobody could be asked right now.
        return Asked(asked=0, reason="no_candidates")
    answer_by = tx.session.execute(
        select(func.max(EarlyReleaseAsk.respond_by)).where(
            EarlyReleaseAsk.er_request_id == asked.request_id
        )
    ).scalar()
    return Asked(
        asked=asked.pharmacies_asked,
        answers_by_display=display.when(answer_by) if answer_by else None,
    )


# --- schedule_followup -----------------------------------------------------------------


class ScheduleFollowup(Arguments):
    in_minutes: int = Field(ge=15, le=300, description="When to look at this request again.")


class FollowupSet(Output):
    followup_display: str


def schedule_followup(turn: Turn, tx: Tx, args: ScheduleFollowup) -> FollowupSet:
    if turn.request_id is None:
        raise Refused(ToolError.FOLLOWUP_NOT_ALLOWED, "A follow-up belongs to a request.")
    wait = timedelta(minutes=args.in_minutes)
    if not FOLLOWUP_MIN <= wait <= FOLLOWUP_MAX:
        raise Refused(ToolError.FOLLOWUP_NOT_ALLOWED, "A follow-up is 15 to 300 minutes ahead.")
    request = tx.session.get_one(SourcingRequest, turn.request_id)
    at = tx.now + wait
    if request.state != "OPEN" or at >= request.ends_at:
        raise Refused(
            ToolError.FOLLOWUP_NOT_ALLOWED,
            "That is after the request's window ends.",
            window_ends=display.when(request.ends_at),
        )
    if turn.state.followups_used >= MAX_FOLLOWUPS_PER_REQUEST:
        raise Refused(ToolError.FOLLOWUP_NOT_ALLOWED, "This request has used its 4 follow-ups.")
    # One pending follow-up per request: a new one replaces the old one (N-39).
    conversation = conversations.locked(tx, turn.conversation_id)
    conversation.followup_at = at
    turn.state.followups_used += 1
    return FollowupSet(followup_display=display.when(at))


# --- escalate --------------------------------------------------------------------------


class Escalate(Arguments):
    reason: EscalationReason
    summary: str = Field(
        min_length=1,
        max_length=300,
        description="What a person needs to know. No names, phone numbers or emails.",
    )


class EscalationOut(Output):
    escalation_id: uuid.UUID
    appended: bool


def escalate(turn: Turn, tx: Tx, args: Escalate) -> EscalationOut:
    done = escalations.escalate(
        tx,
        client_id=turn.client_id,
        reason=args.reason,
        summary=turn.clean(args.summary)[:300],
        conversation_id=turn.conversation_id,
        request_id=turn.request_id,
    )
    turn.state.escalated = True
    return EscalationOut(escalation_id=done.escalation_id, appended=done.appended)


TOOLS = (
    Tool(
        "create_watch",
        "Starts waiting for new stock of one medicine for the client, for 6 hours. The client "
        "is offered the stock if some appears (first come, first served).",
        CreateWatch,
        create_watch,
        ASSISTANT,
        progress="Setting up a watch…",
    ),
    Tool(
        "open_claim",
        "Starts waiting for new stock for one medicine of this request, until its window ends.",
        OpenClaim,
        open_claim,
        SOURCING,
        progress="Setting up a watch…",
    ),
    Tool(
        "request_early_release",
        "Asks up to 3 open pharmacies to release stock they keep private, for a watch or a "
        "waiting request item. You only learn how many were asked.",
        RequestEarlyRelease,
        request_early_release,
        BOTH,
        progress="Asking pharmacies…",
    ),
    Tool(
        "schedule_followup",
        "Looks at this request again later, when waiting will let you do something new "
        "(for example, pharmacies open in 40 minutes). One pending follow-up at a time.",
        ScheduleFollowup,
        schedule_followup,
        SOURCING,
    ),
    Tool(
        "escalate",
        "Hands the case to a person from DawaLink. They can reply and help; they can't change "
        "who gets stock first.",
        Escalate,
        escalate,
        BOTH,
    ),
)
