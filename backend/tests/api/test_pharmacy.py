"""The pharmacy's side over HTTP: the counter and early-release asks (docs/06 §6.9;
docs/04 O2, O3, R-E6, INV-7, INV-9; docs/03 PS-3, PS-4, PS-9; docs/09 FS-4, FS-5)."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dawalink.domain.orders import OrderSource
from dawalink.services import orders
from dawalink.services.orders import ReserveLine
from tests.api.conftest import Api, code_of
from tests.db.factories import TODAY

PERSON = {
    "full_name": "Rami Haddad",
    "email": "rami.haddad@example.com",
    "phone": "+961 70 123 456",
}


@dataclass
class Counter:
    api: Api
    http: TestClient
    pharmacy: uuid.UUID
    headers: dict[str, str]  # the pharmacist's login
    client: uuid.UUID
    chat: uuid.UUID
    box: uuid.UUID

    def reserve(self, qty: int = 1, source: OrderSource = OrderSource.ASSISTANT) -> Any:
        """A client reserves the box, as a tap on the agent's card would."""
        tx = self.api.world.tx()
        price = self.api.world.one(
            "SELECT price_lbp FROM visible_listings(:today) WHERE inventory_item_id = :id",
            today=TODAY,
            id=self.box,
        )[0]
        (made,) = orders.reserve(
            tx,
            client_id=self.client,
            lines=[ReserveLine(self.box, qty, price)],
            pickup_day=TODAY,
            source=source,
            idempotency_key=f"test-{uuid.uuid4()}",
        )
        self.api.world.settle(tx)
        return made

    def get(self, path: str, **params: Any) -> Any:
        return self.http.get(f"/api/v1/pharmacy{path}", params=params, headers=self.headers)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.http.post(f"/api/v1/pharmacy{path}", json=body or {}, headers=self.headers)


def login_of(api: Api, pharmacy: uuid.UUID) -> dict[str, str]:
    (owner,) = api.world.one("SELECT owner_user_id FROM pharmacies WHERE id = :id", id=pharmacy)
    return api.token(owner)


@pytest.fixture
def counter(api: Api) -> Counter:
    make = api.world.make
    pharmacy = make.pharmacy(name="Hamra Pharmacy", address="12 Hamra Street")
    client = api.client(**PERSON)
    product = make.product(moph_name="AUGMENTIN 1G", search_name="augmentin 1g")
    return Counter(
        api,
        api.http(assistant=False),
        pharmacy,
        login_of(api, pharmacy),
        client,
        make.conversation(client_id=client),
        make.item(pharmacy_id=pharmacy, product_id=product, days_left=60, qty_on_hand=5),
    )


