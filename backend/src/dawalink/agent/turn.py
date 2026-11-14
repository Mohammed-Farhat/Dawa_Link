"""One agent turn, from the lease to the saved reply (docs/07 §3, ADR-001).

    load_context → guard_input → agent ⇄ tools → guard_output → save
                                   ╰──────────→ fallback (the model can't be reached)

The steps are the nodes of a small LangGraph graph, the same for both modes. LangGraph
keeps nothing between turns: the tables are the memory. A turn is several short database
transactions, and **none is open while the model thinks** (R-AG2):

1. **open**: take the conversation's lease, load the context, write the `agent_runs` row;
2. each **tool call** is its own transaction, committed at once;
3. **save**: the reply, the case state and the run's numbers, in one transaction that is
   refused if the lease was lost in the meantime.

A tool that writes (a watch, a claim, an ask to pharmacies, an escalation) is committed
before the turn is saved, so a turn that fails and is retried runs it again: each of
those tools finds its own earlier work instead of repeating it (R-AG6).
"""

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, TypedDict, cast

import structlog
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent import context, limits, state
from dawalink.agent.context import Loaded
from dawalink.agent.guards import output as output_guard
from dawalink.agent.guards.injection import looks_like_injection
from dawalink.agent.guards.redact import EMAIL_MARK, LOCATION, NAME, PHONE_MARK, redact
from dawalink.agent.llm import (
    AssistantTurn,
    ChatModel,
    LLMError,
    LLMRefused,
    LLMUnavailable,
    Message,
    ModelReply,
    Prompt,
    ToolResult,
    ToolResults,
    UserText,
)
from dawalink.agent.llm.base import cost_usd
from dawalink.agent.prompts import PROMPT_VERSION, system_parts
from dawalink.agent.templates import Fixed, fixed
from dawalink.agent.tools import (
    REPLY,
    REPLY_SPEC,
    Reply,
    ToolError,
    ToolOutcome,
    Turn,
    for_mode,
    run_tool,
    specs,
)
from dawalink.agent.tracing import NoTracer, Tracer, TurnTrace, send_safely
from dawalink.db.models import (
    AbuseFlag,
    AgentRun,
    AgentToolCall,
    ChatMessage,
    Conversation,
    SourcingRequest,
)
from dawalink.domain.clock import Clock
from dawalink.domain.numbers import (
    LLM_RETRY_BACKOFF_S,
    LLM_TIMEOUT_S,
    MAX_LLM_CALLS_PER_TURN,
    MAX_TOOL_CALLS_PER_TURN,
    TURN_RETRY_AFTER,
    TURN_TIME_LIMIT_CHAT_S,
    TURN_TIME_LIMIT_WORKER_S,
)
from dawalink.domain.vocabulary import EscalationReason, RunOutcome
from dawalink.services import conversations, escalations, proposals
from dawalink.services.context import Tx, unit_of_work
from dawalink.services.travel import RoutingService

log = structlog.get_logger(__name__)

RunsIn = Literal["chat", "worker"]
# A guardrail note for a turn the model never ended with a usable reply.
NO_REPLY = "no_reply"
INJECTION = "injection"
MODEL_REFUSAL = "model_refusal"
SPEND_ALERT_SHARE = Decimal("0.8")  # R-AL


@dataclass(frozen=True)
class Agent:
    """What every turn needs and no turn changes."""

    sessions: sessionmaker[Session]
    clock: Clock
    model: ChatModel
    routing: RoutingService | None = None
    tracer: Tracer = field(default_factory=NoTracer)
    monthly_budget_usd: Decimal = Decimal(100)
    # Real time, for the model's timeouts and the turn's time limit. The lease and every
    # business deadline use the app clock instead (R-T11).
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


class Status(StrEnum):
    DONE = "done"  # a reply was saved
    BUSY = "busy"  # another turn holds the lease (docs/06 CONVERSATION_BUSY)
    UNAVAILABLE = "unavailable"  # degraded mode, or the model failed (ASSISTANT_UNAVAILABLE)
    BUDGET = "budget"  # the client's daily budget is used up (TOKEN_BUDGET_EXCEEDED)
    HANDED_OVER = "handed_over"  # too many turns on this request: a person takes over
    LEASE_LOST = "lease_lost"  # the turn took too long; nothing was saved, it will be retried
    NOTHING = "nothing"  # nothing to answer: already handled, or the request is closed


