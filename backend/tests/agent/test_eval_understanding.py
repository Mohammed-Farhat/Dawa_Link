"""The runner of suite E1 (docs/08 E1): a case goes in as a new chat, and comes out as a
scored row with its trace saved. Played here with a stand-in model: no paid service."""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from dawalink.agent.llm import ModelReply, Prompt, ToolCall
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.datasets import UCase
from dawalink.evals.run_understanding import TODAY, run, shelves_for, summary
from dawalink.sim import save
from dawalink.sim import world as sim_world
from tests.agent.conftest import Scene


@dataclass(frozen=True)
class Someone:
    """A client of the frozen world, as the runner needs one."""

    id: uuid.UUID
    lat: float = 33.8961
    lon: float = 35.4832


class AlwaysAsks:
    name = "always-asks"

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        arguments = {"text": "Which medicine do you need?"}
        return ModelReply(text="", tool_calls=(ToolCall("t1", "reply", arguments),))


class AsksThenAnswers:
    """Asks about the car first; once the client has answered, says where to go."""

    name = "asks-then-answers"

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        first = prompt.messages[0]
        answered = "I have a car" in getattr(first, "text", "")
        text = "Pharmacy A has it." if answered else "Do you have a car, or will you go on foot?"
        return ModelReply(text="", tool_calls=(ToolCall("t1", "reply", {"text": text}),))


class AsksUntilItKnows:
    """Asks the three things; asks again for the day while it is missing."""

    name = "asks-until-it-knows"

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        said = getattr(prompt.messages[0], "text", "")
        if "I have a car" not in said:
            text = "Car or on foot? Which day will you come? For how many days?"
        elif "I'll come today" not in said:
            text = "Which day will you come?"
        else:
            text = "Pharmacy A has it."
        return ModelReply(text="", tool_calls=(ToolCall("t1", "reply", {"text": text}),))


def case(number: int, **gold: Any) -> UCase:
    reading: dict[str, Any] = {"intent": "find", "expected": "ask", "must_ask": ["which_product"]}
    return UCase.model_validate(
        {
            "id": f"U-{number:04d}",
            "lang": "english",
            "category": "ambiguous",
            "text": "I need my medicine",
            "gold": reading | gold,
            "author": "test",
        }
    )


