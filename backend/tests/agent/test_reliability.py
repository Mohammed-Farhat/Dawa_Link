"""How the agent copes with what fails around it: a turn that crashes before it holds its
lease, a routing service that is down, a turn that runs out of time, a turn left unsaved.

Docs/04 SM-12, N-37 to N-39; docs/07 §8; docs/09 FA-17, FX-1, FX-18. A#21, A#25, A#27.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from dawalink.agent import context, limits
from dawalink.agent import turn as turn_module
from dawalink.agent.llm import LLMUnavailable, Prompt
from dawalink.agent.llm.scripted import call, reply
from dawalink.agent.pending import PendingTurns
from dawalink.agent.turn import Status
from dawalink.domain.geo import Point
from dawalink.services import travel
from tests.agent.conftest import Scene
from tests.conftest import logged
from tests.fakes import FakeRouting

DOWN = LLMUnavailable("down")


class Stopwatch:
    """The agent's real-time clock, moved by hand: what the time limit is counted on."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def work(scene: Scene, *steps: Any, **more: Any) -> int:
    """One pass of the worker's agent loop, on a script."""
    return PendingTurns(scene.agent(*steps, **more)).run_pending_turns()


def broken_load(*_: Any, **__: Any) -> Any:
    raise RuntimeError("a bug in the opening transaction")