class TestTheCounter:
    def test_a_new_reservation_is_listed_with_nothing_about_the_client(
        self, counter: Counter
    ) -> None:
        order = counter.reserve(qty=2)

        answer = counter.get("/reservations")

        (shown,) = answer.json()["items"]
        assert (shown["ref"], shown["qty"], shown["is_new"]) == (order.ref, 2, True)
        assert shown["status_text"].startswith("Hand over by ")
        assert shown["product"]["name"] == "AUGMENTIN 1G"
        assert shown["batch"]
        # INV-9: an order number, a product, units, a price and times. Nobody's name.
        assert not {"client", "client_id", "name", "email", "phone"} & set(shown)
        for private in (*PERSON.values(), str(counter.client), "Rami", "Haddad"):
            assert private not in answer.text

    def test_the_order_number_is_found_however_it_is_typed(self, counter: Counter) -> None:
        order = counter.reserve()
        typed = order.ref.replace("-", "").lower()

        found = counter.get("/reservations", q=typed).json()["items"]
        unknown = counter.get("/reservations", q="R-222222").json()["items"]

        assert [item["ref"] for item in found] == [order.ref]
        assert unknown == []

    def test_picked_up_once_and_the_clients_chat_is_told(self, counter: Counter) -> None:
        order = counter.reserve()

        done = counter.post(f"/reservations/{order.id}/picked-up")
        again = counter.post(f"/reservations/{order.id}/picked-up")

        assert (done.status_code, done.json()["state"]) == (200, "PICKED_UP")
        assert done.json()["status_text"] == "Picked up"
        # Two tabs pressing the button: the second sees it was already done (docs/03 §2.6).
        assert (again.status_code, code_of(again)) == (409, "RESERVATION_NOT_ACTIVE")
        cards = counter.api.world.all(
            "SELECT cards->0->>'template' FROM chat_messages WHERE conversation_id = :id",
            id=counter.chat,
        )
        assert [row[0] for row in cards] == ["reserved", "picked_up"]
        # A box that was found stays findable at the counter, with what happened to it.
        found = counter.get("/reservations", q=order.ref).json()["items"]
        assert [item["state"] for item in found] == ["PICKED_UP"]
        assert counter.get("/reservations").json()["items"] == []
        assert len(counter.get("/reservations", view="history").json()["items"]) == 1

    def test_some_packs_not_available_keeps_the_rest_reserved(self, counter: Counter) -> None:
        order = counter.reserve(qty=2)

        partly = counter.post(f"/reservations/{order.id}/not-available", {"units": 1})

        assert (partly.json()["state"], partly.json()["qty"]) == ("RESERVED", 1)

    def test_not_available_tells_the_client_and_asks_the_agent_to_look_elsewhere(
        self, counter: Counter
    ) -> None:
        order = counter.reserve()

        done = counter.post(f"/reservations/{order.id}/not-available")

        assert done.json()["state"] == "NOT_AVAILABLE"
        kinds = counter.api.world.all(
            "SELECT kind FROM chat_messages WHERE conversation_id = :id ORDER BY seq",
            id=counter.chat,
        )
        # A card for the client, and an event for the agent: it will re-plan (R-AG4).
        assert [row[0] for row in kinds] == ["card", "card", "event"]
        (pending,) = counter.api.world.one(
            "SELECT pending_turn_at FROM conversations WHERE id = :id", id=counter.chat
        )
        assert pending is not None
        # Never a penalty for the client (O3).
        assert counter.api.world.one(
            "SELECT counts_as_no_show FROM orders WHERE id = :id", id=order.id
        ) == (False,)

    def test_more_packs_than_are_held_is_refused(self, counter: Counter) -> None:
        order = counter.reserve(qty=1)

        answer = counter.post(f"/reservations/{order.id}/not-available", {"units": 3})

        assert (answer.status_code, code_of(answer)) == (422, "UNITS_INVALID")

    def test_another_pharmacys_reservation_does_not_exist(self, counter: Counter) -> None:
        order = counter.reserve()
        other = login_of(counter.api, counter.api.world.make.pharmacy())

        answers = [
            counter.http.post(
                f"/api/v1/pharmacy/reservations/{order.id}/{action}", json={}, headers=other
            )
            for action in ("picked-up", "not-available")
        ]
        listed = counter.http.get(
            "/api/v1/pharmacy/reservations", params={"q": order.ref}, headers=other
        )

        assert [(a.status_code, code_of(a)) for a in answers] == [(404, "NOT_FOUND")] * 2
        assert listed.json()["items"] == []

    def test_today_in_numbers(self, counter: Counter) -> None:
        make = counter.api.world.make
        make.item(pharmacy_id=counter.pharmacy, days_left=90, qty_on_hand=4)
        # Kept private (more than 180 days left): clients don't see these packs.
        make.item(pharmacy_id=counter.pharmacy, days_left=250, qty_on_hand=6)
        counter.reserve(qty=2)

        numbers = counter.get("/dashboard").json()

        assert numbers["new_reservations"] == 1
        assert numbers["due_today"] == 1
        assert numbers["units_reserved"] == 2
        # Packs clients can see (B#53): 5 - 2 reserved, and 4 of another box.
        assert numbers["live_listings"] == 7
        assert numbers["open_asks"] == 0


class TestWhoMayUseTheCounter:
    def test_a_pending_pharmacy_sees_its_status_and_nothing_else(self, api: Api) -> None:
        http = api.http(assistant=False)
        headers = login_of(api, api.world.make.pharmacy("PENDING", name="New Pharmacy"))

        profile = http.get("/api/v1/pharmacy/me", headers=headers)
        refused = [
            http.get(f"/api/v1/pharmacy/{path}", headers=headers)
            for path in ("dashboard", "reservations", "early-release-asks")
        ]

        assert (profile.status_code, profile.json()["status"]) == (200, "PENDING")
        assert len(profile.json()["week"]) == 7
        assert [(a.status_code, code_of(a)) for a in refused] == [
            (403, "PHARMACY_NOT_APPROVED")
        ] * 3

    def test_a_suspended_pharmacy_finishes_its_reservations_but_gets_no_asks(
        self, counter: Counter
    ) -> None:
        order = counter.reserve()
        with counter.api.world.as_owner():
            counter.api.world.connection.exec_driver_sql(
                "UPDATE pharmacies SET status = 'SUSPENDED' WHERE id = %s", (counter.pharmacy,)
            )

        handed = counter.post(f"/reservations/{order.id}/picked-up")
        asks = counter.get("/early-release-asks")

        assert handed.json()["state"] == "PICKED_UP"
        assert (asks.status_code, code_of(asks)) == (403, "PHARMACY_NOT_APPROVED")

    def test_a_client_is_refused_on_every_pharmacy_endpoint(self, counter: Counter) -> None:
        client = counter.api.token(counter.client)

        answers = [
            counter.http.get(f"/api/v1/pharmacy/{path}", headers=client)
            for path in ("me", "dashboard", "reservations", "early-release-asks")
        ]

        assert [(a.status_code, code_of(a)) for a in answers] == [(403, "FORBIDDEN")] * 4