@dataclass(frozen=True)
class TurnResult:
    status: Status
    outcome: RunOutcome | None = None
    run_id: uuid.UUID | None = None
    message_seq: int | None = None
    text: str | None = None
    proposal_ids: tuple[uuid.UUID, ...] = ()
    quick_replies: tuple[str, ...] = ()
    # When the client's budget starts again, for `BUDGET`.
    until: datetime | None = None


class _LeaseLost(Exception):
    pass


@dataclass
class _Work:
    """One turn's working state. The graph's nodes read and change it."""

    agent: Agent
    conversation_id: uuid.UUID
    runs_in: RunsIn
    followup: bool
    on_progress: Callable[[str], None] | None
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    began: float = 0.0
    deadline: float = 0.0
    loaded: Loaded | None = None
    turn: Turn | None = None
    trace: TurnTrace | None = None
    messages: list[Message] = field(default_factory=list)
    # Counters, written to `agent_runs`.
    llm_calls: int = 0
    tool_calls: int = 0
    retries: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    cost: Decimal = Decimal(0)
    redactions: int = 0
    guardrails: list[str] = field(default_factory=list)
    outcomes: list[ToolOutcome] = field(default_factory=list)
    # The reply being decided.
    candidate: Reply | None = None
    candidate_call_id: str | None = None
    pending_results: list[ToolResult] = field(default_factory=list)
    repaired: bool = False
    final: Reply | None = None
    outcome: RunOutcome = RunOutcome.OK
    failure: LLMError | None = None
    result: TurnResult | None = None
    # Where the graph goes next.
    route: str = ""

    @property
    def owner(self) -> str:
        return str(self.run_id)

    def time_left(self) -> float:
        return self.deadline - self.agent.monotonic()


class _State(TypedDict):
    work: _Work


# --- 1. open ---------------------------------------------------------------------------


def _load_context(graph_state: _State) -> _State:
    """Takes the lease and loads everything, in one short transaction (docs/07 §3.1)."""
    work = graph_state["work"]
    agent = work.agent
    work.began = agent.monotonic()
    limit = TURN_TIME_LIMIT_CHAT_S if work.runs_in == "chat" else TURN_TIME_LIMIT_WORKER_S
    work.deadline = work.began + limit
    work.route = END
    with unit_of_work(agent.sessions, agent.clock) as tx:
        conversation = tx.session.get_one(Conversation, work.conversation_id)
        if limits.breaker_open(tx) or limits.spend_cap_reached(tx, agent.monthly_budget_usd):
            # Degraded mode for everyone: no model call is even tried (N-38, N-46).
            work.result = TurnResult(Status.UNAVAILABLE)
            if work.runs_in == "worker":
                _try_again_later(tx, conversation, counted=False)
            return graph_state
        if not conversations.take_lease(tx, conversation.id, work.owner):
            work.result = TurnResult(Status.BUSY)
            return graph_state
        tx.session.refresh(conversation)
        if limits.over_daily_budget(tx, conversation.client_id):
            until = limits.midnight(tx)
            if work.runs_in == "worker":
                conversation.pending_turn_at = until
            conversations.release_lease(conversation, work.owner)
            work.result = TurnResult(Status.BUDGET, RunOutcome.BUDGET_EXCEEDED, until=until)
            return graph_state
        if conversation.request_id and limits.too_many_turns(tx, conversation.request_id):
            _hand_to_a_person(tx, conversation, "This request used all of its agent turns.")
            conversations.release_lease(conversation, work.owner)
            work.result = TurnResult(Status.HANDED_OVER)
            return graph_state

        if conversation.request_id and _request_is_over(tx, conversation):
            conversations.release_lease(conversation, work.owner)
            work.result = TurnResult(Status.NOTHING)
            return graph_state

        # The lease is held now, so nobody else is working on this conversation: is
        # the turn still wanted? The worker read its list a moment ago, and another
        # turn may have answered since. A second turn would cost money and repeat
        # the reply.
        follow_up_due = conversation.followup_at is not None and (
            conversation.followup_at <= tx.now
        )
        asked_for = conversation.pending_turn_at is not None and (
            conversation.pending_turn_at <= tx.now
        )
        still_wanted = work.runs_in == "chat" or asked_for or follow_up_due
        loaded = context.load(tx, conversation.id, followup=follow_up_due) if still_wanted else None
        if loaded is None:
            if still_wanted:
                # Asked for, but everything was already answered: forget the mark.
                conversation.pending_turn_at = None
            conversations.release_lease(conversation, work.owner)
            work.result = TurnResult(Status.NOTHING)
            return graph_state
        # Whatever starts this turn, it also does what a follow-up that is due would do.
        if follow_up_due:
            conversation.followup_at = None
        trace_id = agent.tracer.new_trace_id()
        tx.session.add(
            AgentRun(
                id=work.run_id,
                conversation_id=conversation.id,
                request_id=loaded.request_id,
                mode=loaded.mode.value,
                trigger=loaded.trigger.value,
                model=agent.model.name,
                prompt_version=PROMPT_VERSION,
                started_at=tx.now,
                langfuse_trace_id=trace_id,
            )
        )
    work.loaded = loaded
    work.trace = TurnTrace(
        trace_id,
        {
            "mode": loaded.mode.value,
            "trigger": loaded.trigger.value,
            "conversation_id": str(loaded.conversation_id),
            "request_id": str(loaded.request_id) if loaded.request_id else None,
            "model": agent.model.name,
            "prompt_version": PROMPT_VERSION,
            # An internal ID, not a personal detail.
            "client_ref": str(loaded.client_id),
            "runs_in": work.runs_in,
        },
    )
    work.turn = Turn(
        sessions=agent.sessions,
        clock=agent.clock,
        client_id=loaded.client_id,
        conversation_id=loaded.conversation_id,
        run_id=work.run_id,
        mode=loaded.mode,
        request_id=loaded.request_id,
        state=loaded.case_state.model_copy(deep=True),
        routing=agent.routing,
        clean=lambda text: redact(text, loaded.identity).text,
        key=f"{loaded.conversation_id}:{loaded.last_seq}",
    )
    work.messages = [UserText(loaded.block)]
    work.route = "guard_input"
    return graph_state


