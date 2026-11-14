"""What a turn is given to read, and what it remembers (docs/07 §3.1, §6; N-32, N-33).

The block of facts is written field by field by code. These tests look at that block
for each kind of thing a conversation can hold.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from dawalink.agent import context, state
from dawalink.agent.llm import LLMRejected
from dawalink.agent.llm.scripted import reply
from dawalink.agent.state import CaseNotes, CaseState, FocusItem, Money
from dawalink.agent.tracing import Span, TurnTrace
from dawalink.agent.turn import Status
from dawalink.domain.numbers import CASE_STATE_MAX_BYTES
from dawalink.services import conversations, events
from dawalink.services.events import Decision
from tests.agent.conftest import Scene
from tests.conftest import logged
from tests.db.factories import TODAY


def block(scene: Scene, conversation: uuid.UUID | None = None) -> str:
    loaded = context.load(scene.world.tx(), conversation or scene.chat)
    assert loaded is not None
    return loaded.block


class TestTheFacts:
    def test_the_time_the_days_and_the_limits(self, scene: Scene) -> None:
        """N-49: the days are given with their dates, so the model never works one out."""
        scene.say("hello")

        text = block(scene)

        assert "Tue 20 Oct 2026, 10:00 (Beirut time)." in text
        assert "Request hours (08:00-20:00): open." in text
        assert "Tue 20 Oct = 2026-10-20 (today), Wed 21 Oct = 2026-10-21" in text
        assert text.count(" = 2026-") == 7
        assert "Location: shared for this conversation. Home area: Beirut." in text
        assert "reservations 0/5, requests 0/2, watches 0/5, early-release requests 0/5" in text

    def test_at_night_it_says_that_nothing_new_can_start(self, scene: Scene) -> None:
        scene.world.later(hours=12)
        scene.say("hello")

        assert "closed: no new watch or request now" in block(scene)

    def test_only_the_last_20_messages_are_read(self, scene: Scene) -> None:
        """N-32."""
        for number in range(1, 26):
            scene.say(f"message {number}")

        text = block(scene)

        assert "client: message 5\n" not in text
        assert "[6] client: message 6" in text
        assert "[25] client: message 25" in text

    @pytest.mark.rows_by_hand
    def test_system_cards_and_events_are_written_as_chosen_facts(self, scene: Scene) -> None:
        """INV-23: a card's data is never copied whole into the prompt."""
        order = scene.world.make.order(
            client_id=scene.client, pharmacy_id=scene.pharmacy, product_id=scene.augmentin
        )
        ref = scene.world.one("SELECT ref FROM orders WHERE id = :o", o=order).ref
        claim = scene.world.make.claim(client_id=scene.client, product_id=scene.concor)
        tx = scene.world.tx()
        events.post_card(
            tx,
            scene.chat,
            "reserved",
            order_ref=ref,
            product="AUGMENTIN 1G",
            pharmacy="Hamra Pharmacy",
            units=1,
            price_lbp=700_000,
            pickup_by="2026-10-20T18:00:00+00:00",
            pharmacy_address="12 Secret Lane",  # not a chosen fact: it must not appear
        )
        events.post_decision(tx, scene.chat, Decision.NOT_AVAILABLE, order_id=order, units=1)
        events.post_decision(tx, scene.chat, Decision.SYSTEM_CANCELLED, order_id=order)
        events.post_decision(tx, scene.chat, Decision.EARLY_RELEASE_UNFULFILLED, claim_id=claim)
        events.post_decision(
            tx,
            scene.chat,
            Decision.GROUP_ITEM_FAILED,
            failed_items=[{"listing_id": "box-1", "code": "NOT_ENOUGH_STOCK"}],
        )
        events.post_decision(tx, scene.chat, Decision.ITEMS_UNTICKED, items=["box-2"])
        chat = conversations.locked(tx, scene.chat)
        conversations.append(tx, chat, author="admin", kind="text", text="Call us on 01 345 678")

        text = block(scene)

        assert (
            f"system card: reserved: order_ref {ref}, product AUGMENTIN 1G, pharmacy Hamra "
            "Pharmacy, units 1, price 700,000 LBP (about $7.82), pickup_by Tue 21:00"
        ) in text
        assert "Secret Lane" not in text
        described = f"order {ref} (AUGMENTIN 1G x 1 at Hamra Pharmacy)"
        assert f"not_available: the pharmacy marked {described} not available for 1 unit(s)" in text
        assert f"system_cancelled: DawaLink cancelled {described}" in text
        assert "early_release_unfulfilled: no pharmacy released stock for CONCOR 5MG" in text
        assert "group_item_failed: a plan card couldn't be reserved, nothing was. box-1: " in text
        assert "items_unticked: the client left these items unticked: box-2" in text
        assert "DawaLink team: Call us on [phone]" in text
        assert "Something changed (see the newest events)" in text

    def test_a_card_shown_earlier_says_whether_it_can_still_be_tapped(self, scene: Scene) -> None:
        box = scene.stock()
        made = scene.tool("propose_reservation", listing_id=box, pickup_day=TODAY)
        tx = scene.world.tx()
        chat = conversations.locked(tx, scene.chat)
        conversations.append(
            tx, chat, author="agent", kind="text", text="Here.", cards=[made["proposal_id"]]
        )

        scene.say("and now?")

        fresh = block(scene)
        scene.world.later(hours=3)
        stale = block(scene)

        card = f'{made["proposal_id"]} "AUGMENTIN 1G at Hamra Pharmacy"'
        assert f"you: Here. (cards: {card} [open])" in fresh
        assert f"(cards: {card} [expired])" in stale


