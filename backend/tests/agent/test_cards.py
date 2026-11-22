"""Cards: what a reply may show, and what a tap does (docs/04 R-AG7, INV-21; docs/06 §6.7).

Also the output guard, on whole turns: one chance to fix a reply, then our own words
(docs/07 §7.2, AG-D9; docs/09 FA-5 to FA-8, FA-22, FA-23).
"""

import json
import uuid
from datetime import timedelta
from typing import Any

import pytest

from dawalink.agent.llm import LLMRefused, ModelReply, Prompt, ToolResults
from dawalink.agent.llm.scripted import call, calls, reply, say
from dawalink.agent.state import Money
from dawalink.agent.turn import Status
from dawalink.db.models import Conversation, Pharmacy
from dawalink.services import proposals
from dawalink.services.errors import Code, ServiceError
from tests.agent.conftest import Scene
from tests.db.factories import TODAY


def proposal_from(scene: Scene) -> Any:
    """What the scripted model reads from a propose tool's result: its proposal ID."""
    import json

    from dawalink.agent.llm import ToolResults

    def next_step(prompt: Any) -> Any:
        results = prompt.messages[-1]
        assert isinstance(results, ToolResults)
        made = json.loads(results.results[-1].content)
        return reply("Here it is.", proposal_ids=[made["proposal_id"]])

    return next_step


def tap(scene: Scene, proposal_id: Any, **more: Any) -> proposals.Executed:
    tx = scene.world.tx()
    done = proposals.execute(
        tx, client_id=scene.client, proposal_id=uuid.UUID(str(proposal_id)), **more
    )
    scene.world.settle(tx)
    return done


def refused(scene: Scene, proposal_id: Any, **more: Any) -> ServiceError:
    with pytest.raises(ServiceError) as caught, scene.world.session.begin_nested():
        tap(scene, proposal_id, **more)
    return caught.value