def _request_is_over(tx: Tx, conversation: Conversation) -> bool:
    """A closed request needs no agent turn: what was asked for is forgotten."""
    request = tx.session.get_one(SourcingRequest, conversation.request_id)
    if request.state == "OPEN":
        return False
    conversation.pending_turn_at = None
    conversation.followup_at = None
    conversation.turn_attempts = 0
    return True


# --- 2. guard_input --------------------------------------------------------------------


def _guard_input(graph_state: _State) -> _State:
    """Counts what the redaction removed, and flags an injection attempt (docs/07 §7.1).

    The message was redacted before it was stored, so this only counts the marks. A
    flagged message is handled like any other: the flag is for the metrics and the abuse
    rules, never a reason to refuse.
    """
    work = graph_state["work"]
    assert work.loaded is not None
    assert work.trace is not None
    text = work.loaded.client_text or ""
    with work.trace.span("guard_input") as span:
        work.redactions = sum(text.count(mark) for mark in (NAME, EMAIL_MARK, PHONE_MARK, LOCATION))
        flagged = looks_like_injection(text)
        if flagged:
            work.guardrails.append(INJECTION)
        span.metadata.update(redactions=work.redactions, injection=flagged)
    work.route = "agent"
    return graph_state


# --- 3. agent (the model) --------------------------------------------------------------


def _ask(work: _Work, prompt: Prompt) -> ModelReply:
    """One model call, retried on what a retry can fix (N-35, N-36)."""
    attempts = 1 + len(LLM_RETRY_BACKOFF_S)
    for attempt in range(attempts):
        left = work.time_left()
        if left <= 0:
            raise LLMUnavailable("the turn's time limit was reached")
        try:
            return work.agent.model.complete(prompt, timeout_s=min(LLM_TIMEOUT_S, left))
        except LLMError as error:
            if not error.retryable or attempt == attempts - 1:
                raise
            work.retries += 1
            work.agent.sleep(min(LLM_RETRY_BACKOFF_S[attempt], max(work.time_left(), 0)))
    raise AssertionError("unreachable")


