"""Refusals of the catalog (docs/06 §3.2) as the website receives them: the limits, a card
that expired, a plan card whose items are gone, the assistant's daily budget, a pickup
after the deadline.

The rules themselves are tested where they live (`tests/services/`, `tests/agent/`).
Here each one is caused through the API, so that its HTTP status and its code are what
docs/06 promises (§9: every code has a test that triggers it; docs/09 FA-19, FA-22, FR-9).
"""

import uuid
from typing import Any

from dawalink.domain.numbers import (
    DAILY_TOKEN_BUDGET_PER_CLIENT,
    MAX_OPEN_ORDERS,
    MAX_OPEN_REQUESTS,
    MAX_WATCHES,
)
from dawalink.services.requests import RequestLine
from tests.agent.conftest import Scene, scene  # noqa: F401  (the fixture)
from tests.api.conftest import Api, code_of, events_of
from tests.api.test_chat import Chat, chat  # noqa: F401  (the fixture)
from tests.api.test_pharmacy import Counter, counter  # noqa: F401  (the fixture)
from tests.api.test_search import Shop, shop  # noqa: F401  (the fixture)


def a_tap() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


class TestAClientsLimits:
    def test_a_sixth_open_reservation_is_refused(self, shop: Shop) -> None:  # noqa: F811
        """R-L1."""
        make = shop.api.world.make
        for number in range(MAX_OPEN_ORDERS):
            other = make.item(
                pharmacy_id=shop.near,
                product_id=make.product(public_price_lbp=1_000_000),
                days_left=60,
                qty_on_hand=3,
            )
            assert shop.reserve(f"tap-{number}", listing_id=str(other)).status_code == 201

        one_more = shop.reserve("one-more")

        assert (one_more.status_code, code_of(one_more)) == (409, "LIMIT_OPEN_ORDERS")
        assert shop.api.world.one("SELECT count(*) FROM orders") == (MAX_OPEN_ORDERS,)

    def test_a_fourth_pack_of_one_medicine_is_refused(self, shop: Shop) -> None:  # noqa: F811
        """R-L2: three packs across every open reservation of the medicine."""
        assert shop.reserve("three", qty=3).status_code == 201

        fourth = shop.reserve("a-fourth")

        assert (fourth.status_code, code_of(fourth)) == (409, "LIMIT_GROUP_UNITS")
        assert shop.api.world.one("SELECT sum(qty_locked) FROM orders") == (3,)

    def test_a_sixth_watch_is_refused(self, api: Api) -> None:
        """R-W2."""
        http = api.http(assistant=False)
        login = api.token(api.client())

        def watch() -> Any:
            body = {
                "product_id": str(api.world.make.product()),
                "location": {"lat": 33.8959, "lon": 35.4784},
            }
            return http.post("/api/v1/watches", json=body, headers=login)

        made = [watch().status_code for _ in range(MAX_WATCHES)]
        one_more = watch()

        assert made == [201] * MAX_WATCHES
        assert (one_more.status_code, code_of(one_more)) == (409, "LIMIT_WATCHES")
        assert api.world.one("SELECT count(*) FROM claims") == (MAX_WATCHES,)

    def test_a_third_open_request_is_refused_at_the_tap(self, api: Api, scene: Scene) -> None:  # noqa: F811
        """R-RQ2: the card was made while there was room; the tap checks again."""
        card = scene.tool(
            "prepare_request_summary",
            items=[{"product_id": scene.augmentin, "qty": 1, "days_of_use": 7}],
            alternatives_ok=False,
        )
        for _ in range(MAX_OPEN_REQUESTS):
            scene.start_request(RequestLine(scene.world.make.product()))

        answer = api.http().post(
            f"/api/v1/proposals/{card['proposal_id']}/execute",
            json={},
            headers=api.token(scene.client) | a_tap(),
        )

        assert (answer.status_code, code_of(answer)) == (409, "LIMIT_OPEN_REQUESTS")
        assert scene.world.one("SELECT count(*) FROM sourcing_requests") == (MAX_OPEN_REQUESTS,)