class TestTheCaseState:
    def test_with_nothing_new_there_is_nothing_to_load(self, scene: Scene) -> None:
        assert context.load(scene.world.tx(), scene.chat) is None

    def test_the_agents_notes_change_only_its_own_fields(self) -> None:
        """docs/07 §6.2."""
        before = CaseState(notes=["first"], escalated=True, open_proposal_ids=[uuid.uuid4()])
        notes = CaseNotes(
            language="arabizi",
            preference="walkable",
            budget=Money(amount=10, currency="USD"),
            pickup_day=date(2026, 10, 21),
            alternatives_ok=True,
            situation_notes=["no car", "free after 18:00"],
            items_in_focus=[FocusItem(product_id=uuid.uuid4(), qty=2, note="for my mother")],
            add_note="prefers the afternoon",
            remove_note_index=0,
        )

        after = state.apply_notes(before, notes, str.upper)

        assert (after.language, after.preference, after.alternatives_ok) == (
            "arabizi",
            "walkable",
            True,
        )
        assert after.budget == Money(amount=10, currency="USD")
        assert after.situation_notes == ["NO CAR", "FREE AFTER 18:00"]
        assert after.items_in_focus[0].note == "FOR MY MOTHER"
        assert after.notes == ["PREFERS THE AFTERNOON"]
        # What code owns is untouched by the model.
        assert (after.escalated, after.open_proposal_ids) == (True, before.open_proposal_ids)
        assert before.notes == ["first"]

    def test_a_pickup_day_that_has_passed_is_forgotten(self) -> None:
        kept = state.tidy(CaseState(pickup_day=date(2026, 10, 20)), date(2026, 10, 20))
        gone = state.tidy(CaseState(pickup_day=date(2026, 10, 20)), date(2026, 10, 21))

        assert (kept.pickup_day, gone.pickup_day) == (date(2026, 10, 20), None)

    def test_it_never_grows_past_its_limit(self) -> None:
        """N-33: what code remembers goes first, then the agent's notes."""
        big = CaseState(
            shown_listing_ids=[uuid.uuid4() for _ in range(400)],
            notes=["n" * 200] * 5,
            situation_notes=["s" * 80] * 3,
        )
        big.plans = {
            f"plan-{number}": state.PlanRef(
                pickup_day=date(2026, 10, 20),
                groups=[
                    state.PlanGroup(
                        pharmacy_id=uuid.uuid4(),
                        picks=[
                            state.PlanPick(
                                product_id=uuid.uuid4(),
                                listing_id=uuid.uuid4(),
                                qty=1,
                                price_lbp=1,
                                days_of_use=1,
                            )
                            for _ in range(20)
                        ],
                    )
                ],
            )
            for number in range(8)
        }

        tidy = state.tidy(big, date(2026, 10, 20))

        assert state.size(tidy) <= CASE_STATE_MAX_BYTES
        assert tidy.notes == ["n" * 200] * 5  # the agent's notes survived
        assert tidy.plans == {}

    def test_a_stored_state_that_can_not_be_read_starts_empty(self) -> None:
        assert state.load({"language": "klingon", "items_in_focus": "?"}) == CaseState()
        assert state.load(None) == CaseState()

    def test_the_model_is_not_shown_what_only_code_needs(self) -> None:
        shown = state.for_model(
            CaseState(language="english", shown_listing_ids=[uuid.uuid4()], followups_used=2)
        )

        assert shown == {"language": "english"}