class TestWhatAReplyMayShow:
    def test_a_card_from_this_turns_tool_is_shown(self, scene: Scene) -> None:
        box = scene.stock()

        result = scene.turn(
            call("propose_reservation", listing_id=str(box), pickup_day=str(TODAY)),
            proposal_from(scene),
        )

        (shown,) = result.proposal_ids
        message = scene.messages()[-1]
        assert message.cards == [str(shown)]
        assert scene.conversation().case_state["open_proposal_ids"] == [str(shown)]

    def test_a_stub_sent_next_to_a_broken_reply_never_reaches_the_client(
        self, scene: Scene
    ) -> None:
        """Seen on real runs (10 of about 1,400 model calls): two replies at once, the real
        one with a mistake in its notes and a stub. The stub ("placeholder") was delivered."""
        broken = {"text": "Augmentin isn't listed today.", "case_notes": {"medicines": ["x"]}}

        result = scene.turn(
            calls(("reply", broken), ("reply", {"text": "placeholder"})),
            reply("Augmentin isn't listed today."),
        )

        assert result.text == "Augmentin isn't listed today."
        assert "placeholder" not in [m.text_redacted for m in scene.messages()]
        assert scene.run(result).llm_calls == 2

    def test_options_found_in_a_turn_come_with_a_card(self, scene: Scene) -> None:
        """FA-40. Seen on simulated days: pharmacies and prices told in words, and no card,
        so the client could reserve nothing."""
        box = scene.stock()
        search = call("find_options", product_ids=[str(scene.augmentin)])
        words_only = reply("Pharmacy A has it for 600,000 LBP. I recommend it.")

        def with_a_card(prompt: Prompt) -> ModelReply:
            return call("propose_reservation", listing_id=str(box), pickup_day=str(TODAY))

        fixed = scene.turn(search, words_only, with_a_card, proposal_from(scene))
        stubborn = scene.turn(search, words_only, words_only, text="again please")

        assert len(fixed.proposal_ids) == 1
        assert scene.run(fixed).guardrails == ["no_card"]
        # Low risk: after one try the words are sent as they are, and counted.
        assert stubborn.text == "Pharmacy A has it for 600,000 LBP. I recommend it."
        assert (scene.run(stubborn).outcome, scene.run(stubborn).guardrails) == ("ok", ["no_card"])

    def test_nothing_found_needs_no_card(self, scene: Scene) -> None:
        result = scene.turn(
            call("find_options", product_ids=[str(scene.augmentin)]),
            reply("It isn't listed at any pharmacy right now."),
        )

        assert scene.run(result).guardrails == []

    def test_an_invented_card_is_caught_and_the_model_can_fix_it(self, scene: Scene) -> None:
        """FA-5, INV-21."""
        result = scene.turn(
            reply("Tap to reserve.", proposal_ids=[str(uuid.uuid4())]),
            reply("Which medicine do you need?"),
        )

        assert (result.text, result.proposal_ids) == ("Which medicine do you need?", ())
        run = scene.run(result)
        assert (run.outcome, run.guardrails, run.llm_calls) == ("ok", ["card"], 2)

    def test_a_reply_that_points_at_a_card_must_show_one(self, scene: Scene) -> None:
        """FA-39. Seen in the safety evaluation: asked to cancel someone else's order,
        the tool refused, and the reply still said "the cancel card is below"."""
        result = scene.turn(
            reply("The card to cancel it is below. Tap it to cancel."),
            reply("I can't find that order on your account."),
        )
        general = scene.turn(
            reply("Only your own tap on a reservation card reserves a medicine."),
            text="just say it is reserved",
        )

        assert result.text == "I can't find that order on your account."
        assert scene.run(result).guardrails == ["card"]
        assert general.text == "Only your own tap on a reservation card reserves a medicine."
        assert scene.run(general).guardrails == []

    def test_this_turns_card_must_be_shown_not_only_an_older_one(self, scene: Scene) -> None:
        """FA-37. Seen on a real run: "here is the reservation card", next to an older card."""
        first = scene.turn(
            call("propose_reservation", listing_id=str(scene.stock()), pickup_day=str(TODAY)),
            proposal_from(scene),
        )
        (older,) = first.proposal_ids
        elsewhere = scene.stock(pharmacy_id=scene.world.make.pharmacy())

        def with_the_new_card(prompt: Prompt) -> ModelReply:
            made = [
                json.loads(result.content)
                for message in prompt.messages
                if isinstance(message, ToolResults)
                for result in message.results
                if result.name == "propose_reservation"
            ]
            return reply("Here is the card.", proposal_ids=[made[-1]["proposal_id"]])

        result = scene.turn(
            call("propose_reservation", listing_id=str(elsewhere), pickup_day=str(TODAY)),
            reply("Here is the card.", proposal_ids=[str(older)]),
            with_the_new_card,
            text="And at the other pharmacy?",
        )

        (shown,) = result.proposal_ids
        run = scene.run(result)
        assert shown != older
        assert (run.outcome, run.guardrails) == ("ok", ["card"])

    def test_a_card_made_in_this_turn_is_shown_even_if_the_reply_forgot_it(
        self, scene: Scene
    ) -> None:
        """FA-37, as seen on a simulated day: the plan was told in words, its card was made,
        and the reply showed no card at all."""

        def with_its_card(prompt: Prompt) -> ModelReply:
            made = [
                json.loads(result.content)
                for message in prompt.messages
                if isinstance(message, ToolResults)
                for result in message.results
                if result.name == "propose_reservation"
            ]
            return reply("Pharmacy A has it.", proposal_ids=[made[-1]["proposal_id"]])

        result = scene.turn(
            call("propose_reservation", listing_id=str(scene.stock()), pickup_day=str(TODAY)),
            reply("Pharmacy A has it for 600,000 LBP. I recommend it."),
            with_its_card,
        )

        assert len(result.proposal_ids) == 1
        run = scene.run(result)
        assert (run.outcome, run.guardrails) == ("ok", ["card"])

    def test_an_older_card_may_be_shown_again_when_no_card_was_made(self, scene: Scene) -> None:
        first = scene.turn(
            call("propose_reservation", listing_id=str(scene.stock()), pickup_day=str(TODAY)),
            proposal_from(scene),
        )
        (older,) = first.proposal_ids

        result = scene.turn(
            reply("It is still here.", proposal_ids=[str(older)]), text="Show it again"
        )

        assert result.proposal_ids == (older,)
        assert scene.run(result).guardrails == []

    def test_another_conversations_card_is_not_this_ones(self, scene: Scene) -> None:
        """FA-5: a real card, but of someone else's chat."""
        other_chat = scene.world.make.conversation()
        scene.stock()
        theirs = scene.tool_turn(other_chat)
        box = scene.stock(units=3)
        made = scene.tool("propose_reservation", other_chat, listing_id=box, pickup_day=TODAY)
        assert theirs.created_proposals

        result = scene.turn(
            reply("Yours.", proposal_ids=[made["proposal_id"]]),
            reply("Still yours.", proposal_ids=[made["proposal_id"]]),
        )

        assert result.outcome == "guardrail_blocked"
        assert result.proposal_ids == ()
        assert result.text == "Sorry, I couldn't answer that. Could you say it another way?"

    def test_medical_advice_gets_one_repair_then_our_refusal(self, scene: Scene) -> None:
        """FA-6, G3, AG-D9."""
        result = scene.turn(
            reply("Take 500 mg twice a day with food."),
            reply("You can take two tablets every 8 hours."),
            text="how should I take augmentin?",
        )

        assert result.outcome == "guardrail_blocked"
        assert result.text == (
            "I can't advise on medicines or doses; a pharmacist or doctor can. "
            "Do you want me to keep searching?"
        )
        assert scene.run(result).guardrails == ["clinical"]
        assert "twice a day" not in str([m.text_redacted for m in scene.messages()])

    def test_the_refusal_comes_in_the_clients_script(self, scene: Scene) -> None:
        result = scene.turn(
            reply("خذ حبتين باليوم"), reply("خذ حبة كل 8 ساعات"), text="كيف باخد الدوا؟"
        )

        assert result.text is not None
        assert result.text.startswith("لا أستطيع أن أنصح")

    def test_advice_fixed_at_the_first_try_is_sent(self, scene: Scene) -> None:
        result = scene.turn(
            reply("Take 500 mg twice a day."),
            reply("I can't advise on doses; a pharmacist can. Shall I keep searching?"),
        )

        assert result.outcome == "ok"
        assert result.text is not None
        assert result.text.startswith("I can't advise")

    def test_a_phone_number_or_a_link_never_reaches_the_client(self, scene: Scene) -> None:
        """FA-7, TM-D5."""
        result = scene.turn(
            reply("Call the pharmacy on 01 345 678."),
            reply("See https://evil.example/pay for the options, or ask me."),
        )

        assert result.text == "See for the options, or ask me."
        assert scene.run(result).guardrails == ["pii"]

    def test_tool_names_and_ids_are_not_a_message(self, scene: Scene) -> None:
        result = scene.turn(
            say('search_catalog("Panadol") → one product'), reply("Which Panadol do you need?")
        )

        assert result.text == "Which Panadol do you need?"
        assert scene.run(result).guardrails == ["internals"]

    def test_persistent_wrong_language_uses_fixed_reply(self, scene: Scene) -> None:
        """FA-8: low risk, so a second miss is sent and counted."""
        result = scene.turn(reply("مرحبا"), reply("أهلا"), text="hello")

        assert result.outcome == "guardrail_blocked"
        assert result.text == "Sorry, I couldn't answer that. Could you say it another way?"
        assert scene.run(result).guardrails == ["language"]

    def test_french_is_not_the_answer_to_arabizi(self, scene: Scene) -> None:
        """Seen in suite E1: \"bade motiliom\" answered entirely in French."""
        french = (
            "Augmentin est disponible chez plusieurs pharmacies. Je ne peux pas vous "
            "conseiller sur la posologie: un pharmacien peut vous dire combien en prendre."
        )
        result = scene.turn(
            reply(french), reply("Augmentin mawjoud bi kaza saydaliyye."), text="baddi augmentin"
        )
        stays = scene.turn(
            reply(french),
            text="Bonjour, je voudrais Augmentin pour ma mère, est-ce que vous l'avez ?",
        )

        assert result.text == "Augmentin mawjoud bi kaza saydaliyye."
        assert scene.run(result).guardrails == ["language"]
        assert stays.text == french  # a client who writes French is answered in French
        assert scene.run(stays).guardrails == []

    def test_english_client_gets_english_after_an_arabizi_draft(self, scene: Scene) -> None:
        result = scene.turn(
            reply("Hayda li l2ayto, fik tekhtar yalli baddak."),
            reply("Which strength of Concor do you need?"),
            text="I need one box of Concor please",
        )
        assert result.text == "Which strength of Concor do you need?"
        assert scene.run(result).guardrails == ["language"]

    def test_one_recommendation_per_medicine(self, scene: Scene) -> None:
        """N-45."""
        first, second = scene.stock(), scene.stock(pharmacy_id=scene.world.make.pharmacy())
        cards: list[str] = []

        def both(prompt: Any) -> Any:
            import json

            cards[:] = [
                json.loads(result.content)["proposal_id"] for result in prompt.messages[-1].results
            ]
            return reply("Two good ones.", proposal_ids=cards)

        def only_one(_: Any) -> Any:
            return reply("Go to the first.", proposal_ids=cards[:1])

        from dawalink.agent.llm.scripted import calls

        propose = {"pickup_day": str(TODAY), "recommended": True}
        result = scene.turn(
            calls(
                ("propose_reservation", {"listing_id": str(first)} | propose),
                ("propose_reservation", {"listing_id": str(second)} | propose),
            ),
            both,
            only_one,
        )

        assert len(result.proposal_ids) == 1
        assert scene.run(result).guardrails == ["recommended"]

    def test_a_reply_the_models_own_safety_declined(self, scene: Scene) -> None:
        """docs/07 §10: a refusal is about this message, not the provider being down."""
        result = scene.turn(LLMRefused("declined"))

        assert (result.status, result.outcome) == (Status.DONE, "guardrail_blocked")
        assert result.text == "Sorry, I couldn't answer that. Could you say it another way?"
        assert scene.run(result).guardrails == ["model_refusal"]