class TestATurnThatCrashesBeforeItHoldsItsLease:
    """A#27: the crash undoes the lease with the rest of the opening transaction."""

    def test_it_counts_as_an_attempt_and_waits_before_it_is_tried_again(
        self, scene: Scene, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, thread = scene.start_request()
        monkeypatch.setattr(context, "load", broken_load)

        first = work(scene, reply("never reached"))
        again = work(scene, reply("never reached"))

        conversation = scene.conversation(thread)
        assert (first, again) == (0, 0)
        assert conversation.turn_attempts == 1
        assert conversation.pending_turn_at == scene.world.clock.now() + timedelta(minutes=1)
        assert conversation.turn_lease_until is None
        # The second pass found nothing due: no second crash.
        assert scene.world.one("SELECT count(*) AS n FROM agent_runs").n == 0

    def test_after_the_fourth_a_person_is_told(
        self, scene: Scene, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SM-12: the same hand-over as for a model that keeps failing."""
        request, thread = scene.start_request()
        monkeypatch.setattr(context, "load", broken_load)

        for _ in range(4):
            work(scene)
            scene.world.later(minutes=16)

        escalation = scene.world.one("SELECT * FROM escalations")
        assert (escalation.reason, escalation.request_id) == ("cannot_resolve", request)
        conversation = scene.conversation(thread)
        assert (conversation.pending_turn_at, conversation.followup_at) == (None, None)

    def test_a_follow_up_that_was_due_waits_with_the_rest(
        self, scene: Scene, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The worker picks a conversation whose follow-up is due whatever the other mark
        says: left due, the follow-up would bring the crash back on every pass."""
        _, thread = scene.start_request()
        work(scene, call("schedule_followup", in_minutes=40), reply("I'll look again."))
        scene.world.later(minutes=41)
        monkeypatch.setattr(context, "load", broken_load)

        work(scene)
        again = work(scene)

        conversation = scene.conversation(thread)
        retry = scene.world.clock.now() + timedelta(minutes=1)
        assert again == 0
        assert (conversation.turn_attempts, conversation.followup_at) == (1, retry)
        assert scene.world.one("SELECT count(*) AS n FROM agent_runs").n == 1

    def test_a_turn_someone_else_is_running_is_left_alone(
        self, scene: Scene, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Their lease, their turn: this crash isn't counted against it."""
        from dawalink.services import conversations

        _, thread = scene.start_request()
        tx = scene.world.tx()
        assert conversations.take_lease(tx, thread, "another turn")
        scene.world.session.flush()
        # A crash before this turn even tries for the lease.
        monkeypatch.setattr(limits, "breaker_open", broken_load)

        result = turn_module.run_turn(scene.agent(), thread, runs_in="worker")

        conversation = scene.conversation(thread)
        assert (result.status, result.outcome) == (Status.UNAVAILABLE, "error")
        assert (conversation.turn_attempts, conversation.turn_owner) == (0, "another turn")

    def test_when_even_the_clean_up_fails_the_conversation_is_put_aside(
        self, scene: Scene, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Not tried again every 5 seconds for ever: after the longest wait, and logged."""
        _, thread = scene.start_request()
        monkeypatch.setattr(context, "load", broken_load)

        def cannot_count(*_: Any, **__: Any) -> None:
            raise RuntimeError("the counting is broken too")

        monkeypatch.setattr(turn_module, "_try_again_later", cannot_count)

        work(scene)

        conversation = scene.conversation(thread)
        assert conversation.pending_turn_at == scene.world.clock.now() + timedelta(minutes=15)
        assert conversation.turn_lease_until is None
        assert len(logged(caplog, "agent_turn_put_aside")) == 1


class TestARoutingServiceThatIsDown:
    """A#25, FX-18: one wait, then the straight-line estimate for a minute."""

    def test_the_agent_asks_it_once_and_uses_the_estimate(self, scene: Scene) -> None:
        scene.routing.fail = True
        scene.stock()

        first = scene.tool("find_options", product_ids=[scene.augmentin])
        second = scene.tool("find_options", product_ids=[scene.augmentin])

        assert scene.routing.calls == 1
        assert first["options"][0]["travel"]["source"] == "straight"
        assert second["options"][0]["travel"]["source"] == "straight"

    def test_it_is_asked_again_after_a_minute(self) -> None:
        down, other = FakeRouting(fail=True), FakeRouting()
        point = Point(Decimal("33.896"), Decimal("35.483"))
        wanted = travel.Wanted({"cell": point}, {uuid.uuid4(): point})
        clock = Stopwatch()

        travel.fetch(down, wanted, monotonic=clock)
        clock.now += 59
        paused = travel.fetch(down, wanted, monotonic=clock)
        others = travel.fetch(other, wanted, monotonic=clock)
        clock.now += 2
        down.fail = False
        back = travel.fetch(down, wanted, monotonic=clock)

        assert paused == []
        # The failure; nothing while paused; then by car and on foot once the minute is over.
        assert down.calls == 3
        assert len(others) == 2  # another service isn't paused by this one's failure
        assert len(back) == 2


class TestATurnThatRunsOutOfTime:
    """A#25, N-37, N-38: the breaker counts turns lost to the model, nothing else."""

    def slow_tool(self, stopwatch: Stopwatch, seconds: float) -> Any:
        def step(_: Prompt) -> Any:
            stopwatch.now += seconds  # the model answers; the tool then takes the time
            return call("search_catalog", query="augmentin")

        return step

    def test_it_falls_back_and_does_not_open_the_breaker(self, scene: Scene) -> None:
        stopwatch = Stopwatch()
        for _ in range(3):
            result = scene.turn(self.slow_tool(stopwatch, 61), monotonic=stopwatch)
            assert (result.status, result.outcome) == (Status.UNAVAILABLE, "fallback")
            assert scene.run(result).guardrails == [limits.TIME_LIMIT]

        someone_else = scene.turn(reply("Hello"))

        assert (someone_else.status, someone_else.text) == (Status.DONE, "Hello")

    def test_a_call_cut_short_by_what_was_left_is_not_the_models_failure(
        self, scene: Scene
    ) -> None:
        stopwatch = Stopwatch()

        def times_out(_: Prompt) -> Any:
            stopwatch.now += 10  # all that was left of the turn
            raise LLMUnavailable("APITimeoutError")

        result = scene.turn(self.slow_tool(stopwatch, 50), times_out, monotonic=stopwatch)

        assert result.outcome == "fallback"
        assert scene.run(result).guardrails == [limits.TIME_LIMIT]

    def test_a_model_that_timed_out_earlier_in_the_turn_is_still_to_blame(
        self, scene: Scene
    ) -> None:
        """One call times out, its retry answers, the next call times out on what is left:
        a provider that fails half its calls must still count toward the breaker."""
        stopwatch = Stopwatch()

        def hangs(_: Prompt) -> Any:
            stopwatch.now += 30
            raise LLMUnavailable("APITimeoutError")

        def hangs_on_the_rest(_: Prompt) -> Any:
            stopwatch.now += 29
            raise LLMUnavailable("APITimeoutError")

        result = scene.turn(
            hangs, self.slow_tool(stopwatch, 1), hangs_on_the_rest, monotonic=stopwatch
        )

        assert result.outcome == "fallback"
        assert scene.run(result).guardrails == []

    def test_a_model_that_hangs_still_opens_the_breaker(self, scene: Scene) -> None:
        """30 s, then the retry: the time runs out because the model doesn't answer."""
        stopwatch = Stopwatch()

        def hangs(_: Prompt) -> Any:
            stopwatch.now += 30
            raise LLMUnavailable("APITimeoutError")

        for _ in range(3):
            result = scene.turn(hangs, hangs, monotonic=stopwatch)
            assert scene.run(result).guardrails == []

        blocked = scene.turn(reply("Hello"))

        assert (blocked.status, blocked.run_id) == (Status.UNAVAILABLE, None)


class TestWhatAnUnsavedTurnStillWrites:
    def test_the_spending_is_on_the_run_after_each_model_call(self, scene: Scene) -> None:
        """A#21: a turn the worker's stop cuts off still counts toward the caps."""
        seen: list[Any] = []

        def second_call(_: Prompt) -> Any:
            seen.append(scene.world.one("SELECT llm_calls, tokens_in, outcome FROM agent_runs"))
            return reply("Found it.")

        result = scene.turn(call("search_catalog", query="augmentin"), second_call)

        (during,) = seen
        assert (during.llm_calls, during.tokens_in, during.outcome) == (1, 100, None)
        assert scene.run(result).llm_calls == 2

    def test_a_turn_that_fell_back_keeps_the_follow_up_it_scheduled(self, scene: Scene) -> None:
        """N-39: the follow-up is committed by its tool; its count must be kept too, or
        the retry could schedule more than four."""
        _, thread = scene.start_request()

        work(scene, call("schedule_followup", in_minutes=40), DOWN, DOWN, DOWN)

        conversation = scene.conversation(thread)
        assert conversation.followup_at is not None
        assert conversation.case_state.get("followups_used") == 1
