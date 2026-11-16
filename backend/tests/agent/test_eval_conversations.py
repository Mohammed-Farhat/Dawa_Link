"""The runner of suite E7 (docs/08 E7): a played client and the agent talk until cards
appear. Both are stand-ins here: no paid service."""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from dawalink.agent.llm import ModelReply, Prompt, ToolCall
from dawalink.evals.datasets import UCase
from dawalink.evals.played_client import personas
from dawalink.evals.run_conversations import MAX_CLIENT_MESSAGES, run, summary
from dawalink.sim import save
from tests.agent.conftest import Scene


@dataclass(frozen=True)
class Someone:
    id: uuid.UUID
    lat: float = 33.8961
    lon: float = 35.4832


class AgentThatAsksOnce:
    """Asks the three things, and says where to go once the client said "bukra"."""

    name = "asks-once"

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        said = getattr(prompt.messages[0], "text", "")
        text = "Pharmacy A has it." if "bukra" in said else "Car or on foot? Which day?"
        return ModelReply(text="", tool_calls=(ToolCall("t1", "reply", {"text": text}),))


class ClientThatAnswers:
    """Names the medicine, then answers. Leaves when told where to go without a card."""

    name = "client"

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        chat = getattr(prompt.messages[0], "text", "")
        if "Pharmacy A" in chat:
            call = ToolCall("c", "leave", {"why": "nothing to tap"})
        elif "Which day" in chat:
            arguments = {"text": "3ande siyyara, bukra", "says": ["transport", "day"]}
            call = ToolCall("c", "write_message", arguments)
        else:
            call = ToolCall("c", "write_message", {"text": "baddi concor 5", "says": []})
        return ModelReply(text="", tool_calls=(call,))


class ClientThatNeverStops(ClientThatAnswers):
    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        call = ToolCall("c", "write_message", {"text": "baddi concor 5", "says": []})
        return ModelReply(text="", tool_calls=(call,))


def people() -> list[Any]:
    case = UCase.model_validate(
        {
            "id": "U-0003",
            "lang": "arabizi",
            "category": "clear",
            "text": "baddi concor 5",
            "gold": {
                "intent": "find",
                "items": [{"match": {"name": "concor", "strength": "5mg"}}],
                "expected": "propose_options",
            },
            "author": "test",
        }
    )
    return [p for p in personas([case] * 3) if p.style == "bare"]


def played(scene: Scene, folder: Path, client_model: Any) -> list[dict[str, Any]]:
    return run(
        people(),
        sessions=scene.world.sessions(),
        clock=scene.world.clock,
        model=AgentThatAsksOnce(),
        client_model=client_model,
        tracer=save.FileTracer(folder),
        folder=folder,
        clients=[Someone(scene.client)],  # type: ignore[list-item]
        max_usd=Decimal(1),
    )


def test_a_conversation_is_played_scored_and_saved(scene: Scene, tmp_path: Path) -> None:
    (row,) = played(scene, tmp_path, ClientThatAnswers())

    assert (row["id"], row["style"], row["ended"]) == ("U-0003:bare", "bare", "client_left")
    assert [(e["client"], e["says"], e["agent"]) for e in row["exchanges"]] == [
        ("baddi concor 5", [], "Car or on foot? Which day?"),
        ("3ande siyyara, bukra", ["transport", "day"], "Pharmacy A has it."),
    ]
    # Told where to go without a card, and nothing was searched.
    assert row["checks"]["gets_cards"] is False
    assert row["checks"]["right_medicine"] is False
    assert row["checks"]["asks_again"] is False
    result = summary([row])
    assert result["ended"] == {"client_left": 1}
    assert result["checks"]["gets_cards"] == {"cases": 1, "yes": 0, "share": 0.0}
    assert result["by_style"]["bare"] == {
        "conversations": 1,
        "ended_with_cards": 0,
        "client_messages_to_cards": 0.0,
    }
    assert len((tmp_path / "turns.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_a_conversation_that_goes_in_circles_is_cut(scene: Scene, tmp_path: Path) -> None:
    (row,) = played(scene, tmp_path, ClientThatNeverStops())

    assert (row["ended"], row["client_messages"]) == ("too_long", MAX_CLIENT_MESSAGES)