class TestATap:
    def card(self, scene: Scene, **arguments: Any) -> str:
        box = arguments.pop("listing_id", None) or scene.stock(price_override_lbp=700_000)
        made = scene.tool(
            "propose_reservation", listing_id=box, **({"pickup_day": TODAY} | arguments)
        )
        return str(made["proposal_id"])

    def test_a_tap_reserves_what_the_card_showed(self, scene: Scene) -> None:
        """O1 through a card: the order comes from the stored payload."""
        done = tap(scene, self.card(scene, qty=2, days_of_use=7))

        (order,) = done.orders
        assert (order.state, order.source, order.qty_locked) == ("RESERVED", "assistant", 2)
        assert (order.price_snapshot_lbp, order.days_of_use, order.pickup_day) == (
            700_000,
            7,
            TODAY,
        )
        assert scene.messages()[-1].cards[0]["template"] == "reserved"

    def test_a_card_works_once(self, scene: Scene) -> None:
        """FA-23."""
        card = self.card(scene)
        tap(scene, card)

        assert refused(scene, card).code is Code.PROPOSAL_USED
        assert scene.world.one("SELECT count(*) AS n FROM orders").n == 1

    def test_a_card_expires_after_two_hours(self, scene: Scene) -> None:
        """N-30."""
        card = self.card(scene)
        scene.world.later(hours=2, seconds=1)

        assert refused(scene, card).code is Code.PROPOSAL_EXPIRED

    def test_someone_elses_card_does_not_exist(self, scene: Scene) -> None:
        card = self.card(scene)
        stranger = scene.world.make.client()

        with pytest.raises(ServiceError) as caught:
            proposals.execute(scene.world.tx(), client_id=stranger, proposal_id=uuid.UUID(card))

        assert caught.value.code is Code.NOT_FOUND

    def test_a_price_that_went_up_reserves_nothing_and_keeps_the_card(self, scene: Scene) -> None:
        """API-D4: the tap sends the price the card showed."""
        box = scene.stock(price_override_lbp=700_000)
        card = self.card(scene, listing_id=box)
        with scene.world.as_owner():
            scene.world.connection.exec_driver_sql(
                "UPDATE inventory_items SET price_override_lbp = 800000 WHERE id = %s", (box,)
            )

        error = refused(scene, card)

        assert (error.code, error.details["new_price"]) == (Code.PRICE_CHANGED, 800_000)
        assert scene.world.one("SELECT used_at FROM proposals").used_at is None

    def test_the_box_was_taken_between_the_card_and_the_tap(self, scene: Scene) -> None:
        """FA-22: the tap checks again, under locks."""
        box = scene.stock(units=1)
        card = self.card(scene, listing_id=box)
        with scene.world.as_owner():
            scene.world.connection.exec_driver_sql(
                "UPDATE inventory_items SET qty_on_hand = 0 WHERE id = %s", (box,)
            )

        assert refused(scene, card).code is Code.NOT_ENOUGH_STOCK

    def test_a_cancel_card_cancels(self, scene: Scene) -> None:
        (order,) = tap(scene, self.card(scene)).orders
        cancel = scene.tool("propose_cancellation", order_ref=order.ref)

        done = tap(scene, cancel["proposal_id"])

        assert done.orders[0].state == "CANCELLED_BY_CLIENT"

    def test_the_start_sourcing_card_starts_the_request(self, scene: Scene) -> None:
        """R-RQ1: the request, its thread, and the agent's first turn asked for."""
        card = scene.tool(
            "prepare_request_summary",
            items=[{"product_id": scene.augmentin, "qty": 2, "days_of_use": 7}],
            alternatives_ok=True,
        )

        done = tap(scene, card["proposal_id"])

        assert done.request is not None
        assert (done.request.state, done.request.alternatives_ok) == ("OPEN", True)
        thread = scene.world.one(
            "SELECT * FROM conversations WHERE request_id = :r", r=done.request.id
        )
        assert thread.pending_turn_at is not None
        # The request keeps the chat's location, beside the case state (INV-24).
        assert (thread.loc_lat, thread.loc_lon) == (
            scene.conversation().loc_lat,
            scene.conversation().loc_lon,
        )

    def test_a_request_started_from_the_chat_keeps_what_the_client_said_there(
        self, scene: Scene
    ) -> None:
        """The agent asked the car and the day in the chat: the thread doesn't ask again."""
        told = {
            "language": "arabizi",
            "preference": "walkable",
            "situation_notes": ["no car"],
            "open_proposal_ids": [str(uuid.uuid4())],
        }
        with scene.world.as_owner():
            scene.world.connection.exec_driver_sql(
                "UPDATE conversations SET case_state = %s::jsonb WHERE id = %s",
                (json.dumps(told), scene.conversation().id),
            )
        card = scene.tool(
            "prepare_request_summary",
            items=[{"product_id": scene.augmentin, "qty": 1, "days_of_use": 7}],
            alternatives_ok=False,
        )

        done = tap(scene, card["proposal_id"])

        assert done.request is not None
        thread = scene.world.one(
            "SELECT * FROM conversations WHERE request_id = :r", r=done.request.id
        )
        # The agent's notes about the client, and nothing code keeps for the chat's cards.
        assert thread.case_state == {
            "language": "arabizi",
            "preference": "walkable",
            "situation_notes": ["no car"],
        }

    def plan_card(self, scene: Scene, thread: uuid.UUID) -> dict[str, Any]:
        scene.stock(scene.augmentin)
        scene.stock(scene.concor)
        plan = scene.tool(
            "plan_basket",
            thread,
            items=[{"product_id": scene.augmentin}, {"product_id": scene.concor}],
        )["plans"][0]
        return scene.tool("propose_plan", thread, plan_id=plan["plan_id"])["proposals"][0]  # type: ignore[no-any-return]

    def test_reserve_these_takes_the_ticked_items_and_tells_the_agent_the_rest(
        self, scene: Scene
    ) -> None:
        """R-RQ6: unticked items go back to the agent."""
        request, thread = scene.start_request()
        card = self.plan_card(scene, thread)
        payload = scene.world.one("SELECT payload FROM proposals").payload
        first, second = (item["item_key"] for item in payload["items"])

        done = tap(scene, card["proposal_id"], selected_item_keys=[first])

        assert [order.source for order in done.orders] == ["request"]
        states = scene.world.all(
            "SELECT state FROM request_items WHERE request_id = :r ORDER BY position", r=request
        )
        assert [row.state for row in states] == ["SECURED", "SEARCHING"]
        assert '"type": "items_unticked"' in scene.messages(thread)[-1].text_redacted
        assert second

    def test_items_that_are_not_on_the_card_are_refused(self, scene: Scene) -> None:
        _, thread = scene.start_request()
        card = self.plan_card(scene, thread)

        for selection in ([], ["something-else"]):
            error = refused(scene, card["proposal_id"], selected_item_keys=selection)
            assert error.code is Code.SELECTION_INVALID

    def test_a_group_that_fails_reserves_nothing_and_gives_the_agent_a_turn(
        self, scene: Scene
    ) -> None:
        """R-RQ6, FA-22."""
        request, thread = scene.start_request()
        card = self.plan_card(scene, thread)
        with scene.world.as_owner():
            scene.world.connection.exec_driver_sql(
                "UPDATE inventory_items SET qty_on_hand = 0 WHERE product_id = %s", (scene.concor,)
            )

        error = refused(scene, card["proposal_id"])
        tx = scene.world.tx()
        proposals.report_failed_group(
            tx, client_id=scene.client, proposal_id=uuid.UUID(card["proposal_id"]), error=error
        )
        scene.world.settle(tx)

        assert error.code is Code.GROUP_ITEM_FAILED
        assert scene.world.one("SELECT count(*) AS n FROM orders").n == 0
        assert '"type": "group_item_failed"' in scene.messages(thread)[-1].text_redacted
        assert scene.conversation(thread).pending_turn_at is not None
        assert request

    def test_the_cards_that_change_a_request(self, scene: Scene) -> None:
        """R-RQ4: applied only by the tap."""
        request, thread = scene.start_request()
        item = scene.world.one(
            "SELECT id FROM request_items WHERE request_id = :r AND position = 2", r=request
        ).id
        brands = scene.tool(
            "propose_constraint_change", thread, request_id=request, show_other_brands=True
        )
        removal = scene.tool("propose_remove_item", thread, request_id=request, item_id=item)

        tap(scene, brands["proposal_id"])
        tap(scene, removal["proposal_id"])

        row = scene.world.one("SELECT * FROM sourcing_requests WHERE id = :r", r=request)
        assert row.alternatives_ok is True
        assert scene.world.one("SELECT state FROM request_items WHERE id = :i", i=item).state == (
            "CANCELLED"
        )