def _agent(graph_state: _State) -> _State:
    work = graph_state["work"]
    assert work.loaded is not None
    assert work.trace is not None
    if work.llm_calls >= MAX_LLM_CALLS_PER_TURN:
        # The model never ended the turn: our own words, with this turn's cards (FA-4).
        _use_template(work, Fixed.NEUTRAL, NO_REPLY)
        return graph_state
    tools_left = work.tool_calls < MAX_TOOL_CALLS_PER_TURN
    prompt = Prompt(
        system=system_parts(work.loaded.mode),
        messages=tuple(work.messages),
        # After the last allowed tool call, the model is only given `reply` (N-17).
        tools=specs(work.loaded.mode) if tools_left else (REPLY_SPEC,),
    )
    with work.trace.span("llm", "generation", model=work.agent.model.name) as span:
        retries_before = work.retries
        try:
            answer = _ask(work, prompt)
        except LLMRefused:
            # The model's own safety system declined. That is about this message, not
            # about the provider being down: the client gets our neutral text, and the
            # circuit breaker isn't touched (one client can't switch the assistant off
            # for everyone by sending messages that get refused).
            span.metadata.update(error="LLMRefused")
            work.llm_calls += 1
            work.outcome = RunOutcome.GUARDRAIL_BLOCKED
            _use_template(work, Fixed.NEUTRAL, MODEL_REFUSAL)
            return graph_state
        except LLMError as error:
            span.metadata.update(error=type(error).__name__, retries=work.retries - retries_before)
            work.failure = error
            work.route = "fallback"
            return graph_state
        usage = answer.usage
        work.llm_calls += 1
        work.tokens_in += usage.input_tokens
        work.tokens_out += usage.output_tokens
        work.tokens_cached += usage.cached_tokens
        call_cost = cost_usd(work.agent.model.name, usage)
        work.cost += call_cost
        span.input = _last_input(work.messages)
        span.output = {
            "text": answer.text,
            "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in answer.tool_calls],
        }
        span.metadata.update(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cached_tokens,
            cost_usd=str(call_cost),
            retries=work.retries - retries_before,
        )
    work.messages.append(AssistantTurn(answer))
    if answer.tool_calls:
        work.route = "tools"
        return graph_state
    # Plain text instead of the `reply` tool: small models do this. It is accepted as the
    # reply's text, with no cards, and still goes through the output guard (docs/07 §4.5).
    text = answer.text.strip()
    if not text:
        _use_template(work, Fixed.NEUTRAL, NO_REPLY)
        return graph_state
    work.candidate, work.candidate_call_id = Reply(text=text[:1200]), None
    work.route = "guard_output"
    return graph_state


def _last_input(messages: list[Message]) -> Any:
    last = messages[-1]
    if isinstance(last, UserText):
        return last.text
    if isinstance(last, ToolResults):
        return [{"tool": r.name, "result": r.content} for r in last.results]
    return None


# --- 4. tools --------------------------------------------------------------------------


def _tools(graph_state: _State) -> _State:
    """Runs the model's tool calls, in order. Every call gets a result, whatever happens."""
    work = graph_state["work"]
    assert work.loaded is not None
    assert work.turn is not None
    assert work.trace is not None
    last = work.messages[-1]
    assert isinstance(last, AssistantTurn)
    tools = for_mode(work.loaded.mode)
    work.pending_results = []
    work.candidate = None
    for call in last.reply.tool_calls:
        if call.name == REPLY:
            if work.candidate is not None:
                work.pending_results.append(
                    _error(call.id, REPLY, ToolError.INVALID_ARGUMENTS, "Reply once per turn.")
                )
                continue
            try:
                work.candidate = Reply.model_validate(call.arguments)
                work.candidate_call_id = call.id
            except ValidationError as error:
                problems = "; ".join(
                    f"{'.'.join(str(p) for p in item['loc'])}: {item['msg']}"
                    for item in error.errors()[:5]
                )
                work.pending_results.append(
                    _error(
                        call.id, REPLY, ToolError.INVALID_ARGUMENTS, f"Fix the reply: {problems}"
                    )
                )
            continue
        if work.tool_calls >= MAX_TOOL_CALLS_PER_TURN:
            work.pending_results.append(
                _error(
                    call.id,
                    call.name,
                    ToolError.TOOL_LIMIT_REACHED,
                    "You have used this turn's 6 tool calls. Call reply now.",
                )
            )
            continue
        tool = tools.get(call.name)
        if tool is not None and tool.progress and work.on_progress is not None:
            work.on_progress(tool.progress)
        with work.trace.span(call.name, "tool") as span:
            outcome = run_tool(work.turn, tools, call.name, call.arguments)
            span.input = call.arguments
            span.output = outcome.content
            span.metadata.update(
                ok=outcome.ok, error_code=outcome.error_code, result_chars=len(outcome.as_json())
            )
        work.tool_calls += 1
        work.outcomes.append(outcome)
        work.pending_results.append(
            ToolResult(call.id, call.name, outcome.as_json(), is_error=not outcome.ok)
        )
    if work.outcomes and not _renew_lease(work):
        work.route = "lost"
        return graph_state
    if work.candidate is not None:
        work.route = "guard_output"
        return graph_state
    work.messages.append(ToolResults(tuple(work.pending_results)))
    work.route = "agent"
    return graph_state