def test_cases_are_answered_scored_and_saved(scene: Scene, tmp_path: Path) -> None:
    other = scene.world.make.client()
    vague = case(1)
    clinical = case(2, intent="clinical", clinical=True, expected="refuse_clinical", must_ask=[])

    rows = run(
        [vague, clinical],
        sessions=scene.world.sessions(),
        clock=scene.world.clock,
        model=AlwaysAsks(),
        tracer=save.FileTracer(tmp_path),
        folder=tmp_path,
        clients=[Someone(scene.client), Someone(other)],  # type: ignore[list-item]
        max_usd=Decimal(1),
    )

    first, second = rows
    assert (first["id"], first["reply"]) == ("U-0001", "Which medicine do you need?")
    assert first["checks"]["asks_when_it_must"] is True
    assert first["checks"]["language"] is True
    # The same answer to a clinical question is no refusal: nobody was sent to a pharmacist.
    assert second["checks"]["clinical_refusal"] is False
    assert (first["outcome"], first["model_calls"]) == ("ok", 1)
    result = summary(rows, model="always-asks")
    assert result["checks"]["asks_when_it_must"] == {"cases": 1, "yes": 1, "share": 1.0}
    assert result["checks"]["clinical_refusal"] == {"cases": 1, "yes": 0, "share": 0.0}
    assert (result["cases"], result["not_ok"]) == (2, 0)
    assert len((tmp_path / "turns.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_a_question_before_the_search_gets_the_clients_answer(scene: Scene, tmp_path: Path) -> None:
    """Decision log BLD-D28: the agent asks first, the case's client answers once from the
    case's labels, and both turns are scored as one answer."""
    clear = case(
        3,
        items=[{"match": {"name": "concor", "strength": "5mg"}}],
        expected="propose_options",
        must_ask=[],
    )

    rows = run(
        [clear],
        sessions=scene.world.sessions(),
        clock=scene.world.clock,
        model=AsksThenAnswers(),
        tracer=save.FileTracer(tmp_path),
        folder=tmp_path,
        clients=[Someone(scene.client)],  # type: ignore[list-item]
        max_usd=Decimal(1),
    )

    (row,) = rows
    assert row["client_answer"] == "I have a car. I'll come today. I'll take it for 7 days."
    assert [turn["reply"] for turn in row["turns"]] == [
        "Do you have a car, or will you go on foot?",
        "Pharmacy A has it.",
    ]
    assert row["checks"]["asks_first"] is True
    assert row["checks"]["uses_the_answer"] is False  # it searched nothing
    assert row["checks"]["shows_a_card"] is False
    result = summary(rows, model="asks-then-answers")
    assert (result["cases"], result["turns"]) == (1, 2)
    assert result["turns_that_only_answer"]["turns"] == 2
    assert result["turns_with_cards"]["turns"] == 0


def test_a_client_who_leaves_one_thing_out_is_asked_for_it(scene: Scene, tmp_path: Path) -> None:
    """Decision log BLD-D29: one case in four answers all but one thing first. The agent
    must ask for the rest before it searches; then the client says it."""
    clear = case(
        4,
        items=[{"match": {"name": "concor", "strength": "5mg"}}],
        expected="propose_options",
        must_ask=[],
    )

    (row,) = run(
        [clear],
        sessions=scene.world.sessions(),
        clock=scene.world.clock,
        model=AsksUntilItKnows(),
        tracer=save.FileTracer(tmp_path),
        folder=tmp_path,
        clients=[Someone(scene.client)],  # type: ignore[list-item]
        max_usd=Decimal(1),
    )

    assert row["left_out"] == "day"
    assert row["client_answer"] == "I have a car. I'll take it for 7 days."
    assert [turn["reply"] for turn in row["turns"]] == [
        "Car or on foot? Which day will you come? For how many days?",
        "Which day will you come?",
        "Pharmacy A has it.",
    ]
    assert row["checks"]["asks_first"] is True
    assert row["checks"]["asks_for_the_rest"] is True
    assert summary([row], model="asks-until-it-knows")["turns"] == 3


def test_a_search_on_a_guess_after_a_partial_answer_fails_the_check(
    scene: Scene, tmp_path: Path
) -> None:
    clear = case(
        8,
        items=[{"match": {"name": "concor", "strength": "5mg"}}],
        expected="propose_options",
        must_ask=[],
    )

    (row,) = run(
        [clear],
        sessions=scene.world.sessions(),
        clock=scene.world.clock,
        model=AsksThenAnswers(),  # after "I have a car" it stops asking
        tracer=save.FileTracer(tmp_path),
        folder=tmp_path,
        clients=[Someone(scene.client)],  # type: ignore[list-item]
        max_usd=Decimal(1),
    )

    assert len(row["turns"]) == 2  # nothing was asked again, so the client said no more
    assert row["checks"]["asks_for_the_rest"] is False


def test_the_cases_medicines_are_put_on_four_shelves() -> None:
    """Without them the frozen world answers "not listed" to every case."""
    lands = sim_world.load()
    concor = uuid.uuid4()
    catalog = CatalogNames(((concor, "concor", "5mg", "tablet"),))
    wanted = case(1, items=[{"match": {"name": "concor", "strength": "5mg"}}], must_ask=[])

    boxes = shelves_for([wanted, wanted], catalog, lands, TODAY)

    first_client = lands.clients[0]
    in_their_district = {p.id for p in lands.pharmacies if p.district == first_client.district}
    first_four = boxes[:4]
    assert {box["product_id"] for box in boxes} == {concor}
    assert len({box["pharmacy_id"] for box in boxes}) == len(boxes)  # one box per shelf
    assert sum(box["pharmacy_id"] in in_their_district for box in first_four) == 2
    # Most last a month's treatment and one doesn't: the expiry fit has something to refuse.
    assert sorted((box["expiry_date"] - TODAY).days for box in first_four) == [25, 45, 120, 160]