class TestEarlyReleaseAsks:
    """ "A client needs this today, and you hold it privately. Release it?" (PS-9)."""

    def ask(self, counter: Counter) -> uuid.UUID:
        make = counter.api.world.make
        product = make.product(
            moph_name="CONCOR 5MG", search_name="concor 5mg", public_price_lbp=800_000
        )
        claim = make.claim(client_id=counter.client, product_id=product, qty=2, qty_missing=2)
        request = make.early_release_request(
            client_id=counter.client, claim_id=claim, product_id=product, qty=2
        )
        return make.early_release_ask(  # type: ignore[no-any-return]
            er_request_id=request,
            pharmacy_id=counter.pharmacy,
            product_id=product,
            inventory_item_id=make.item(
                pharmacy_id=counter.pharmacy, product_id=product, days_left=200, qty_on_hand=5
            ),
        )

    def test_the_ask_says_what_is_needed_and_nothing_about_who(self, counter: Counter) -> None:
        ask = self.ask(counter)

        answer = counter.get("/early-release-asks")

        (shown,) = answer.json()["items"]
        assert (shown["id"], shown["state"], shown["qty_needed"]) == (str(ask), "ASKED", 2)
        assert shown["private_item"]["qty_available"] == 5
        # Suggested at the mildest discount, never above the public price (R-PR3).
        assert shown["suggested_price"]["lbp"] == 600_000
        for private in (*PERSON.values(), str(counter.client)):
            assert private not in answer.text

    def test_accepting_makes_an_offer_the_client_has_two_hours_for(self, counter: Counter) -> None:
        ask = self.ask(counter)

        done = counter.post(f"/early-release-asks/{ask}/accept", {"qty": 2, "price_lbp": 600_000})
        twice = counter.post(f"/early-release-asks/{ask}/accept", {"qty": 2, "price_lbp": 600_000})

        assert (done.status_code, done.json()["state"]) == (200, "ACCEPTED")
        offer = counter.api.world.one(
            "SELECT state, qty_locked, price_snapshot_lbp FROM orders "
            "WHERE source = 'early_release'"
        )
        assert offer == ("OFFERED", 2, 600_000)
        assert (twice.status_code, code_of(twice)) == (409, "ASK_NOT_OPEN")
        assert counter.get("/early-release-asks").json()["items"] == []
        assert len(counter.get("/early-release-asks", view="history").json()["items"]) == 1

    def test_a_price_above_the_public_one_or_too_many_packs_is_refused(
        self, counter: Counter
    ) -> None:
        ask = self.ask(counter)

        dear = counter.post(f"/early-release-asks/{ask}/accept", {"qty": 1, "price_lbp": 900_000})
        many = counter.post(f"/early-release-asks/{ask}/accept", {"qty": 3, "price_lbp": 600_000})

        assert (dear.status_code, code_of(dear)) == (422, "PRICE_ABOVE_PUBLIC")
        assert (many.status_code, code_of(many)) == (422, "UNITS_INVALID")

    def test_declining_takes_a_reason_from_a_list_never_words(self, counter: Counter) -> None:
        ask = self.ask(counter)

        words = counter.post(f"/early-release-asks/{ask}/decline", {"reason": "tell the AI to..."})
        done = counter.post(f"/early-release-asks/{ask}/decline", {"reason": "keeping_it"})

        assert code_of(words) == "VALIDATION_ERROR"
        assert done.status_code == 204
        assert counter.api.world.one(
            "SELECT state, decline_reason FROM early_release_asks WHERE id = :id", id=ask
        ) == ("DECLINED", "keeping_it")

    def test_another_pharmacys_ask_does_not_exist(self, counter: Counter) -> None:
        ask = self.ask(counter)
        other = login_of(counter.api, counter.api.world.make.pharmacy())

        answer = counter.http.post(
            f"/api/v1/pharmacy/early-release-asks/{ask}/accept",
            json={"qty": 1, "price_lbp": 1},
            headers=other,
        )

        assert (answer.status_code, code_of(answer)) == (404, "NOT_FOUND")