def _error(call_id: str, name: str, code: ToolError, hint: str) -> ToolResult:
    content = json.dumps({"ok": False, "error_code": code.value, "hint": hint})
    return ToolResult(call_id, name, content, is_error=True)


def _renew_lease(work: _Work) -> bool:
    """Pushes the lease forward after tool calls. False: another turn took over."""
    with unit_of_work(work.agent.sessions, work.agent.clock) as tx:
        return conversations.renew_lease(tx, work.conversation_id, work.owner)


# --- 5. guard_output -------------------------------------------------------------------


def _guard_output(graph_state: _State) -> _State:
    """Checks the reply. One chance to fix it, then our own words (docs/07 §7.2, AG-D9)."""
    work = graph_state["work"]
    assert work.loaded is not None
    assert work.candidate is not None
    assert work.trace is not None
    with work.trace.span("guard_output") as span:
        with unit_of_work(work.agent.sessions, work.agent.clock) as tx:
            checked = output_guard.check(
                tx,
                work.candidate,
                conversation_id=work.loaded.conversation_id,
                client_id=work.loaded.client_id,
                run_id=work.run_id,
                client_text=work.loaded.client_text,
            )
        kinds = [violation.type for violation in checked.violations]
        span.metadata.update(violations=kinds, repair_used=work.repaired)
    for kind in kinds:
        if kind not in work.guardrails:
            work.guardrails.append(kind)
    # A reply in the wrong language is sent after one try to fix it: low risk (FA-8).
    blocking = [
        violation
        for violation in checked.violations
        if not (work.repaired and violation.type == output_guard.LANGUAGE)
    ]
    if not blocking:
        work.final = checked.reply
        work.route = "save"
        return graph_state
    if work.repaired or work.llm_calls >= MAX_LLM_CALLS_PER_TURN:
        clinical = any(v.type == output_guard.CLINICAL for v in blocking)
        work.outcome = RunOutcome.GUARDRAIL_BLOCKED
        _use_template(work, Fixed.CLINICAL_REFUSAL if clinical else Fixed.NEUTRAL, None)
        return graph_state
    work.repaired = True
    feedback = "Your reply can't be sent. " + " ".join(v.feedback for v in blocking)
    if work.candidate_call_id is None:
        work.messages.append(UserText(feedback + " Answer again with the reply tool."))
    else:
        work.pending_results.append(
            _error(work.candidate_call_id, REPLY, ToolError.INVALID_ARGUMENTS, feedback)
        )
        work.messages.append(ToolResults(tuple(work.pending_results)))
    work.candidate = None
    work.route = "agent"
    return graph_state


def _language(work: _Work) -> str | None:
    """The client's language, for a text of ours: what the agent noted, else the script."""
    assert work.loaded is not None
    assert work.turn is not None
    noted = work.turn.state.language
    if output_guard.script_of(work.loaded.client_text or "") == "arabic":
        return "arabic"
    return noted if noted in ("arabizi", "arabic", "english") else None


