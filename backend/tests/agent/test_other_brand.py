"""Another brand is shown with "ask the pharmacist first", and never reserved for the client.

Decision log BLD-D17; rules R-C10, R-AG8, INV-11, INV-25; docs/09 FA-34, FA-35.
Every test tries to get a reservation, a plan or a waiting claim for another brand without
the client asking for it in their own words.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dawalink.agent.llm import ModelReply, Prompt, ToolResults
from dawalink.agent.llm.scripted import call, reply
from dawalink.agent.pending import PendingTurns
from dawalink.db.models import Proposal
from dawalink.services import proposals
from dawalink.services.errors import Code, ServiceError
from dawalink.services.requests import RequestLine
from tests.agent.conftest import Scene
from tests.db.factories import TODAY

KEY = "amox-clav=1g | tablet"
ASK_FIRST = "Call the pharmacy and ask the pharmacist if this brand suits you"


@pytest.fixture
def clavox(scene: Scene) -> uuid.UUID:
    """Another brand of Augmentin. Tests put it on a shelf when Augmentin itself is not."""
    with scene.world.as_owner():
        scene.world.session.execute(
            text("UPDATE products SET equivalence_key = :k WHERE id = :p"),
            {"k": KEY, "p": scene.augmentin},
        )
    return scene.world.make.product(moph_name="CLAVOX 1G", equivalence_key=KEY)  # type: ignore[no-any-return]


def agreed(scene: Scene, conversation: uuid.UUID | None = None) -> None:
    """The client said yes to hearing about other brands, and the agent noted it."""
    scene.tool_turn(conversation).state.alternatives_ok = True


def found_as_another_brand(scene: Scene, clavox: uuid.UUID, thread: uuid.UUID | None = None) -> Any:
    """What `find_options` returns for the other brand when the client asked for Augmentin."""
    options = scene.tool("find_options", thread, product_ids=[scene.augmentin, clavox])["options"]
    (option,) = [option for option in options if option["is_alternative"]]
    return option


def reserve_card(
    scene: Scene, listing: uuid.UUID | str, thread: uuid.UUID | None = None, **more: Any
) -> Any:
    return scene.tool("propose_reservation", thread, listing_id=listing, pickup_day=TODAY, **more)


class TestTheCard:
    def test_it_says_where_the_brand_is_and_to_ask_the_pharmacist(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        box = scene.stock(clavox, price_override_lbp=600_000)
        agreed(scene)
        option = found_as_another_brand(scene, clavox)

        card = scene.tool("show_other_brand", listing_id=box, instead_of_product_id=scene.augmentin)

        assert option["listing_id"] == str(box)
        assert card["preview"]["title"] == "Another brand: CLAVOX 1G at Hamra Pharmacy"
        assert "Instead of: AUGMENTIN 1G" in card["preview"]["lines"]
        assert "It has: the same ingredient, strength and form" in card["preview"]["lines"]
        assert f"Before you go: {ASK_FIRST}" in card["preview"]["lines"]
        stored = scene.world.one("SELECT kind, payload FROM proposals")
        assert stored.kind == "other_brand"
        assert stored.payload["pharmacy_id"] == str(scene.pharmacy)

    def test_the_phone_is_read_for_the_screen_and_never_passes_the_model(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """R-AG8: the model gets the card's text; the [Call] button's number is not in it."""
        box = scene.stock(clavox)
        agreed(scene)
        phone = scene.world.one(
            "SELECT phone FROM pharmacies WHERE id = :p", p=scene.pharmacy
        ).phone

        card = scene.tool("show_other_brand", listing_id=box, instead_of_product_id=scene.augmentin)

        proposal = scene.world.session.get_one(Proposal, uuid.UUID(card["proposal_id"]))
        assert phone not in json.dumps(card)
        assert phone not in json.dumps(proposal.payload)
        assert proposals.call_number(scene.world.session, proposal) == phone

    def test_a_tap_on_it_changes_nothing(self, scene: Scene, clavox: uuid.UUID) -> None:
        box = scene.stock(clavox)
        agreed(scene)
        card = scene.tool("show_other_brand", listing_id=box, instead_of_product_id=scene.augmentin)

        with pytest.raises(ServiceError) as refused:
            proposals.execute(
                scene.world.tx(), client_id=scene.client, proposal_id=uuid.UUID(card["proposal_id"])
            )

        assert refused.value.code is Code.VALIDATION_ERROR
        assert scene.world.all("SELECT 1 FROM orders") == []
        assert scene.world.one("SELECT qty_reserved FROM inventory_items").qty_reserved == 0

    def test_only_if_the_client_agreed_to_hear_about_other_brands(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """G4: consent, now checked by code."""
        box = scene.stock(clavox)

        asked = {"listing_id": box, "instead_of_product_id": scene.augmentin}

        told = scene.tool("show_other_brand", **asked)
        # The agent can't say "they agreed" in a turn that no client message started.
        claimed = scene.tool("show_other_brand", **asked, client_agreed=True)

        assert told["error_code"] == claimed["error_code"] == "OTHER_BRANDS_NOT_AGREED"
        assert scene.world.all("SELECT 1 FROM proposals") == []

    def test_a_yes_in_the_message_being_answered_counts_and_is_remembered(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """Found on the first real run: the yes and the card belong to the same turn."""
        box = scene.stock(clavox)
        asked = {"listing_id": box, "instead_of_product_id": scene.augmentin}
        scene.tool_turn().by_client = True

        first = scene.tool("show_other_brand", **asked, client_agreed=True)
        scene.tool_turn().by_client = False
        later = scene.tool("show_other_brand", **asked)

        assert "proposal_id" in first
        assert "proposal_id" in later
        assert scene.tool_turn().state.alternatives_ok is True

    def test_the_profiles_default_counts_until_the_client_says_no(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        box = scene.stock(clavox)
        asked = {"listing_id": box, "instead_of_product_id": scene.augmentin}
        with scene.world.as_owner():
            scene.world.session.execute(
                text(
                    "UPDATE client_profiles SET alternatives_ok_default = true WHERE user_id = :c"
                ),
                {"c": scene.client},
            )

        by_default = scene.tool("show_other_brand", **asked)
        scene.tool_turn().state.alternatives_ok = False  # "no other brands", noted in this chat
        after_a_no = scene.tool("show_other_brand", **asked)

        assert "proposal_id" in by_default
        assert after_a_no["error_code"] == "OTHER_BRANDS_NOT_AGREED"

    def test_it_must_be_another_brand_of_that_very_medicine(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        agreed(scene)
        itself = scene.stock(scene.augmentin)
        something_else = scene.stock(scene.concor)

        answers = [
            scene.tool("show_other_brand", listing_id=box, instead_of_product_id=scene.augmentin)
            for box in (itself, something_else)
        ]

        assert [answer["error_code"] for answer in answers] == ["NOT_SAME_MEDICINE"] * 2

    def test_a_box_that_expires_too_early_is_not_shown(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """INV-25."""
        box = scene.stock(clavox, days_left=5)
        agreed(scene)

        told = scene.tool(
            "show_other_brand",
            listing_id=box,
            instead_of_product_id=scene.augmentin,
            days_of_use=10,
        )

        assert told["error_code"] == "DOES_NOT_FIT"


class TestNoReservationOfAnotherBrand:
    def test_a_reserve_card_for_it_is_refused(self, scene: Scene, clavox: uuid.UUID) -> None:
        box = scene.stock(clavox)
        found_as_another_brand(scene, clavox)

        told = reserve_card(scene, box)

        assert told["error_code"] == "ASK_PHARMACIST_FIRST"
        assert scene.world.all("SELECT 1 FROM proposals") == []

    def test_every_box_of_that_brand_is_refused_not_only_the_one_found(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        scene.stock(clavox)
        found_as_another_brand(scene, clavox)
        elsewhere = scene.stock(clavox, pharmacy_id=scene.world.make.pharmacy())

        assert reserve_card(scene, elsewhere)["error_code"] == "ASK_PHARMACIST_FIRST"

    def test_knowing_the_other_brands_is_enough_to_refuse(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """The agent can't skip `find_options` to keep the brand unmarked."""
        box = scene.stock(clavox)
        scene.tool("get_equivalents", product_id=scene.augmentin)

        assert reserve_card(scene, box)["error_code"] == "ASK_PHARMACIST_FIRST"

    def test_the_clients_own_word_in_their_own_message_opens_it(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """The client called the pharmacist, and now asks for that brand."""
        box = scene.stock(clavox)
        found_as_another_brand(scene, clavox)
        scene.tool_turn().by_client = True

        card = reserve_card(scene, box, client_asked_for_this_brand=True)

        assert card["preview"]["title"] == "CLAVOX 1G at Hamra Pharmacy"
        assert (
            "Brand: Another brand than you first asked for, at your request"
            in card["preview"]["lines"]
        )

    def test_the_agent_can_not_say_so_in_a_turn_no_client_message_started(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """A worker turn (an event, a follow-up) has no client words to rely on."""
        box = scene.stock(clavox)
        found_as_another_brand(scene, clavox)

        told = reserve_card(scene, box, client_asked_for_this_brand=True)

        assert scene.tool_turn().by_client is False
        assert told["error_code"] == "ASK_PHARMACIST_FIRST"

    def test_a_brand_the_client_asked_for_from_the_start_is_a_normal_reservation(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        box = scene.stock(clavox)
        scene.tool("find_options", product_ids=[clavox])

        card = reserve_card(scene, box)

        assert card["preview"]["title"] == "CLAVOX 1G at Hamra Pharmacy"
        assert not any(line.startswith("Brand:") for line in card["preview"]["lines"])

    def test_searching_the_brand_by_itself_later_does_not_make_it_the_clients_medicine(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """The first product searched of a medicine stays the client's medicine in a chat."""
        box = scene.stock(clavox)
        scene.tool("find_options", product_ids=[scene.augmentin])  # nothing listed
        scene.tool("find_options", product_ids=[clavox])

        assert reserve_card(scene, box)["error_code"] == "ASK_PHARMACIST_FIRST"

    def test_what_code_can_not_know_in_a_chat(self, scene: Scene, clavox: uuid.UUID) -> None:
        """A limit, written down on purpose (docs/07 §14.7).

        The client asked for Augmentin in words. If the agent never searches Augmentin and
        goes straight to another brand's product, code has nothing that says so: the
        prompt forbids it, and the safety evaluation (E4) checks it. In a request this
        can't happen: the item fixes what was asked.
        """
        box = scene.stock(clavox)
        scene.tool("find_options", product_ids=[clavox])

        assert "proposal_id" in reserve_card(scene, box)

    def test_a_plan_never_holds_another_brand(self, scene: Scene, clavox: uuid.UUID) -> None:
        """A plan's card reserves everything with one tap."""
        scene.stock(clavox)

        found = scene.tool("plan_basket", items=[{"product_id": scene.augmentin}])

        assert found["plans"] == []
        assert [gap["reason"] for gap in found["unplannable"]] == ["none_listed"]

    def test_a_watch_can_not_be_told_to_wait_for_other_brands(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        told = scene.tool("create_watch", product_id=scene.augmentin, include_alternatives=True)

        assert told["error_code"] == "INVALID_ARGUMENTS"


class TestInARequest:
    """The request item says what was asked: nothing else is ever the medicine itself."""

    def thread(self, scene: Scene, *, other_brands: bool) -> tuple[uuid.UUID, uuid.UUID]:
        request, thread = scene.start_request(RequestLine(scene.augmentin))
        if other_brands:
            with scene.world.as_owner():
                scene.world.session.execute(
                    text("UPDATE sourcing_requests SET alternatives_ok = true WHERE id = :r"),
                    {"r": request},
                )
        return request, thread

    def test_the_card_needs_the_requests_own_yes(self, scene: Scene, clavox: uuid.UUID) -> None:
        box = scene.stock(clavox)
        _, strict = self.thread(scene, other_brands=False)
        agreed(scene, strict)  # a note of the agent's doesn't replace the request's setting

        told = scene.tool(
            "show_other_brand", strict, listing_id=box, instead_of_product_id=scene.augmentin
        )

        assert told["error_code"] == "OTHER_BRANDS_NOT_AGREED"

    def test_the_card_is_for_a_medicine_the_request_still_looks_for(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        with scene.world.as_owner():
            scene.world.session.execute(
                text("UPDATE products SET equivalence_key = 'biso=5mg | tablet' WHERE id = :p"),
                {"p": scene.concor},
            )
        other_concor = scene.world.make.product(equivalence_key="biso=5mg | tablet")
        box = scene.stock(other_concor)
        _, thread = self.thread(scene, other_brands=True)

        told = scene.tool(
            "show_other_brand", thread, listing_id=box, instead_of_product_id=scene.concor
        )

        assert told["error_code"] == "VALIDATION_ERROR"

    def test_a_reserve_card_is_refused_even_when_the_brand_was_searched_by_itself(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        box = scene.stock(clavox)
        _, thread = self.thread(scene, other_brands=True)
        scene.tool("find_options", thread, product_ids=[clavox])

        told = reserve_card(scene, box, thread)

        assert told["error_code"] == "ASK_PHARMACIST_FIRST"

    def test_after_the_clients_word_the_brand_secures_the_medicine(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """The reservation the client asked for serves the need the request was started for."""
        box = scene.stock(clavox)
        request, thread = self.thread(scene, other_brands=True)
        shown = scene.tool(
            "show_other_brand", thread, listing_id=box, instead_of_product_id=scene.augmentin
        )
        scene.tool_turn(thread).by_client = True

        card = reserve_card(scene, box, thread, client_asked_for_this_brand=True)
        tx = scene.world.tx()
        done = proposals.execute(
            tx, client_id=scene.client, proposal_id=uuid.UUID(card["proposal_id"])
        )
        scene.world.settle(tx)

        item = scene.world.one("SELECT state FROM request_items WHERE request_id = :r", r=request)
        assert "proposal_id" in shown
        assert [order.product_id for order in done.orders] == [clavox]
        assert item.state == "SECURED"


def results(prompt: Prompt) -> list[dict[str, Any]]:
    last = prompt.messages[-1]
    assert isinstance(last, ToolResults)
    return [json.loads(result.content) for result in last.results]


class TestWholeTurns:
    def test_a_client_message_lets_the_agent_reserve_the_brand_they_asked_for(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        box = scene.stock(clavox)
        scene.turn(
            call("find_options", product_ids=[str(scene.augmentin), str(clavox)]),
            reply(
                "Augmentin isn't listed. Another brand exists.",
                case_notes={"alternatives_ok": True},
            ),
        )

        def show(prompt: Prompt) -> ModelReply:
            return reply("Here it is.", proposal_ids=[results(prompt)[0]["proposal_id"]])

        result = scene.turn(
            call(
                "propose_reservation",
                listing_id=str(box),
                pickup_day=str(TODAY),
                client_asked_for_this_brand=True,
            ),
            show,
            text="The pharmacist said Clavox is fine, reserve it",
        )

        assert scene.tool_calls(result) == [("propose_reservation", True, None)]
        assert scene.world.one("SELECT kind FROM proposals").kind == "reserve"

    def test_no_quick_reply_may_say_the_pharmacist_agreed(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """FA-38. Seen on a real run: one tap would have claimed a call that never happened."""
        scene.stock(clavox)

        def show(prompt: Prompt) -> ModelReply:
            (option,) = [o for o in results(prompt)[0]["options"] if o["is_alternative"]]
            return call(
                "show_other_brand",
                listing_id=option["listing_id"],
                instead_of_product_id=str(scene.augmentin),
                client_agreed=True,
            )

        def card_of(prompt: Prompt) -> str:
            made = [
                json.loads(result.content)
                for message in prompt.messages
                if isinstance(message, ToolResults)
                for result in message.results
                if result.name == "show_other_brand"
            ]
            return str(made[-1]["proposal_id"])

        def with_a_shortcut(prompt: Prompt) -> ModelReply:
            return reply(
                "Another brand is at Hamra Pharmacy. Call them first.",
                proposal_ids=[card_of(prompt)],
                quick_replies=["Pharmacist agreed, reserve it", "No thanks"],
            )

        def without_it(prompt: Prompt) -> ModelReply:
            return reply(
                "Another brand is at Hamra Pharmacy. Call them first.",
                proposal_ids=[card_of(prompt)],
                quick_replies=["Show other pharmacies", "No thanks"],
            )

        result = scene.turn(
            call("find_options", product_ids=[str(scene.augmentin), str(clavox)]),
            show,
            with_a_shortcut,
            without_it,
            text="Yes, tell me about other brands of Augmentin",
        )

        assert scene.run(result).guardrails == ["card"]
        assert scene.messages()[-1].quick_replies == ["Show other pharmacies", "No thanks"]

    def test_a_worker_turn_can_not_reserve_another_brand(
        self, scene: Scene, clavox: uuid.UUID
    ) -> None:
        """The autonomous mode: an event wakes the agent, and no client wrote anything."""
        box = scene.stock(clavox)
        _, thread = TestInARequest().thread(scene, other_brands=True)
        agent = scene.agent(
            call(
                "propose_reservation",
                listing_id=str(box),
                pickup_day=str(TODAY),
                client_asked_for_this_brand=True,
            ),
            reply("Augmentin isn't listed yet. I keep looking."),
        )

        assert PendingTurns(agent).run_pending_turns() == 1

        calls = scene.world.all("SELECT tool, ok, error_code FROM agent_tool_calls")
        assert [(row.tool, row.ok, row.error_code) for row in calls] == [
            ("propose_reservation", False, "ASK_PHARMACIST_FIRST")
        ]
        assert scene.world.all("SELECT 1 FROM proposals") == []
        assert thread is not None