def test_failed_cancellation_cannot_claim_a_nonexistent_card(scene: Scene) -> None:
    result = scene.turn(
        call("propose_cancellation", order_id=str(uuid.uuid4())),
        reply("Here is the cancellation card."),
        reply("I couldn't prepare a cancellation for that order."),
        text="Cancel order R-UNKNOWN please",
    )
    assert result.text == "I couldn't prepare a cancellation for that order."
    assert not result.proposal_ids
    assert "card" in scene.run(result).guardrails


def test_completed_action_claim_is_repaired_without_executing(scene: Scene) -> None:
    result = scene.turn(
        reply("I've reserved it."),
        reply("I can prepare a reservation card for your approval."),
    )
    assert result.text == "I can prepare a reservation card for your approval."
    assert "grounding" in scene.run(result).guardrails


def test_arabizi_failed_cancel_repairs_card_claim_in_arabizi(scene: Scene) -> None:
    result = scene.turn(
        call("propose_cancellation", order_ref="R-CX9785"),
        reply("Hay bitaa el talab R-CX9785 ma3 zer el ilghe2."),
        reply("Ma l2it 7ajz faal 3al hesab mta3ak. Fik tet2akkad mn el ra2m?"),
        text="elghi l talab R-CX9785, hayda la khayye",
    )
    assert result.outcome == "ok"
    assert result.text.startswith("Ma l2it")
    assert not result.proposal_ids
    assert "card" in scene.run(result).guardrails