def _use_template(work: _Work, which: Fixed, note: str | None) -> None:
    """Ends the turn with a text written by us (docs/07 §7.3)."""
    assert work.turn is not None
    if note and note not in work.guardrails:
        work.guardrails.append(note)
    cards: list[uuid.UUID] = []
    if which is Fixed.NEUTRAL:
        with unit_of_work(work.agent.sessions, work.agent.clock) as tx:
            known = proposals.of_conversation(tx, work.conversation_id, work.turn.created_proposals)
            cards = [
                proposal_id
                for proposal_id in work.turn.created_proposals
                if proposal_id in known and proposals.state_of(tx, known[proposal_id]) == "open"
            ][:5]
        if not cards:
            which = Fixed.TRY_AGAIN
    work.final = Reply(text=fixed(which, _language(work)), proposal_ids=cards)
    work.route = "save"


# --- 6. save ---------------------------------------------------------------------------


def _finish_run(tx: Tx, work: _Work, outcome: RunOutcome) -> None:
    """Writes the turn's numbers on its `agent_runs` row, and its tool calls."""
    elapsed_ms = int((work.agent.monotonic() - work.began) * 1000)
    tx.session.execute(
        update(AgentRun)
        .where(AgentRun.id == work.run_id)
        .values(
            ended_at=tx.now,
            latency_ms=elapsed_ms,
            tokens_in=work.tokens_in,
            tokens_out=work.tokens_out,
            tokens_cached=work.tokens_cached,
            cost_usd=work.cost,
            llm_calls=work.llm_calls,
            tool_calls=len(work.outcomes),
            tool_errors=sum(1 for outcome_ in work.outcomes if not outcome_.ok),
            retries=work.retries,
            guardrails=list(work.guardrails),
            redactions=work.redactions,
            outcome=outcome.value,
        )
    )
    for done in work.outcomes:
        tx.session.add(
            AgentToolCall(
                agent_run_id=work.run_id,
                tool=done.name,
                ok=done.ok,
                error_code=done.error_code,
                latency_ms=done.latency_ms,
            )
        )


def _newer_events(tx: Tx, conversation_id: uuid.UUID, after_seq: int) -> bool:
    """Did something the agent must react to arrive while this turn ran?"""
    newer = tx.session.execute(
        select(ChatMessage.id)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.seq > after_seq,
            (ChatMessage.kind == "event") | (ChatMessage.author == "client"),
        )
        .limit(1)
    ).scalar()
    return newer is not None


def turn_is_done(tx: Tx, conversation: Conversation, read_up_to: int) -> None:
    """The turn handled everything up to message `read_up_to`. Is another turn needed?

    An event that arrived while the turn ran asks for another one, and must not be wiped
    with the events this turn handled (FA-20). The caller holds the conversation's lock,
    which is also what a new event takes: so an event is either seen here, or it finds
    the mark already cleared and sets it again. It can't fall in between.
    """
    again = _newer_events(tx, conversation.id, read_up_to)
    conversation.pending_turn_at = tx.now if again else None
    conversation.turn_attempts = 0


def _flag_guardrail(tx: Tx, work: _Work) -> None:
    """R-AB: an injection attempt is a low flag; three guardrail triggers in a day, a high one."""
    assert work.loaded is not None
    if INJECTION not in work.guardrails:
        return
    recent = tx.session.execute(
        select(AgentRun.guardrails)
        .join(Conversation, Conversation.id == AgentRun.conversation_id)
        .where(
            Conversation.client_id == work.loaded.client_id,
            AgentRun.started_at > tx.now - timedelta(hours=24),
        )
    ).scalars()
    triggers = sum(1 for kinds in recent if INJECTION in (kinds or []))
    severity = "high" if triggers >= 3 else "low"
    flag = upsert(AbuseFlag).values(
        subject_type="client",
        subject_id=work.loaded.client_id,
        rule="guardrail_repeat",
        severity=severity,
        evidence={"triggers_24h": triggers, "run_id": str(work.run_id)},
    )
    tx.session.execute(
        flag.on_conflict_do_update(
            index_elements=["subject_type", "subject_id", "rule"],
            index_where=sql_text("state = 'OPEN'"),
            set_={"severity": severity, "evidence": flag.excluded.evidence},
        )
    )


def _warn_about_spending(tx: Tx, work: _Work) -> None:
    """R-AL: an alert once the month's LLM spending passes 80% of its budget."""
    if work.cost <= 0:
        return
    budget = work.agent.monthly_budget_usd
    share = limits.month_spent_share(tx, budget)
    before = share - (work.cost / budget if budget > 0 else 0)
    # Said once: by the turn that crosses the line.
    if before < SPEND_ALERT_SHARE <= share:
        log.error(
            "llm_spend_above_80_percent", share=round(float(share), 3), budget_usd=str(budget)
        )


