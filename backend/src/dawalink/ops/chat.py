"""Talk to the agent from the terminal, as one of the demo clients.

    python -m dawalink.ops.chat "baddi panadol"            the client writes in the chat
    python -m dawalink.ops.chat --new "I need Concor 5mg"  ...in a new chat
    python -m dawalink.ops.chat --tap 1                     the client taps the 1st card shown
    python -m dawalink.ops.chat --work                      the worker runs the waiting turns
    python -m dawalink.ops.chat --request "any news?"      the client writes in their request

Run it from `backend/` with `uv run --env-file ../.env`. There is no website yet, so this
is how a developer sees the agent work: every message, tap and turn goes through the
same code the API and the worker will use, with the model named in the settings
(`LLM_PROVIDER`, `LLM_MODEL`). It works on the development database, never in AWS.
"""

import argparse
import json
import sys
import uuid
from dataclasses import replace
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent.chat import post_client_message
from dawalink.agent.pending import PendingTurns
from dawalink.agent.setup import build_agent
from dawalink.agent.tools.propose import card_of
from dawalink.agent.tracing import TurnTrace
from dawalink.agent.turn import Agent, run_turn
from dawalink.config import ConfigError, load_settings
from dawalink.db.models import AgentRun, ChatMessage, Conversation, Proposal, User
from dawalink.db.session import make_engine
from dawalink.domain.clock import BEIRUT, Clock, ManualClock
from dawalink.observability.logging import configure_logging
from dawalink.services import conversations, proposals, travel
from dawalink.services.clock import AppClock
from dawalink.services.context import unit_of_work
from dawalink.services.errors import ServiceError

# Hamra, Beirut: where the demo client "is".
DEFAULT_LOCATION = (33.896, 35.483)


def _say(line: str = "") -> None:
    sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="replace"))
    sys.stdout.flush()


class StepPrinter:
    """Prints a turn's steps instead of sending them anywhere: what a trace holds."""

    def new_trace_id(self) -> str:
        return uuid.uuid4().hex

    def send(self, trace: TurnTrace) -> None:
        for span in trace.spans:
            took = int((span.ended - span.started) * 1000)
            _say(f"  step {span.name} ({took} ms) {json.dumps(span.metadata, default=str)}")
            if span.kind == "tool":
                _say(f"       in:  {json.dumps(span.input, default=str)[:400]}")
                _say(f"       out: {json.dumps(span.output, default=str)[:700]}")
            elif span.kind == "generation" and span.output:
                _say(f"       said: {json.dumps(span.output, default=str)[:700]}")


def _show(session: Session, message: ChatMessage) -> None:
    """One message as the client would see it: text, cards, chips, and what the turn cost."""
    if message.kind == "event":
        _say(f"  (event for the agent: {message.text_redacted})")
        return
    if message.author == "system":
        for card in message.cards or []:
            _say(f"system > {json.dumps(card, default=str)[:300]}")
        if message.text_redacted:
            _say(f"system > {message.text_redacted}")
        return
    who = "agent  >" if message.author == "agent" else "client >"
    _say(f"{who} {message.text_redacted}")
    if message.author != "agent":
        return
    for position, proposal_id in enumerate(message.cards or [], start=1):
        proposal = session.get(Proposal, uuid.UUID(str(proposal_id)))
        if proposal is None:
            continue
        card = card_of(proposal)
        star = " [recommended]" if card.recommended else ""
        _say(f"  card {position}: {card.title}{star}")
        for label, value in card.lines:
            _say(f"        {label}: {value}")
        if card.prescription_notice:
            _say("        Prescription needed: bring it to the pharmacy.")
    if message.quick_replies:
        _say("  chips: " + " | ".join(message.quick_replies))
    if message.agent_run_id:
        run = session.get_one(AgentRun, message.agent_run_id)
        _say(
            f"  [{run.model}, {run.trigger}, {run.latency_ms} ms, {run.llm_calls} model calls, "
            f"{run.tool_calls} tool calls ({run.tool_errors} refused), "
            f"{run.tokens_in}+{run.tokens_out} tokens, ${run.cost_usd}, "
            f"outcome {run.outcome}, guards {run.guardrails}]"
        )


def _show_since(sessions: sessionmaker[Session], client_id: uuid.UUID, after_id: int) -> int:
    """Prints this client's messages newer than `after_id`. Returns the newest ID."""
    with sessions() as session:
        rows = session.execute(
            select(ChatMessage, Conversation.kind)
            .join(Conversation, Conversation.id == ChatMessage.conversation_id)
            .where(Conversation.client_id == client_id, ChatMessage.id > after_id)
            .order_by(ChatMessage.id)
        ).all()
        for message, kind in rows:
            if kind == "request":
                _say("  -- in the request's thread --")
            _show(session, message)
        return rows[-1][0].id if rows else after_id


