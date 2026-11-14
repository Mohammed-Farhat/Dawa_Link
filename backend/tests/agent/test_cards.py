"""Cards: what a reply may show, and what a tap does (docs/04 R-AG7, INV-21; docs/06 §6.7).

Also the output guard, on whole turns: one chance to fix a reply, then our own words
(docs/07 §7.2, AG-D9; docs/09 FA-5 to FA-8, FA-22, FA-23).
"""

import uuid
from typing import Any

import pytest

from dawalink.agent.llm import LLMRefused
from dawalink.agent.llm.scripted import call, reply, say
from dawalink.agent.turn import Status
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

    def test_an_invented_card_is_caught_and_the_model_can_fix_it(self, scene: Scene) -> None:
        """FA-5, INV-21."""
        result = scene.turn(
            reply("Tap to reserve.", proposal_ids=[str(uuid.uuid4())]),
            reply("Which medicine do you need?"),
        )

        assert (result.text, result.proposal_ids) == ("Which medicine do you need?", ())
        run = scene.run(result)
        assert (run.outcome, run.guardrails, run.llm_calls) == ("ok", ["card"], 2)

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

    def test_the_wrong_language_is_fixed_or_sent_anyway(self, scene: Scene) -> None:
        """FA-8: low risk, so a second miss is sent and counted."""
        result = scene.turn(reply("مرحبا"), reply("أهلا"), text="hello")

        assert (result.outcome, result.text) == ("ok", "أهلا")
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
            "propose_constraint_change", thread, request_id=request, allow_alternatives=True
        )
        removal = scene.tool("propose_remove_item", thread, request_id=request, item_id=item)

        tap(scene, brands["proposal_id"])
        tap(scene, removal["proposal_id"])

        row = scene.world.one("SELECT * FROM sourcing_requests WHERE id = :r", r=request)
        assert row.alternatives_ok is True
        assert scene.world.one("SELECT state FROM request_items WHERE id = :i", i=item).state == (
            "CANCELLED"
        )