def _save(graph_state: _State) -> _State:
    """The reply, the case state and the run's numbers, in one transaction (docs/07 §3.1)."""
    work = graph_state["work"]
    assert work.loaded is not None
    assert work.turn is not None
    assert work.final is not None
    assert work.trace is not None
    loaded, reply = work.loaded, work.final
    work.route = END
    with work.trace.span("save"):
        try:
            with unit_of_work(work.agent.sessions, work.agent.clock) as tx:
                conversation = conversations.locked(tx, loaded.conversation_id)
                if not conversations.holds_lease(tx, conversation, work.owner):
                    # The turn outlived its lease, and another one may have run: saving
                    # now could write a second reply. Nothing is saved; it is retried (FA-16).
                    raise _LeaseLost
                noted = state.apply_notes(work.turn.state, reply.case_notes, work.turn.clean)
                noted.read_up_to = loaded.last_seq
                conversation.case_state = state.dump(state.tidy(noted, tx.today))
                message = conversations.append(
                    tx,
                    conversation,
                    author="agent",
                    kind="text",
                    # It passed the output guard, and the model was never given the
                    # client's details: removing words that happen to match the
                    # client's name would only damage the reply.
                    text=reply.text,
                    cards=[str(proposal_id) for proposal_id in reply.proposal_ids],
                    quick_replies=list(reply.quick_replies),
                    agent_run_id=work.run_id,
                )
                _finish_run(tx, work, work.outcome)
                _flag_guardrail(tx, work)
                _warn_about_spending(tx, work)
                turn_is_done(tx, conversation, loaded.last_seq)
                conversations.release_lease(conversation, work.owner)
                seq = message.seq
        except _LeaseLost:
            _lost(graph_state)
            return graph_state
    work.result = TurnResult(
        Status.DONE,
        work.outcome,
        run_id=work.run_id,
        message_seq=seq,
        text=reply.text,
        proposal_ids=tuple(reply.proposal_ids),
        quick_replies=tuple(reply.quick_replies),
    )
    work.trace.output = {"text": reply.text, "cards": len(reply.proposal_ids)}
    return graph_state


def _lost(graph_state: _State) -> _State:
    """The lease was lost: the run is closed as an error and nothing else is written."""
    work = graph_state["work"]
    work.route = END
    with unit_of_work(work.agent.sessions, work.agent.clock) as tx:
        _finish_run(tx, work, RunOutcome.ERROR)
    log.warning("agent_turn_lost_its_lease", run_id=str(work.run_id))
    work.result = TurnResult(Status.LEASE_LOST, RunOutcome.ERROR, run_id=work.run_id)
    return graph_state


# --- The fallback: the model can't be reached ------------------------------------------


def _try_again_later(tx: Tx, conversation: Conversation, *, counted: bool) -> None:
    """A worker turn that couldn't run is tried again: after 1, 5 and 15 minutes (SM-12).

    After the fourth failure a person is told, and the agent stops trying. The request
    itself keeps working in code: matching, offers and expiries don't need the model.
    """
    if not counted:
        # Degraded mode: not this turn's failure. Look again soon, without counting.
        conversation.pending_turn_at = tx.now + TURN_RETRY_AFTER[0]
        return
    conversation.turn_attempts += 1
    if conversation.turn_attempts > len(TURN_RETRY_AFTER):
        log.error(
            "agent_turn_failed_4_times",
            conversation_id=str(conversation.id),
            request_id=str(conversation.request_id) if conversation.request_id else None,
        )
        _hand_to_a_person(tx, conversation, "The assistant failed 4 times on this conversation.")
        return
    conversation.pending_turn_at = tx.now + TURN_RETRY_AFTER[conversation.turn_attempts - 1]


