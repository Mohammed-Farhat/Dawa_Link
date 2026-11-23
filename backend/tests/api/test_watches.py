"""[Notify me] and the notifications list over HTTP (docs/06 §6.4, §6.8; docs/03 CS-11,
CS-12, PS-11; slice 7g)."""

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest

from dawalink.domain.orders import OrderSource
from dawalink.services import inventory, orders
from tests.api.conftest import Api, code_of
from tests.db.factories import TODAY

WATCHES = "/api/v1/watches"
NOTES = "/api/v1/notifications"


@pytest.fixture
def product(api: Api) -> uuid.UUID:
    return api.world.make.product(moph_name="GLUCOPHAGE 850MG", search_name="glucophage 850mg")  # type: ignore[no-any-return]


def stock_arrives(api: Api, product: uuid.UUID, **values: Any) -> uuid.UUID:
    """A pharmacy lists a box of the medicine: whoever waits first is served (R-PRI1)."""
    pharmacy = api.world.make.pharmacy(name="Hamra Pharmacy")
    tx = api.world.tx()
    item = inventory.add_item(
        tx,
        pharmacy,
        product_id=product,
        batch="G1",
        expiry_date=TODAY + timedelta(days=60),
        quantity=3,
        **values,
    )
    api.world.settle(tx)
    return item.id


class TestNotifyMe:
    def test_a_price_limit_is_in_pounds_or_dollars(self, api: Api, product: uuid.UUID) -> None:
        """FI-5: any other currency is a field that is wrong, never a guess at a rate."""
        http = api.http()
        login = api.token(api.client())

        euros = http.post(
            WATCHES,
            json={"product_id": str(product), "max_price": {"amount": 10, "currency": "EUR"}},
            headers=login,
        )

        assert (euros.status_code, code_of(euros)) == (422, "VALIDATION_ERROR")
        assert euros.json()["error"]["details"]["fields"][0]["field"] == "max_price.currency"
        assert api.world.all("SELECT 1 FROM claims") == []

    def test_a_watch_is_made_listed_and_stopped(self, api: Api, product: uuid.UUID) -> None:
        http = api.http()
        login = api.token(api.client())

        made = http.post(
            WATCHES,
            json={
                "product_id": str(product),
                "qty": 2,
                "days_of_use": 10,
                "max_price": {"amount": 900000, "currency": "LBP"},
                "location": {"lat": 33.8959, "lon": 35.4784},
            },
            headers=login,
        )
        twice = http.post(WATCHES, json={"product_id": str(product)}, headers=login)
        listed = http.get(WATCHES, headers=login).json()["items"]
        stopped = http.post(f"{WATCHES}/{made.json()['id']}/cancel", headers=login)
        again = http.post(f"{WATCHES}/{made.json()['id']}/cancel", headers=login)

        watch = made.json()
        assert (made.status_code, watch["state"], watch["qty"], watch["days_of_use"]) == (
            201,
            "ACTIVE",
            2,
            10,
        )
        assert watch["max_price"]["lbp"] == 900_000
        # The place is said in words; the point itself is in no answer (INV-24).
        assert watch["district"] == "Beirut"
        assert "33.89" not in made.text
        assert "35.47" not in made.text
        assert (twice.status_code, code_of(twice)) == (409, "WATCH_EXISTS")
        assert twice.json()["error"]["details"]["watch_id"] == watch["id"]
        assert [row["id"] for row in listed] == [watch["id"]]
        assert stopped.json()["state"] == "CANCELLED"
        assert (again.status_code, code_of(again)) == (409, "CLAIM_NOT_ACTIVE")
        assert http.get(WATCHES, headers=login).json()["items"] == []
        assert len(http.get(f"{WATCHES}?state=all", headers=login).json()["items"]) == 1

    def test_the_answer_says_the_servers_time(self, api: Api, product: uuid.UUID) -> None:
        """B#39: the page says "until tomorrow 01:30" from the server's clock, never the
        device's: the demo clock may be ahead of it."""
        http = api.http()
        login = api.token(api.client())
        api.world.later(hours=9, minutes=30)  # 19:30 in Beirut: the watch ends after midnight

        made = http.post(WATCHES, json={"product_id": str(product)}, headers=login).json()

        now = api.world.clock.now()
        assert datetime.fromisoformat(made["server_now"]) == now
        assert datetime.fromisoformat(made["ends_at"]) == now + timedelta(hours=6)

    def test_only_during_request_hours_and_only_for_a_client_who_can_reserve(
        self, api: Api, product: uuid.UUID
    ) -> None:
        http = api.http()
        login = api.token(api.client())
        paused = api.token(
            api.world.make.client("PAUSED", paused_until=api.world.clock.now() + timedelta(days=3))
        )
        body = {"product_id": str(product)}

        not_theirs = http.post(f"{WATCHES}/{uuid.uuid4()}/cancel", headers=login)
        refused = http.post(WATCHES, json=body, headers=paused)
        api.world.later(hours=12)  # 22:00 in Beirut
        at_night = http.post(WATCHES, json=body, headers=login)

        assert (not_theirs.status_code, code_of(not_theirs)) == (404, "NOT_FOUND")
        assert (refused.status_code, code_of(refused)) == (403, "CLIENT_PAUSED")
        assert (at_night.status_code, code_of(at_night)) == (409, "OUTSIDE_REQUEST_HOURS")
        assert at_night.json()["error"]["details"]["opens_at"]

    def test_stock_that_appears_becomes_an_offer_the_client_accepts(
        self, api: Api, product: uuid.UUID
    ) -> None:
        """A watch has no request and no chat behind it: its offer is found on the
        offers list, and accepting it is a reservation like any other."""
        http = api.http()
        client = api.client()
        login = api.token(client)
        watch = http.post(WATCHES, json={"product_id": str(product)}, headers=login).json()

        stock_arrives(api, product)
        (offer,) = http.get("/api/v1/offers", headers=login).json()["items"]
        holding = http.get(WATCHES, headers=login).json()["items"]
        accepted = http.post(
            f"/api/v1/offers/{offer['id']}/accept",
            json={"pickup_day": str(TODAY)},
            headers=login | {"Idempotency-Key": "watch-offer-1"},
        )
        after = http.get(f"{WATCHES}?state=all", headers=login).json()["items"]

        assert offer["product"]["name"] == "GLUCOPHAGE 850MG"
        assert [(row["id"], row["state"]) for row in holding] == [(watch["id"], "OFFER_PENDING")]
        assert (accepted.status_code, accepted.json()["state"]) == (201, "RESERVED")
        assert [row["state"] for row in after] == ["FULFILLED"]
        assert "CN-10" in api.world.notifications(client)


