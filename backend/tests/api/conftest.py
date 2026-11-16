"""Setup for the API's tests.

`api` is the real application on top of a test's `World`: every row a request writes
lives in the test's own transaction and is undone at the end. The model, when a test
needs one, is the scripted one. Every call carries the website's `Origin`, as a browser
on our website would send it.
"""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from dawalink.agent.llm.scripted import ScriptedModel, Step
from dawalink.agent.turn import Agent
from dawalink.api.main import create_app
from dawalink.config import Settings
from dawalink.db.models import User
from dawalink.services import auth
from tests.agent.conftest import HAMRA, PERSON, no_sleep
from tests.conftest import WEBSITE, make_settings
from tests.fakes import FakeRouting
from tests.services.conftest import World, world  # noqa: F401  (the fixture)

PASSWORD = "a long enough passphrase"


class Mailbox:
    """Catches what the worker would send: `(to, subject, body)`."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


@dataclass
class Api:
    world: World
    settings: Settings
    apps: list[TestClient] = field(default_factory=list)
    models: list[ScriptedModel] = field(default_factory=list)

    def app(self, *steps: Step, assistant: bool = True, **overrides: Any) -> FastAPI:
        """The application. `steps` is what the scripted model says, call after call."""
        agent: Agent | None = None
        if assistant:
            model = ScriptedModel(*steps)
            self.models.append(model)
            agent = Agent(
                sessions=self.world.sessions(),
                clock=self.world.clock,
                model=model,
                routing=FakeRouting(),
                sleep=no_sleep,
            )
        settings = self.settings.model_copy(update=overrides) if overrides else self.settings
        return create_app(
            settings, agent=agent, clock=self.world.clock, sessions=self.world.sessions()
        )

    def http(self, *steps: Step, **more: Any) -> TestClient:
        """A browser on our website, talking to the application."""
        client = TestClient(self.app(*steps, **more), headers={"Origin": WEBSITE})
        client.__enter__()
        self.apps.append(client)
        return client

    def token(self, user_id: uuid.UUID) -> dict[str, str]:
        """The login header of this user, without going through the login form."""
        tx = self.world.tx()
        logged_in = auth.start_session(tx, tx.session.get_one(User, user_id))
        self.world.session.flush()
        return {"Authorization": f"Bearer {logged_in.token}"}

    def client(self, status: str = "ACTIVE", **person: Any) -> uuid.UUID:
        """A client who can log in with `PASSWORD`."""
        details = {"password_hash": auth.hash_password(PASSWORD)} | person
        if status != "UNVERIFIED":
            details.setdefault("email_verified_at", self.world.clock.now())
        return self.world.make.client(status, person=details)  # type: ignore[no-any-return]

    def emails(self) -> list[tuple[str, str, str]]:
        """Runs the worker's email task, and returns what it sent."""
        mailbox = Mailbox()
        tasks = self.world.clock_tasks(mailer=mailbox)
        tasks._website_url = WEBSITE
        tasks.send_emails()
        return mailbox.sent


@pytest.fixture
def api(world: World, test_database_url: str, tmp_path: Path) -> Iterator[Api]:  # noqa: F811
    made = Api(world, make_settings(test_database_url, tmp_path))
    try:
        yield made
    finally:
        for client in made.apps:
            client.__exit__(None, None, None)


def code_of(response: Response) -> str:
    """The stable code of an error answer: what tests depend on, never the message."""
    return str(response.json()["error"]["code"])


def events_of(response: Response) -> list[tuple[str, Any]]:
    """The events of a chat stream, in order: `(name, data)`."""
    events: list[tuple[str, Any]] = []
    for block in response.text.split("\n\n"):
        lines = [line for line in block.splitlines() if not line.startswith(":")]
        if not lines:
            continue
        name = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


__all__ = ["HAMRA", "PASSWORD", "PERSON", "Api", "Mailbox", "code_of", "events_of"]