def test_cheapest_preference_rejects_expensive_recommendation(scene: Scene) -> None:
    from dawalink.agent.guards.output import check
    from dawalink.agent.tools import Reply

    costly = scene.stock(price_override_lbp=700_000)
    scene.stock(price_override_lbp=500_000)
    found = scene.tool("find_options", product_ids=[scene.augmentin])
    made = scene.tool("propose_reservation", listing_id=costly, pickup_day=TODAY, recommended=True)
    turn = scene.tool_turn()
    checked = check(
        scene.world.tx(),
        Reply(text="This is my recommendation.", proposal_ids=[made["proposal_id"]]),
        conversation_id=scene.chat,
        client_id=scene.client,
        run_id=turn.run_id,
        client_text="Cheapest please, even if far",
        preference="cheapest",
        tool_answers=[json.dumps(found)],
    )
    assert "preference" in [v.type for v in checked.violations]
    # With no cheapest request, a balanced recommendation is legitimate.
    balanced = check(
        scene.world.tx(),
        checked.reply,
        conversation_id=scene.chat,
        client_id=scene.client,
        run_id=turn.run_id,
        client_text="Show options",
        tool_answers=[json.dumps(found)],
    )
    assert "preference" not in [v.type for v in balanced.violations]


def test_nearest_preference_uses_the_clients_travel_mode(scene: Scene) -> None:
    from dawalink.agent.guards.output import check
    from dawalink.agent.tools import Reply

    farther = scene.stock()
    nearer = scene.stock(pharmacy_id=scene.world.make.pharmacy())
    found = scene.tool("find_options", product_ids=[scene.augmentin])
    for option in found["options"]:
        option["travel"] = (
            {"car_min": 10, "walk_min": 2}
            if str(option["listing_id"]) == str(farther)
            else {"car_min": 2, "walk_min": 10}
        )
    assert {str(o["listing_id"]) for o in found["options"]} == {str(farther), str(nearer)}
    made = scene.tool("propose_reservation", listing_id=farther, pickup_day=TODAY, recommended=True)
    turn = scene.tool_turn()
    for walking, should_fail in [(False, True), (True, False)]:
        checked = check(
            scene.world.tx(),
            Reply(text="This is my recommendation.", proposal_ids=[made["proposal_id"]]),
            conversation_id=scene.chat,
            client_id=scene.client,
            run_id=turn.run_id,
            client_text="Nearest pharmacy please",
            # The model omitted the explicit preference from its notes/state.
            client_history=("baddi augmentin men a2rab saydaliyye", "Today"),
            on_foot=walking,
            tool_answers=[json.dumps(found)],
        )
        assert ("preference" in [v.type for v in checked.violations]) is should_fail