class TestTheRestOfATurn:
    def test_a_rejected_key_or_an_empty_credit_is_a_failed_turn(self, scene: Scene) -> None:
        """A failure a retry can't fix isn't retried: the turn falls back at once."""
        result = scene.turn(LLMRejected("AuthenticationError (401)"), reply("never reached"))

        assert (result.status, result.outcome) == (Status.UNAVAILABLE, "fallback")
        assert scene.run(result).retries == 0
        assert scene.model.steps_left == 1

    def test_a_bug_inside_a_turn_closes_the_run_and_frees_the_conversation(
        self, scene: Scene, caplog: pytest.LogCaptureFixture
    ) -> None:
        def broken(_: Any) -> Any:
            raise RuntimeError("a bug")

        result = scene.turn(broken)

        assert (result.status, result.outcome) == (Status.UNAVAILABLE, "error")
        assert scene.run(result).outcome == "error"
        assert scene.conversation().turn_lease_until is None
        assert len(logged(caplog, "agent_turn_crashed")) == 1

    def test_an_alert_when_spending_passes_80_percent_of_the_month(
        self, scene: Scene, caplog: pytest.LogCaptureFixture
    ) -> None:
        """R-AL: said once, by the turn that crosses the line."""

        class Priced:
            name = "claude-haiku-5-5"

            def __init__(self, inner: Any) -> None:
                self.inner = inner

            def complete(self, prompt: Any, *, timeout_s: float) -> Any:
                return self.inner.complete(prompt, timeout_s=timeout_s)

        from dataclasses import replace

        from dawalink.agent.turn import run_turn

        scene.say("hello")
        for _ in range(2):
            agent = scene.agent(reply("Hi."), monthly_budget_usd=Decimal("0.000015"))
            run_turn(replace(agent, model=Priced(agent.model)), scene.chat, runs_in="chat")

        # One turn costs $0.00002: more than the tiny budget, so the first turn crosses 80%.
        assert len(logged(caplog, "llm_spend_above_80_percent")) == 1


class TestSendingATraceToLangfuse:
    """The real client is replaced by one that records what it is given (no network)."""

    def test_a_trace_becomes_one_observation_per_step_with_masked_text(self) -> None:
        from dawalink.agent import tracing_langfuse
        from dawalink.agent.tracing_langfuse import LangfuseTracer, mask

        recorded: list[dict[str, Any]] = []

        class Observation:
            def __init__(self, **given: Any) -> None:
                recorded.append(given)

            def start_observation(self, **given: Any) -> "Observation":
                return Observation(**given)

            def update(self, **given: Any) -> None:
                recorded.append({"updated": given})

            def end(self) -> None:
                recorded.append({"ended": True})

        class Client:
            def start_observation(self, **given: Any) -> Observation:
                return Observation(**given)

        tracer = LangfuseTracer.__new__(LangfuseTracer)
        tracer._client = Client()  # type: ignore[assignment]
        trace = TurnTrace("a" * 32, {"mode": "assistant"})
        trace.spans = [
            Span("llm", "generation", 0.0, 1.5, "in", "out", {"model": "m", "input_tokens": 7}),
            Span("search_catalog", "tool", 1.5, 1.6, {"query": "x"}, {"ok": True}, {"ok": True}),
        ]
        trace.output = {"text": "Hello"}

        tracer.send(trace)

        root, generation, _, tool, _, updated, _ = recorded
        assert root["name"] == "agent_turn"
        assert root["trace_context"] == {"trace_id": "a" * 32}
        assert (generation["as_type"], generation["model"]) == ("generation", "m")
        assert generation["usage_details"] == {"input": 7, "output": 0}
        assert generation["metadata"]["duration_ms"] == 1500
        assert (tool["as_type"], tool["name"]) == ("tool", "search_catalog")
        assert updated == {"updated": {"output": {"text": "Hello"}}}
        # The masking hook removes personal-detail patterns from anything about to leave.
        assert mask(data={"note": ["call 70 123 456", {"mail": "a@b.example"}], "n": 3}) == {
            "note": ["call [phone]", {"mail": "[email]"}],
            "n": 3,
        }
        assert tracing_langfuse.LangfuseTracer.new_trace_id(tracer)