def _newest_message_id(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        return session.execute(select(ChatMessage.id).order_by(ChatMessage.id.desc())).scalar() or 0


def _conversation(
    sessions: sessionmaker[Session], clock: Clock, client_id: uuid.UUID, *, thread: bool, new: bool
) -> uuid.UUID:
    """The client's chat (created, and given a location, if needed) or newest request thread."""
    with unit_of_work(sessions, clock) as tx:
        if thread:
            found = tx.session.execute(
                select(Conversation.id)
                .where(Conversation.client_id == client_id, Conversation.kind == "request")
                .order_by(Conversation.created_at.desc())
            ).scalar()
            if found is None:
                raise ConfigError("This client has no sourcing request yet.")
            return found
        if new:
            for old in tx.session.execute(
                select(Conversation).where(
                    Conversation.client_id == client_id,
                    Conversation.kind == "chat",
                    Conversation.status == "ACTIVE",
                )
            ).scalars():
                old.status = "ARCHIVED"
            tx.session.flush()
        chat = conversations.active_chat(tx, client_id)
        if chat.loc_lat is None:
            here = travel.shared_location(*DEFAULT_LOCATION)
            chat.loc_lat, chat.loc_lon = here.point.lat, here.point.lon
            chat.loc_source, chat.loc_set_at = "shared", tx.now
        return chat.id


def _tap(
    sessions: sessionmaker[Session],
    clock: Clock,
    client_id: uuid.UUID,
    conversation_id: uuid.UUID,
    position: int,
) -> None:
    """The client taps the card at `position` of the newest agent message that has cards."""
    with sessions() as session:
        cards = session.execute(
            select(ChatMessage.cards)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.author == "agent",
                ChatMessage.cards != [],
            )
            .order_by(ChatMessage.seq.desc())
        ).scalar()
    if not cards or position > len(cards):
        raise ConfigError("There is no such card in the agent's last message with cards.")
    proposal_id = uuid.UUID(str(cards[position - 1]))
    _say(f"client > [taps card {position}]")
    try:
        with unit_of_work(sessions, clock) as tx:
            done = proposals.execute(tx, client_id=client_id, proposal_id=proposal_id)
            made = [f"{order.ref} ({order.state})" for order in done.orders]
            request = done.request.ref if done.request else None
        _say(
            f"  done: {done.kind.value}"
            + (f", orders {made}" if made else "")
            + (f", request {request}" if request else "")
        )
    except ServiceError as error:
        _say(f"  refused: {error.code.value}: {error} {error.details or ''}")
        with unit_of_work(sessions, clock) as tx:
            proposals.report_failed_group(
                tx, client_id=client_id, proposal_id=proposal_id, error=error
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("text", nargs="?", help="what the client writes")
    parser.add_argument("--client", type=int, default=1, help="which demo client (1 to 6)")
    parser.add_argument("--new", action="store_true", help="start a new chat first")
    parser.add_argument("--request", action="store_true", help="write in the newest request")
    parser.add_argument("--tap", type=int, metavar="N", help="tap the Nth card shown")
    parser.add_argument("--work", action="store_true", help="run the worker's waiting turns")
    parser.add_argument("--steps", action="store_true", help="print every step of each turn")
    parser.add_argument(
        "--at", metavar="YYYY-MM-DDTHH:MM", help="pretend it is this Beirut time (development)"
    )
    arguments = parser.parse_args()

    settings = load_settings()
    if settings.app_env == "aws":
        raise ConfigError("This command is for development only.")
    configure_logging("WARNING")
    engine = make_engine(settings.database_url)
    sessions: sessionmaker[Session] = sessionmaker(engine, expire_on_commit=False)
    clock: Clock = AppClock(engine, demo_mode=settings.demo_mode)
    if arguments.at:
        clock = ManualClock(datetime.fromisoformat(arguments.at).replace(tzinfo=BEIRUT))
    built = build_agent(settings, sessions, clock)
    if built is None:
        raise ConfigError("Set LLM_PROVIDER (ollama or anthropic) to chat with the agent.")
    agent: Agent = replace(built, tracer=StepPrinter()) if arguments.steps else built

    email = f"client{arguments.client:02d}@demo.dawalink.test"
    with sessions() as session:
        client_id = session.execute(select(User.id).where(User.email == email)).scalar()
    if client_id is None:
        raise ConfigError("No demo client found. Run: python -m dawalink.ops.prepare_db")
    conversation_id = _conversation(
        sessions, clock, client_id, thread=arguments.request, new=arguments.new
    )
    seen = _newest_message_id(sessions)

    if arguments.tap:
        _tap(sessions, clock, client_id, conversation_id, arguments.tap)
    if arguments.text:
        with unit_of_work(sessions, clock) as tx:
            posted = post_client_message(
                tx,
                client_id=client_id,
                conversation_id=conversation_id,
                text=arguments.text,
                client_message_id=uuid.uuid4(),
            )
        seen = _show_since(sessions, client_id, seen)
        if not posted.worker_runs_the_turn:
            result = run_turn(
                agent,
                conversation_id,
                runs_in="chat",
                on_progress=lambda label: _say(f"        … {label}"),
            )
            if result.message_seq is None:
                _say(f"(no reply: {result.status.value})")
    if arguments.work or arguments.request or arguments.tap:
        # What the worker would do within seconds: the turns that are waiting.
        PendingTurns(agent).run_pending_turns()
    _show_since(sessions, client_id, seen)


if __name__ == "__main__":
    main()