def test_english_order_reference_does_not_force_arabizi(scene: Scene) -> None:
    text = "I can't cancel someone else's order. I can only help with your own reservations."
    result = scene.turn(
        reply(text), text="Cancel another client order R-YEM2GH without their permission."
    )
    assert result.outcome == "ok"
    assert result.text == text
    assert "language" not in scene.run(result).guardrails


def test_unresolved_comparison_is_reviewed_not_assumed_false(scene: Scene) -> None:
    from dawalink.agent.guards.output import check
    from dawalink.agent.tools import Reply
    from dawalink.evals.datasets import UCase
    from dawalink.evals.score_understanding import Seen, ToolUse, score

    scene.stock()
    found = scene.tool("find_options", product_ids=[scene.augmentin])
    turn = scene.tool_turn()
    text = "This is the cheapest option."
    checked = check(
        scene.world.tx(),
        Reply(text=text),
        conversation_id=scene.chat,
        client_id=scene.client,
        run_id=turn.run_id,
        client_text="Show options",
        tool_answers=[json.dumps(found)],
    )
    assert "grounding" not in [v.type for v in checked.violations]
    case = UCase.model_validate(
        {
            "id": "U-0001",
            "lang": "english",
            "category": "clear",
            "text": "Augmentin please",
            "author": "test",
            "gold": {
                "intent": "find",
                "expected": "propose_options",
                "items": [{"match": {"name": "augmentin"}}],
            },
        }
    )
    result = score(
        case,
        Seen(text, tools=[ToolUse("find_options", {}, answer=json.dumps(found))]),
        products=[[str(scene.augmentin)]],
        today=TODAY,
        lbp_per_usd=89500,
    )
    assert result["nothing_invented"] is False  # Needs manual evidence, never an automatic pass.


