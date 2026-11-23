"""Numbered pages on the pharmacy's lists and the client's: each answer says how many rows
its choices match (`total`), the same on every page, so that the website can draw
"Page 2 of 2 · 26 in all" (docs/06 §1; the owner, 2026-11-23).

The lists: the pharmacy's stock (Inventory and Listings) and its reservations, the
client's reservations, and the notifications of both.
"""

import uuid
from typing import Any

import pytest

from dawalink.services.notify import Template, notify
from tests.api.conftest import Api
from tests.api.test_pharmacy import login_of
from tests.db.factories import NOW

ROWS = 26
PAGE = 25
NOTES = "/api/v1/notifications"


def _page(api: Api, path: str, headers: dict[str, str], **params: Any) -> Any:
    answer = api.http(assistant=False).get(path, params=params, headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


class TestThePharmacysStock:
    @pytest.fixture
    def shop(self, api: Api) -> tuple[uuid.UUID, dict[str, str], uuid.UUID]:
        make = api.world.make
        pharmacy = make.pharmacy(name="Hamra Pharmacy")
        product = make.product(moph_name="PANADOL", search_name="panadol", dosage_text="500mg")
        return pharmacy, login_of(api, pharmacy), product

    def test_page_two_has_the_last_box_and_both_pages_say_26(
        self, api: Api, shop: tuple[uuid.UUID, dict[str, str], uuid.UUID]
    ) -> None:
        pharmacy, login, product = shop
        for number in range(ROWS):
            api.world.make.item(pharmacy_id=pharmacy, product_id=product, days_left=10 + number)

        first = _page(api, "/api/v1/pharmacy/inventory", login, limit=PAGE)
        second = _page(api, "/api/v1/pharmacy/inventory", login, limit=PAGE, cursor=PAGE)

        assert (len(first["items"]), first["total"], first["next_cursor"]) == (PAGE, ROWS, "25")
        assert (len(second["items"]), second["total"], second["next_cursor"]) == (1, ROWS, None)

    def test_the_total_counts_what_the_choices_keep(
        self, api: Api, shop: tuple[uuid.UUID, dict[str, str], uuid.UUID]
    ) -> None:
        pharmacy, login, product = shop
        other = api.world.make.product(moph_name="CONCOR", search_name="concor")
        api.world.make.item(pharmacy_id=pharmacy, product_id=product, days_left=20)
        api.world.make.item(pharmacy_id=pharmacy, product_id=product, days_left=200)
        api.world.make.item(pharmacy_id=pharmacy, product_id=other, days_left=30)
        # Someone else's box is never counted.
        api.world.make.item(product_id=product, days_left=20)

        everything = _page(api, "/api/v1/pharmacy/inventory", login)
        near = _page(api, "/api/v1/pharmacy/inventory", login, zone="NEAR_EXPIRY")
        named = _page(api, "/api/v1/pharmacy/inventory", login, q="panad")
        past_the_end = _page(api, "/api/v1/pharmacy/inventory", login, cursor=40)

        assert everything["total"] == 3
        assert (len(near["items"]), near["total"]) == (2, 2)
        assert (len(named["items"]), named["total"]) == (2, 2)
        # An empty page still says how many there are: the website moves to the last page.
        assert (past_the_end["items"], past_the_end["total"]) == ([], 3)

    def test_by_medicine_puts_the_boxes_of_one_medicine_side_by_side(
        self, api: Api, shop: tuple[uuid.UUID, dict[str, str], uuid.UUID]
    ) -> None:
        """Two batches of one medicine, each with its own expiry: by expiry another
        medicine comes between them, by medicine they are next to each other, the
        soonest first."""
        pharmacy, login, product = shop
        other = api.world.make.product(moph_name="ASPIRIN", search_name="aspirin")
        make = api.world.make
        make.item(pharmacy_id=pharmacy, product_id=product, batch="P-SOON", days_left=20)
        make.item(pharmacy_id=pharmacy, product_id=other, batch="A-MID", days_left=40)
        make.item(pharmacy_id=pharmacy, product_id=product, batch="P-LATE", days_left=90)

        by_expiry = _page(api, "/api/v1/pharmacy/inventory", login)
        by_medicine = _page(api, "/api/v1/pharmacy/inventory", login, sort="medicine")

        assert [box["batch"] for box in by_expiry["items"]] == ["P-SOON", "A-MID", "P-LATE"]
        assert [box["batch"] for box in by_medicine["items"]] == ["A-MID", "P-SOON", "P-LATE"]
        assert by_medicine["total"] == 3

    def test_another_order_is_refused(
        self, api: Api, shop: tuple[uuid.UUID, dict[str, str], uuid.UUID]
    ) -> None:
        _, login, _ = shop
        answer = api.http(assistant=False).get(
            "/api/v1/pharmacy/inventory", params={"sort": "price"}, headers=login
        )
        assert answer.status_code == 422


@pytest.mark.rows_by_hand  # orders with no stock behind them
class TestThePharmacysReservations:
    def test_both_views_are_counted_and_paged(self, api: Api) -> None:
        make = api.world.make
        pharmacy = make.pharmacy(name="Hamra Pharmacy")
        login = login_of(api, pharmacy)
        client = api.client()
        for _ in range(ROWS):
            make.order(pharmacy_id=pharmacy, client_id=client)
        make.order("PICKED_UP", pharmacy_id=pharmacy, client_id=client, closed_at=NOW)
        # Another pharmacy's reservation is never counted.
        make.order(client_id=client)

        first = _page(api, "/api/v1/pharmacy/reservations", login, limit=PAGE)
        second = _page(api, "/api/v1/pharmacy/reservations", login, limit=PAGE, cursor=PAGE)
        before = _page(api, "/api/v1/pharmacy/reservations", login, view="history")

        assert (len(first["items"]), first["total"]) == (PAGE, ROWS)
        assert (len(second["items"]), second["total"], second["next_cursor"]) == (1, ROWS, None)
        assert (len(before["items"]), before["total"]) == (1, 1)

    def test_an_order_number_typed_at_the_counter_counts_what_it_finds(self, api: Api) -> None:
        make = api.world.make
        pharmacy = make.pharmacy(name="Hamra Pharmacy")
        login = login_of(api, pharmacy)
        order = make.order(pharmacy_id=pharmacy, client_id=api.client())
        (ref,) = api.world.one("SELECT ref FROM orders WHERE id = :id", id=order)

        found = _page(api, "/api/v1/pharmacy/reservations", login, q=ref)
        unknown = _page(api, "/api/v1/pharmacy/reservations", login, q="R-ZZZZZZ")

        assert (len(found["items"]), found["total"]) == (1, 1)
        assert (unknown["items"], unknown["total"]) == ([], 0)


@pytest.mark.rows_by_hand  # orders with no stock behind them
class TestTheClientsReservations:
    def test_the_history_is_counted_and_paged(self, api: Api) -> None:
        client = api.client()
        login = api.token(client)
        for _ in range(ROWS):
            api.world.make.order("PICKED_UP", client_id=client, closed_at=NOW)
        api.world.make.order(client_id=client)
        # Someone else's reservations are never counted.
        api.world.make.order("PICKED_UP", closed_at=NOW)

        first = _page(api, "/api/v1/reservations", login, view="history", limit=PAGE)
        second = _page(api, "/api/v1/reservations", login, view="history", cursor=PAGE)
        active = _page(api, "/api/v1/reservations", login)

        assert (len(first["items"]), first["total"]) == (PAGE, ROWS)
        assert (len(second["items"]), second["total"], second["next_cursor"]) == (1, ROWS, None)
        assert (len(active["items"]), active["total"]) == (1, 1)


class TestTheNotifications:
    @pytest.fixture
    def reader(self, api: Api) -> tuple[uuid.UUID, dict[str, str]]:
        client = api.client()
        tx = api.world.tx()
        for number in range(ROWS):
            notify(
                tx,
                client,
                Template.CANCELLED_BY_SYSTEM,
                {"order_ref": f"R-TEST{number:02d}"},
                event=f"order:{uuid.uuid4()}",
                email=False,
            )
        # Someone else's are never counted.
        notify(tx, api.client(), Template.CANCELLED_BY_SYSTEM, {}, event="order:x", email=False)
        api.world.settle(tx)
        return client, api.token(client)

    def test_an_offset_reaches_page_two_and_every_page_says_26(
        self, api: Api, reader: tuple[uuid.UUID, dict[str, str]]
    ) -> None:
        _, login = reader
        first = _page(api, NOTES, login, limit=PAGE)
        second = _page(api, NOTES, login, limit=PAGE, offset=PAGE)

        assert (len(first["items"]), first["total"]) == (PAGE, ROWS)
        assert (len(second["items"]), second["total"], second["next_cursor"]) == (1, ROWS, None)
        # Page 2 goes on where page 1 stopped: the oldest one, nothing twice.
        ids = [row["id"] for row in first["items"] + second["items"]]
        assert ids == sorted(ids, reverse=True)
        assert len(set(ids)) == ROWS

    def test_the_total_ignores_the_last_id_seen(
        self, api: Api, reader: tuple[uuid.UUID, dict[str, str]]
    ) -> None:
        """`cursor` (the last ID seen) still works as before, and `offset` skips within
        what it leaves; `total` is all of them either way."""
        _, login = reader
        first = _page(api, NOTES, login, limit=10)
        after = _page(api, NOTES, login, limit=10, cursor=first["next_cursor"], offset=5)

        assert after["total"] == ROWS
        assert after["items"][0]["id"] == first["items"][-1]["id"] - 6

    @pytest.mark.parametrize("offset", ["-1", str(10**40), "soon"])
    def test_an_offset_out_of_bounds_is_refused(
        self, api: Api, reader: tuple[uuid.UUID, dict[str, str]], offset: str
    ) -> None:
        _, login = reader
        answer = api.http(assistant=False).get(NOTES, params={"offset": offset}, headers=login)
        assert answer.status_code == 422