class TestNotifications:
    def test_what_happened_is_listed_with_where_a_tap_goes(
        self, api: Api, product: uuid.UUID
    ) -> None:
        http = api.http()
        client = api.client()
        login = api.token(client)
        http.post(WATCHES, json={"product_id": str(product)}, headers=login)
        stock_arrives(api, product)
        (offer,) = http.get("/api/v1/offers", headers=login).json()["items"]
        reserved = http.post(
            f"/api/v1/offers/{offer['id']}/accept",
            json={"pickup_day": str(TODAY)},
            headers=login | {"Idempotency-Key": "note-1"},
        ).json()

        page = http.get(NOTES, headers=login).json()
        count = http.get(f"{NOTES}/unread-count", headers=login).json()

        by_type = {row["type"]: row for row in page["items"]}
        assert set(by_type) == {"CN-10", "CN-3"}
        assert by_type["CN-3"]["title"] == f"Reserved: {reserved['ref']}"
        assert f"Order number: {reserved['ref']}" in by_type["CN-3"]["lines"]
        assert by_type["CN-3"]["link"] == f"/reservations/{reserved['id']}"
        # An offer is answered on Home, where its card is.
        assert by_type["CN-10"]["link"] == "/"
        assert (page["unread"], count["count"]) == (2, 2)
        assert all(not row["read"] for row in page["items"])
        # The newest first, and a page at a time.
        assert [row["type"] for row in page["items"]] == ["CN-3", "CN-10"]
        first = http.get(f"{NOTES}?limit=1", headers=login).json()
        older = http.get(f"{NOTES}?limit=1&cursor={first['next_cursor']}", headers=login).json()
        assert [row["type"] for row in older["items"]] == ["CN-10"]

    def test_marking_as_read_touches_only_ones_own(self, api: Api, product: uuid.UUID) -> None:
        """Notification numbers follow each other: someone else's must not be a way in."""
        http = api.http()
        client, other = api.client(), api.client()
        login, their_login = api.token(client), api.token(other)
        for who in (login, their_login):
            http.post(WATCHES, json={"product_id": str(product)}, headers=who)
        stock_arrives(api, product)
        stock_arrives(api, product, price_override_lbp=None)
        mine = http.get(NOTES, headers=login).json()["items"]
        theirs = http.get(NOTES, headers=their_login).json()["items"]
        assert mine
        assert theirs

        sneaky = http.post(
            f"{NOTES}/read", json={"ids": [row["id"] for row in theirs]}, headers=login
        )
        untouched = http.get(f"{NOTES}/unread-count", headers=their_login).json()["count"]
        one = http.post(f"{NOTES}/read", json={"ids": [mine[0]["id"]]}, headers=login)
        after_one = http.get(NOTES, headers=login).json()
        http.post(f"{NOTES}/read", json={"all": True}, headers=their_login)

        assert (sneaky.status_code, untouched) == (204, len(theirs))
        assert one.status_code == 204
        assert [row["read"] for row in after_one["items"]] == [True] + [False] * (len(mine) - 1)
        assert http.get(f"{NOTES}/unread-count", headers=their_login).json()["count"] == 0

    def test_a_pharmacys_tap_goes_where_the_reservation_is(self, api: Api) -> None:
        """B#52: a new reservation is to hand over; a cancelled one is in the history,
        never an empty "To hand over"."""
        http = api.http()
        make = api.world.make
        owner = make.user("pharmacist", email_verified_at=api.world.clock.now())
        pharmacy = make.pharmacy(owner_user_id=owner)
        box = make.item(pharmacy_id=pharmacy, product_id=make.product(), days_left=60)
        client = api.client()
        tx = api.world.tx()
        price = api.world.one(
            "SELECT price_lbp FROM visible_listings(:today) WHERE inventory_item_id = :id",
            today=TODAY,
            id=box,
        )[0]
        (made,) = orders.reserve(
            tx,
            client_id=client,
            lines=[orders.ReserveLine(box, 1, price)],
            pickup_day=TODAY,
            source=OrderSource.SEARCH,
            idempotency_key=f"tap-{uuid.uuid4()}",
        )
        api.world.settle(tx)
        http.post(f"/api/v1/reservations/{made.id}/cancel", headers=api.token(client))

        page = http.get(NOTES, headers=api.token(owner)).json()["items"]

        links = {row["type"]: row["link"] for row in page}
        assert links == {
            "PN-4": "/pharmacy/reservations",
            "PN-8": "/pharmacy/reservations?view=history",
        }

    def test_a_pharmacy_reads_its_own_with_the_teams_words(self, api: Api) -> None:
        """PS-11. What DawaLink's team wrote about a registration is shown as it is."""
        http = api.http()
        admin = api.token(api.world.make.user("admin", totp_secret=b"not-a-real-secret"))
        owner = api.world.make.user("pharmacist", email_verified_at=api.world.clock.now())
        pharmacy = api.world.make.pharmacy("PENDING", owner_user_id=owner)
        http.post(
            f"/api/v1/admin/pharmacies/{pharmacy}/request-info",
            json={"reason": "Which street is it on?"},
            headers=admin,
        )

        (note,) = http.get(NOTES, headers=api.token(owner)).json()["items"]

        assert (note["type"], note["link"]) == ("PN-13", "/pharmacy")
        assert note["title"].startswith("We need more information")
        assert note["lines"] == ["From DawaLink's team: Which street is it on?"]