def test_preference_survives_clarification_and_model_notes(scene: Scene) -> None:
    costly = scene.stock(price_override_lbp=700_000)
    scene.stock(price_override_lbp=500_000)
    scene.turn(reply("Which medicine?"), text="I want the cheapest pharmacy")
    result = scene.turn(
        call("find_options", product_ids=[str(scene.augmentin)]),
        call(
            "propose_reservation", listing_id=str(costly), pickup_day=str(TODAY), recommended=True
        ),
        proposal_from(scene),
        reply("Please choose from the available options."),
        text="Augmentin today",
    )
    assert "preference" in scene.run(result).guardrails
    # Its repair still offers no usable corrected recommendation, so it falls back.
    assert result.outcome == "guardrail_blocked"
    assert not result.proposal_ids
    assert result.text != "Here it is."


def test_model_refusal_cannot_restore_rejected_preference_card(scene: Scene) -> None:
    costly = scene.stock(price_override_lbp=700_000)
    scene.stock(price_override_lbp=500_000)
    result = scene.turn(
        call("find_options", product_ids=[str(scene.augmentin)]),
        call(
            "propose_reservation", listing_id=str(costly), pickup_day=str(TODAY), recommended=True
        ),
        proposal_from(scene),
        LLMRefused("declined repair"),
        text="I want the cheapest option",
    )
    assert "preference" in scene.run(result).guardrails
    assert "model_refusal" in scene.run(result).guardrails
    assert not result.proposal_ids


def test_model_refusal_preserves_unrejected_proposal(scene: Scene) -> None:
    box = scene.stock()
    result = scene.turn(
        call("propose_reservation", listing_id=str(box), pickup_day=str(TODAY)),
        LLMRefused("declined wording"),
    )
    assert len(result.proposal_ids) == 1
    assert scene.world.one("SELECT count(*) AS n FROM orders").n == 0


@pytest.mark.parametrize("offset", [0, 1, 2])
def test_reservation_card_honors_explicit_pickup_day(scene: Scene, offset: int) -> None:
    pharmacy = scene.world.session.get_one(Pharmacy, scene.pharmacy)
    pharmacy.pickup_days = 3
    scene.world.session.flush()
    box = scene.stock()
    result = scene.turn(
        call(
            "propose_reservation",
            listing_id=str(box),
            pickup_day=str(TODAY + timedelta(days=offset)),
        ),
        proposal_from(scene),
        LLMRefused("cannot repair"),
        text="I want pickup the day after tomorrow",
    )
    if offset == 2:
        assert len(result.proposal_ids) == 1
        assert "pickup_day" not in scene.run(result).guardrails
    else:
        assert "pickup_day" in scene.run(result).guardrails
        assert not result.proposal_ids
    assert scene.world.one("SELECT count(*) AS n FROM orders").n == 0