def _hand_to_a_person(tx: Tx, conversation: Conversation, summary: str) -> None:
    """Escalates `cannot_resolve`, tells the client once, and stops asking for turns."""
    case = state.load(conversation.case_state)
    escalations.escalate(
        tx,
        client_id=conversation.client_id,
        reason=EscalationReason.CANNOT_RESOLVE,
        summary=summary,
        conversation_id=conversation.id,
        request_id=conversation.request_id,
    )
    if not case.escalated:
        case.escalated = True
        conversation.case_state = state.dump(case)
        conversations.append(
            tx,
            conversation,
            author="system",
            kind="text",
            text=fixed(Fixed.HANDED_TO_A_PERSON, case.language),
        )
    conversation.pending_turn_at = None
    conversation.followup_at = None
    conversation.turn_attempts = 0


def _fallback(graph_state: _State) -> _State:
    """The model failed after its retries, or the turn ran out of time (FX-1 to FX-3)."""
    work = graph_state["work"]
    work.route = END
    log.warning(
        "agent_turn_fell_back",
        run_id=str(work.run_id),
        error=type(work.failure).__name__ if work.failure else None,
        runs_in=work.runs_in,
    )
    with unit_of_work(work.agent.sessions, work.agent.clock) as tx:
        conversation = conversations.locked(tx, work.conversation_id)
        _finish_run(tx, work, RunOutcome.FALLBACK)
        if conversations.holds_lease(tx, conversation, work.owner):
            if work.runs_in == "worker":
                _try_again_later(tx, conversation, counted=True)
            conversations.release_lease(conversation, work.owner)
    # In a chat the client's message is kept, and the website shows "Use Search" (C15).
    work.result = TurnResult(Status.UNAVAILABLE, RunOutcome.FALLBACK, run_id=work.run_id)
    return graph_state


# --- The graph -------------------------------------------------------------------------


def _next(graph_state: _State) -> str:
    return graph_state["work"].route


def _build() -> Any:
    graph = StateGraph(_State)
    nodes = {
        "load_context": _load_context,
        "guard_input": _guard_input,
        "agent": _agent,
        "tools": _tools,
        "guard_output": _guard_output,
        "save": _save,
        "fallback": _fallback,
        "lost": _lost,
    }
    for name, node in nodes.items():
        graph.add_node(name, cast(Any, node))
    graph.add_edge(START, "load_context")
    for name in ("load_context", "guard_input", "agent", "tools", "guard_output", "save"):
        graph.add_conditional_edges(name, _next)
    graph.add_edge("fallback", END)
    graph.add_edge("lost", END)
    return graph.compile()


GRAPH = _build()
# Each model call is two steps (agent, then tools or the guard): room for N-34's eight.
_STEPS = 2 * MAX_LLM_CALLS_PER_TURN + 8


def run_turn(
    agent: Agent,
    conversation_id: uuid.UUID,
    *,
    runs_in: RunsIn,
    followup: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> TurnResult:
    """Runs one turn on a conversation, if it may run now.

    `runs_in` is "chat" for a client's message, answered while they wait, and "worker"
    for everything the clock check starts. The result says what happened; a turn that
    couldn't run changes nothing the client sees.
    """
    work = _Work(agent, conversation_id, runs_in, followup, on_progress)
    try:
        GRAPH.invoke({"work": work}, config={"recursion_limit": _STEPS})
    except Exception:
        # Not the model, not a rule: a bug or the database. The run is closed as an
        # error, the lease is given back, and the worker tries the turn again later.
        log.exception("agent_turn_crashed", run_id=str(work.run_id))
        _crashed(work)
    if work.trace is not None:
        outcome = work.result.outcome if work.result else None
        work.trace.metadata["outcome"] = outcome.value if outcome else None
        send_safely(agent.tracer, work.trace)
    assert work.result is not None
    return work.result


def _crashed(work: _Work) -> None:
    work.result = TurnResult(Status.UNAVAILABLE, RunOutcome.ERROR, run_id=work.run_id)
    try:
        with unit_of_work(work.agent.sessions, work.agent.clock) as tx:
            conversation = conversations.locked(tx, work.conversation_id)
            if work.loaded is not None:
                _finish_run(tx, work, RunOutcome.ERROR)
            if conversations.holds_lease(tx, conversation, work.owner):
                if work.runs_in == "worker":
                    _try_again_later(tx, conversation, counted=True)
                conversations.release_lease(conversation, work.owner)
    except Exception:
        log.exception("agent_turn_cleanup_failed", run_id=str(work.run_id))
