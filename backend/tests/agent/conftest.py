"""Setup for the agent's tests (docs/07 §11).

A `Scene` is one client with a chat, one pharmacy nearby and a few medicines. The model
is always the scripted one: a test writes what the model "says", and checks what the
turn did with it. No test here can reach a real model, a routing service or a tracer.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from dawalink.agent.chat import post_client_message
from dawalink.agent.guards.redact import Identity, redact
from dawalink.agent.llm.scripted import ScriptedModel, Step
from dawalink.agent.state import CaseState
from dawalink.agent.tools import Turn, for_mode, run_tool
from dawalink.agent.tracing import Tracer
from dawalink.agent.turn import Agent, RunsIn, TurnResult, run_turn
from dawalink.domain.vocabulary import AgentMode
from dawalink.services.requests import RequestLine
from dawalink.services.travel import shared_location
from tests.fakes import FakeRouting
from tests.services.conftest import World, world  # noqa: F401  (the fixture)

HAMRA = shared_location(33.8961, 35.4832)
PERSON = {
    "full_name": "Rami Haddad",
    "email": "rami.haddad@example.test",
    "phone": "+961 70 123 456",
}


def no_sleep(_: float) -> None:
    """Retries don't wait in tests."""


@dataclass
class Scene:
    world: World
    client: uuid.UUID
    chat: uuid.UUID
    pharmacy: uuid.UUID
    augmentin: uuid.UUID
    concor: uuid.UUID
    routing: FakeRouting = field(default_factory=FakeRouting)
    models: list[ScriptedModel] = field(default_factory=list)
    turns: dict[uuid.UUID, Turn] = field(default_factory=dict)

    def agent(self, *steps: Step, tracer: Tracer | None = None, **more: Any) -> Agent:
        model = ScriptedModel(*steps)
        self.models.append(model)
        extra: dict[str, Any] = {"tracer": tracer} if tracer is not None else {}
        return Agent(
            sessions=self.world.sessions(),
            clock=self.world.clock,
            model=model,
            routing=self.routing,
            sleep=no_sleep,
            **(extra | more),
        )

    @property
    def model(self) -> ScriptedModel:
        """The model of the last turn."""
        return self.models[-1]

    def say(self, text: str, conversation: uuid.UUID | None = None) -> int:
        """The client writes a message. It is stored redacted, as the API will do."""
        posted = post_client_message(
            self.world.tx(),
            client_id=self.client,
            conversation_id=conversation or self.chat,
            text=text,
            client_message_id=uuid.uuid4(),
        )
        self.world.session.flush()
        return posted.seq

    def turn(
        self,
        *steps: Step,
        text: str | None = "I need Augmentin",
        conversation: uuid.UUID | None = None,
        runs_in: RunsIn = "chat",
        **more: Any,
    ) -> TurnResult:
        """The client writes (unless `text` is None), then one turn runs on the script."""
        if text is not None:
            self.say(text, conversation)
        return run_turn(self.agent(*steps, **more), conversation or self.chat, runs_in=runs_in)

    def tool_turn(self, conversation: uuid.UUID | None = None) -> Turn:
        """What a tool is given by the turn it runs in. One per conversation, so that what
        one call remembers (a plan) is there for the next."""
        conversation_id = conversation or self.chat
        if conversation_id not in self.turns:
            row = self.conversation(conversation_id)
            run_id = self.world.make.agent_run(conversation_id=conversation_id)
            self.turns[conversation_id] = Turn(
                sessions=self.world.sessions(),
                clock=self.world.clock,
                client_id=row.client_id,
                conversation_id=conversation_id,
                run_id=run_id,
                mode=AgentMode.SOURCING if row.kind == "request" else AgentMode.ASSISTANT,
                request_id=row.request_id,
                state=CaseState(),
                routing=self.routing,
                clean=lambda text: redact(text, Identity(**PERSON)).text,
                key=f"{conversation_id}:test",
            )
        return self.turns[conversation_id]

    def tool(self, name: str, conversation: uuid.UUID | None = None, **arguments: Any) -> Any:
        """Calls one tool as the model would, with JSON arguments. Returns its JSON result."""
        turn = self.tool_turn(conversation)
        sent = json.loads(json.dumps(arguments, default=str))
        outcome = run_tool(turn, for_mode(turn.mode), name, sent)
        self.world.session.expire_all()
        return json.loads(outcome.as_json())

    def stock(self, product: uuid.UUID | None = None, units: int = 5, **values: Any) -> uuid.UUID:
        defaults = {
            "pharmacy_id": self.pharmacy,
            "product_id": product or self.augmentin,
            "days_left": 60,
        }
        return self.world.make.item(**(defaults | {"qty_on_hand": units} | values))  # type: ignore[no-any-return]

    def run(self, result: TurnResult | None = None) -> Any:
        """The `agent_runs` row of a turn, or of the newest one."""
        if result is not None and result.run_id is not None:
            return self.world.one("SELECT * FROM agent_runs WHERE id = :id", id=result.run_id)
        # The run of the newest agent message: runs made at the same clock time have no
        # order of their own.
        return self.world.one(
            "SELECT r.* FROM agent_runs r JOIN chat_messages m ON m.agent_run_id = r.id "
            "ORDER BY m.id DESC LIMIT 1"
        )

    def messages(self, conversation: uuid.UUID | None = None) -> list[Any]:
        return self.world.all(
            "SELECT * FROM chat_messages WHERE conversation_id = :c ORDER BY seq",
            c=conversation or self.chat,
        )

    def conversation(self, conversation: uuid.UUID | None = None) -> Any:
        return self.world.one(
            "SELECT * FROM conversations WHERE id = :c", c=conversation or self.chat
        )

    def tool_calls(self, result: TurnResult) -> list[tuple[str, bool, str | None]]:
        rows = self.world.all(
            "SELECT tool, ok, error_code FROM agent_tool_calls WHERE agent_run_id = :r ORDER BY id",
            r=result.run_id,
        )
        return [(row.tool, row.ok, row.error_code) for row in rows]

    def start_request(self, *lines: RequestLine) -> tuple[uuid.UUID, uuid.UUID]:
        """The client starts a sourcing request: `(request, its thread)`."""
        from dawalink.services import requests

        tx = self.world.tx()
        request = requests.create_request(
            tx,
            client_id=self.client,
            lines=lines or (RequestLine(self.augmentin), RequestLine(self.concor)),
            location=HAMRA,
            alternatives_ok=False,
            idempotency_key=f"start-{uuid.uuid4()}",
        )
        self.world.settle(tx)
        thread = self.world.one(
            "SELECT id FROM conversations WHERE request_id = :r", r=request.id
        ).id
        return request.id, thread


@pytest.fixture
def scene(world: World) -> Scene:  # noqa: F811
    client = world.make.client(person=PERSON)
    return Scene(
        world,
        client=client,
        chat=world.make.conversation(
            client_id=client,
            loc_lat=HAMRA.point.lat,
            loc_lon=HAMRA.point.lon,
            loc_source="shared",
        ),
        pharmacy=world.make.pharmacy(
            name="Hamra Pharmacy", address="12 Secret Lane", lat=33.897, lon=35.484
        ),
        augmentin=world.make.product(
            moph_name="AUGMENTIN 1G", search_name="augmentin 1g", public_price_lbp=1_000_000
        ),
        concor=world.make.product(
            moph_name="CONCOR 5MG", search_name="concor 5mg", public_price_lbp=800_000
        ),
    )