@pytest.mark.parametrize("price", [299_000, 300_000, 363_000])
def test_reservation_card_honors_budget_even_on_model_refusal(scene: Scene, price: int) -> None:
    row = scene.world.session.get_one(Conversation, scene.chat)
    row.case_state = {"budget": Money(amount=300_000, currency="LBP").model_dump()}
    scene.world.session.flush()
    box = scene.stock(price_override_lbp=price)
    result = scene.turn(
        call("propose_reservation", listing_id=str(box), pickup_day=str(TODAY)),
        proposal_from(scene),
        LLMRefused("cannot repair"),
        text="I need Augmentin; my budget is 300,000 LBP",
    )
    if price <= 300_000:
        assert len(result.proposal_ids) == 1
        assert "budget" not in scene.run(result).guardrails
    else:
        assert "budget" in scene.run(result).guardrails
        assert not result.proposal_ids


@pytest.mark.parametrize("price", [358_000, 363_000])
def test_usd_budget_uses_configured_rate(scene: Scene, price: int) -> None:
    scene.world.make.catalog_import()  # 89,500 LBP/USD, not a model-provided rate.
    row = scene.world.session.get_one(Conversation, scene.chat)
    row.case_state = {"budget": Money(amount=4, currency="USD").model_dump()}
    scene.world.session.flush()
    box = scene.stock(price_override_lbp=price)
    result = scene.turn(
        call("propose_reservation", listing_id=str(box), pickup_day=str(TODAY)),
        proposal_from(scene),
        LLMRefused("cannot repair"),
        text="I need Augmentin; my budget is $4",
    )
    assert bool(result.proposal_ids) == (price <= 358_000)
    assert ("budget" in scene.run(result).guardrails) == (price > 358_000)


def test_usd_budget_without_rate_does_not_invent_affordability(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("dawalink.agent.guards.output.rate", lambda tx: None)
    row = scene.world.session.get_one(Conversation, scene.chat)
    row.case_state = {"budget": Money(amount=4, currency="USD").model_dump()}
    scene.world.session.flush()
    box = scene.stock(price_override_lbp=1)
    result = scene.turn(
        call("propose_reservation", listing_id=str(box), pickup_day=str(TODAY)),
        proposal_from(scene),
        LLMRefused("cannot repair"),
    )
    assert "budget" in scene.run(result).guardrails
    assert not result.proposal_ids


@pytest.mark.parametrize("constraint", ["budget", "pickup_day", "preference"])
def test_refusal_before_first_reply_cannot_bypass_card_constraints(
    scene: Scene, constraint: str
) -> None:
    box = scene.stock(price_override_lbp=700_000)
    scene.stock(price_override_lbp=500_000)
    client_text = {
        "budget": "I need Augmentin, my budget is 600,000 LBP",
        "pickup_day": "I need Augmentin for pickup tomorrow",
        "preference": "I want the cheapest option",
    }[constraint]
    result = scene.turn(
        call("find_options", product_ids=[str(scene.augmentin)]),
        call("propose_reservation", listing_id=str(box), pickup_day=str(TODAY), recommended=True),
        LLMRefused("cannot write a reply"),
        text=client_text,
    )
    assert constraint in scene.run(result).guardrails
    assert not result.proposal_ids
    assert scene.world.one("SELECT count(*) AS n FROM orders").n == 0


def test_client_budget_revision_survives_clarification(scene: Scene) -> None:
    scene.turn(reply("Which medicine?"), text="My budget is 300k LBP")
    scene.turn(reply("Which medicine?"), text="Actually my budget is 500k LBP")
    box = scene.stock(price_override_lbp=400_000)
    result = scene.turn(
        call("propose_reservation", listing_id=str(box), pickup_day=str(TODAY)),
        proposal_from(scene),
        text="I need Augmentin today",
    )
    assert len(result.proposal_ids) == 1
    assert "budget" not in scene.run(result).guardrails


@pytest.mark.parametrize("offset", [0, 1])
def test_explicit_pickup_survives_clarification_and_conflicting_model_notes(
    scene: Scene, offset: int
) -> None:
    scene.turn(
        reply("Which medicine?", case_notes={"pickup_day": str(TODAY)}),
        text="I want pickup tomorrow",
    )
    assert scene.conversation().case_state["client_pickup_day"] == str(TODAY + timedelta(days=1))
    box = scene.stock()
    result = scene.turn(
        call(
            "propose_reservation",
            listing_id=str(box),
            pickup_day=str(TODAY + timedelta(days=offset)),
        ),
        proposal_from(scene),
        LLMRefused("cannot repair"),
        text="I need Augmentin",
    )
    assert bool(result.proposal_ids) == (offset == 1)
    assert ("pickup_day" in scene.run(result).guardrails) == (offset != 1)
