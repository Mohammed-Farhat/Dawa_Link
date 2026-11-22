"""Contenders share backend authority; auxiliary calls cannot run business tools."""

import json
from typing import Any

import pytest

from dawalink.agent.architectures import Facts, decode
from dawalink.agent.llm import LLMRejected, Prompt, UserText
from dawalink.agent.llm.scripted import call, reply
from dawalink.agent.turn import Status
from dawalink.db.models import Conversation
from tests.agent.conftest import Scene


def facts(**more: Any) -> Any:
    data: dict[str, Any] = {
        "intent": "find",
        "language": "english",
        "items": [{"name": "augmentin"}],
        "transport": "car",
        "pickup_day": "2026-10-20",
        "days_of_use": 7,
    }
    return call("record_facts", **(data | more))


def test_default_current_keeps_original_prompt_calls_and_usage(scene: Scene) -> None:
    result = scene.turn(reply("Which strength?"))
    assert result.status == Status.DONE
    assert len(scene.model.seen) == 1
    assert "Hard rules" in scene.model.seen[0].system[0]
    assert scene.run(result).llm_calls == 1


@pytest.mark.parametrize("runs_in", ["chat", "worker"])
def test_staged_missing_information_routes_without_search(scene: Scene, runs_in: Any) -> None:
    if runs_in == "worker":
        scene.world.session.get_one(
            Conversation, scene.chat
        ).pending_turn_at = scene.world.clock.now()
    result = scene.turn(
        facts(transport=None, pickup_day=None),
        text="I need Augmentin for seven days",
        architecture="staged",
        runs_in=runs_in,
    )
    assert result.status == Status.DONE
    assert "car or on foot" in (result.text or "")
    assert "which day you will pick up" in (result.text or "")
    assert "days of use" not in (result.text or "")
    assert scene.tool_calls(result) == []
    assert scene.run(result).llm_calls == 1
    assert {t.name for t in scene.model.seen[0].tools} == {"record_facts"}


def test_staged_replacement_facts_remove_items_and_keep_unknowns(scene: Scene) -> None:
    def inspect(prompt: Prompt) -> Any:
        message = prompt.messages[-1]
        assert isinstance(message, UserText)
        snapshot = json.loads(message.text.split(": ", 1)[1].split(" Use these", 1)[0])
        assert [i["name"] for i in snapshot["items"]] == ["concor"]
        assert snapshot["items"][0]["qty"] == 2
        assert snapshot["budget"] == {"amount": 5.0, "currency": "USD"}
        assert snapshot["items"][0]["form"] is None
        return call("search_catalog", query="concor")

    result = scene.turn(
        facts(
            items=[{"name": "augmentin"}, {"name": "concor", "qty": 2}],
            removed_items=["augmentin"],
            budget={"amount": 5, "currency": "USD"},
        ),
        inspect,
        reply("Which strength do you need?"),
        text="Remove Augmentin, two Concor instead, five dollars per box.",
        architecture="staged",
    )
    assert result.status == Status.DONE
    assert scene.tool_calls(result) == [("search_catalog", True, None)]
    assert scene.run(result).llm_calls == 3


@pytest.mark.parametrize("architecture", ["staged", "verified"])
def test_auxiliary_failure_is_bounded_and_saves_no_business_action(
    scene: Scene, architecture: Any
) -> None:
    prefix = [reply("Hello")] if architecture == "verified" else []
    result = scene.turn(*prefix, LLMRejected("invalid"), architecture=architecture)
    assert result.status == Status.UNAVAILABLE
    assert scene.tool_calls(result) == []


def test_verifier_detects_wrong_draft_and_one_correction_is_guarded(scene: Scene) -> None:
    result = scene.turn(
        reply("I reserved three boxes."),
        call("review_draft", issues=["No reservation or client approval exists"]),
        reply("Please choose a medicine first."),
        architecture="verified",
    )
    assert result.status == Status.DONE
    assert result.text == "Please choose a medicine first."
    assert scene.run(result).llm_calls == 3
    assert scene.run(result).tool_calls == 0
    assert scene.run(result).guardrails == ["verifier_issues"]
    assert {t.name for t in scene.model.seen[1].tools} == {"review_draft"}


def test_verifier_cannot_execute_business_tools(scene: Scene) -> None:
    result = scene.turn(
        reply("Hello"), call("open_claim", listing_id="forbidden"), architecture="verified"
    )
    assert result.status == Status.UNAVAILABLE
    assert scene.tool_calls(result) == []


def test_verifier_correction_still_cannot_attach_unowned_cards(scene: Scene) -> None:
    result = scene.turn(
        reply("Hello"),
        call("review_draft", issues=["Wrong greeting"]),
        reply("Choose this.", proposal_ids=["00000000-0000-0000-0000-000000000001"]),
        architecture="verified",
    )
    assert result.outcome == "guardrail_blocked"
    assert result.proposal_ids == ()
    assert len(scene.model.seen) == 3


def test_verifier_no_issues_sends_original_draft(scene: Scene) -> None:
    scene.world.session.get_one(Conversation, scene.chat).pending_turn_at = scene.world.clock.now()
    result = scene.turn(
        reply("Which strength?"),
        call("review_draft", issues=[]),
        architecture="verified",
        runs_in="worker",
    )
    assert result.status == Status.DONE
    assert result.text == "Which strength?"
    assert scene.run(result).llm_calls == 2


def test_auxiliary_calls_use_turn_deadline(scene: Scene) -> None:
    times = iter([0.0, 100000.0, 100001.0, 100002.0, 100003.0, 100004.0])
    result = scene.turn(architecture="staged", monotonic=lambda: next(times))
    assert result.status == Status.UNAVAILABLE
    assert not scene.model.seen


def test_extractor_rejects_actions_and_preserves_unknown_facts() -> None:
    with pytest.raises(LLMRejected):
        decode(call("reserve", qty=1), Facts, "record_facts")
    snapshot = Facts(intent="find", language="english", items=[{"name": "panadol"}])
    assert snapshot.transport is None
    assert snapshot.items[0].qty is None
    assert snapshot.missing() == ["transport", "pickup day", "days of use"]


def test_extraction_and_verification_traces_keep_shared_scorer_contract(scene: Scene) -> None:
    import dataclasses

    from dawalink.evals.score_understanding import seen_in
    from tests.agent.test_worker_turns import RecordingTracer

    tracer = RecordingTracer()
    result = scene.turn(facts(transport=None), tracer=tracer, architecture="staged")
    assert result.status == Status.DONE
    trace = dataclasses.asdict(tracer.traces[0])
    for span in trace["spans"]:
        span["seconds"] = span["ended"] - span["started"]
    seen = seen_in(trace, [])
    assert seen.model_calls == 1
    assert seen.tools == []


def test_verifier_receives_reference_policy_in_its_read_only_context(scene: Scene) -> None:
    def review(prompt: Prompt) -> Any:
        message = prompt.messages[0]
        assert isinstance(message, UserText)
        payload = json.loads(message.text)
        assert any("Ask first, then search" in part for part in payload["application_rules"])
        assert {t.name for t in prompt.tools} == {"review_draft"}
        return call("review_draft", issues=[])

    result = scene.turn(reply("Do you go by car or on foot?"), review, architecture="verified")
    assert result.status == Status.DONE