class TestTheAssistantsDailyBudget:
    def test_a_client_who_used_the_days_tokens_is_told_until_when(self, chat: Chat) -> None:  # noqa: F811
        """R-AS, FA-19: no model call, nothing stored, and search is named as the way on."""
        world = chat.api.world
        world.make.agent_run(
            conversation_id=chat.chat,
            started_at=world.clock.now(),
            tokens_in=DAILY_TOKEN_BUDGET_PER_CLIENT,
            tokens_out=1,
        )
        http = chat.api.http()

        answer = chat.say(http)

        assert (answer.status_code, code_of(answer)) == (429, "TOKEN_BUDGET_EXCEEDED")
        assert answer.json()["error"]["details"]["until"]
        assert "Search still works" in answer.json()["error"]["message"]
        assert chat.api.models[-1].seen == []
        assert world.all("SELECT 1 FROM chat_messages") == []


class TestACardThatCantBeUsed:
    def test_a_card_older_than_two_hours_is_refused(self, chat: Chat) -> None:  # noqa: F811
        """N-30."""
        http = chat.api.http(*chat.reserve_turn())
        card = dict(events_of(chat.say(http)))["message"]["cards"][0]["card_id"]
        chat.api.world.later(hours=2, seconds=1)

        answer = http.post(
            f"/api/v1/proposals/{card}/execute", json={}, headers=chat.headers | a_tap()
        )

        assert (answer.status_code, code_of(answer)) == (409, "PROPOSAL_EXPIRED")
        assert http.get("/api/v1/reservations", headers=chat.headers).json()["items"] == []

    def plan_card(self, scene: Scene) -> tuple[uuid.UUID, str]:  # noqa: F811
        """A request for two medicines, and the agent's [Reserve these] card for both."""
        _, thread = scene.start_request()
        scene.stock(scene.augmentin)
        scene.stock(scene.concor)
        plan = scene.tool(
            "plan_basket",
            thread,
            items=[{"product_id": scene.augmentin}, {"product_id": scene.concor}],
        )["plans"][0]
        card = scene.tool("propose_plan", thread, plan_id=plan["plan_id"])["proposals"][0]
        return thread, str(card["proposal_id"])

    def test_a_plan_card_needs_at_least_one_of_its_own_items(self, api: Api, scene: Scene) -> None:  # noqa: F811
        """R-RQ6."""
        _, card = self.plan_card(scene)
        http = api.http()
        login = api.token(scene.client)

        for selection in ([], ["something-else"]):
            answer = http.post(
                f"/api/v1/proposals/{card}/execute",
                json={"selected_item_keys": selection},
                headers=login | a_tap(),
            )
            assert (answer.status_code, code_of(answer)) == (422, "SELECTION_INVALID")
        assert scene.world.all("SELECT 1 FROM orders") == []

    def test_a_plan_whose_box_is_gone_reserves_nothing_and_wakes_the_agent(
        self,
        api: Api,
        scene: Scene,  # noqa: F811
    ) -> None:
        """R-RQ6, FA-22: all or none, and the agent is asked to plan again."""
        thread, card = self.plan_card(scene)
        with scene.world.as_owner():
            scene.world.connection.exec_driver_sql(
                "UPDATE inventory_items SET qty_on_hand = 0 WHERE product_id = %s", (scene.concor,)
            )

        answer = api.http().post(
            f"/api/v1/proposals/{card}/execute",
            json={},
            headers=api.token(scene.client) | a_tap(),
        )

        assert (answer.status_code, code_of(answer)) == (409, "GROUP_ITEM_FAILED")
        assert scene.world.all("SELECT 1 FROM orders") == []
        assert scene.conversation(thread).pending_turn_at is not None
        assert '"type": "group_item_failed"' in scene.messages(thread)[-1].text_redacted


class TestTheCounter:
    def test_picked_up_after_the_deadline_is_refused(self, counter: Counter) -> None:  # noqa: F811
        """FR-9, R-T4: there is no late pickup; the box goes back to the shelf."""
        order = counter.reserve()
        counter.api.world.later(hours=11)

        late = counter.post(f"/reservations/{order.id}/picked-up")

        assert (late.status_code, code_of(late)) == (409, "PICKUP_DEADLINE_PASSED")
        assert counter.api.world.one("SELECT state FROM orders WHERE id = :id", id=order.id) == (
            "RESERVED",
        )
