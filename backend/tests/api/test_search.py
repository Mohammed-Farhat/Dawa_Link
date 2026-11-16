"""The search page over HTTP: the catalog, the listings, reserving (docs/06 §6.2, §6.3;
docs/04 R-S1 to R-S5, R-F1, R-F3, R-AG5, O1; docs/09 FR-2; C15: no part of it needs the
assistant)."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dawalink.api.limits import Limiter
from tests.api.conftest import Api, code_of
from tests.db.factories import TODAY


@dataclass
class Shop:
    api: Api
    http: TestClient
    client: uuid.UUID
    headers: dict[str, str]
    augmentin: uuid.UUID
    near: uuid.UUID  # a pharmacy in the client's district
    box: uuid.UUID  # its box of Augmentin, 60 days from expiry

    def search(self, **more: Any) -> Any:
        body = {"product_id": str(self.augmentin)} | more
        return self.http.post("/api/v1/listings/search", json=body, headers=self.headers)

    def reserve(self, key: str = "tap-1", **more: Any) -> Any:
        listing = self.search().json()["items"][0]
        body = {
            "listing_id": listing["id"],
            "qty": 1,
            "expected_price_lbp": listing["price"]["lbp"],
            "pickup_day": listing["pickup_days_allowed"][0],
        } | more
        return self.http.post(
            "/api/v1/reservations", json=body, headers=self.headers | {"Idempotency-Key": key}
        )


@pytest.fixture
def shop(api: Api) -> Shop:
    """One client, one medicine, one pharmacy with a box of it. **The assistant is
    switched off** for every test here: search and reserving never need it."""
    make = api.world.make
    client = api.client()
    augmentin = make.product(
        moph_name="AUGMENTIN 1G",
        search_name="augmentin 1g",
        public_price_lbp=1_000_000,
        equivalence_key="amoxicillin-clavulanate|1g|tablet",
    )
    near = make.pharmacy(name="Hamra Pharmacy", lat=33.897, lon=35.484)
    return Shop(
        api,
        api.http(assistant=False),
        client,
        api.token(client),
        augmentin,
        near,
        make.item(pharmacy_id=near, product_id=augmentin, days_left=60, qty_on_hand=8),
    )


class TestTheCatalog:
    def test_a_medicine_is_found_by_a_misspelled_name(self, shop: Shop) -> None:
        found = shop.http.get(
            "/api/v1/catalog/products", params={"q": "ogmentin"}, headers=shop.headers
        ).json()

        assert [item["name"] for item in found["items"]] == ["AUGMENTIN 1G"]
        assert found["items"][0]["public_price"]["lbp"] == 1_000_000
        assert found["items"][0]["prescription_required"] is True

    def test_a_controlled_medicine_is_never_found_or_shown(self, shop: Shop) -> None:
        hidden = shop.api.world.make.product(
            moph_name="TRAMAL 50MG", search_name="tramal 50mg", controlled=True
        )

        found = shop.http.get(
            "/api/v1/catalog/products", params={"q": "tramal"}, headers=shop.headers
        ).json()
        direct = shop.http.get(f"/api/v1/catalog/products/{hidden}", headers=shop.headers)
        searched = shop.search(product_id=str(hidden))

        assert found["items"] == []
        assert (direct.status_code, code_of(direct)) == (404, "NOT_FOUND")
        assert code_of(searched) == "PRODUCT_NOT_ALLOWED"

    def test_a_medicines_page_says_what_is_printed_on_the_box(self, shop: Shop) -> None:
        detail = shop.http.get(
            f"/api/v1/catalog/products/{shop.augmentin}", headers=shop.headers
        ).json()

        assert detail["name"] == "AUGMENTIN 1G"
        assert set(detail) >= {"ingredients", "atc_code", "manufacturer", "pack", "form"}


class TestSearching:
    def test_a_box_is_shown_with_what_it_saves_and_how_far_it_is(self, shop: Shop) -> None:
        result = shop.search().json()

        (listing,) = result["items"]
        assert result["product"]["name"] == "AUGMENTIN 1G"
        assert listing["pharmacy"]["name"] == "Hamra Pharmacy"
        assert listing["price"]["lbp"] < 1_000_000
        assert listing["saving"]["lbp"] == 1_000_000 - listing["price"]["lbp"]
        assert listing["days_left"] == 60
        # Shown exactly up to 5, then "5+" (R-S5): the pharmacy holds 8.
        assert (listing["available"], listing["more_available"]) == (5, True)
        assert listing["travel"]["car_min"] >= 0
        # Nobody said for how long: no promise, only a warning on the page (R-F2).
        assert listing["fits"] is None
        assert result["location"] == {"source": "profile", "label": "Beirut"}
        assert len(result["upcoming_days"]) >= 3

    def test_search_shows_only_what_was_searched_never_another_brand(self, shop: Shop) -> None:
        """R-S4: another brand of the same medicine is only ever shown by the assistant."""
        clavox = shop.api.world.make.product(
            moph_name="CLAVOX 1G",
            search_name="clavox 1g",
            equivalence_key="amoxicillin-clavulanate|1g|tablet",
        )
        shop.api.world.make.item(pharmacy_id=shop.near, product_id=clavox)

        result = shop.search().json()

        assert [item["product"]["name"] for item in result["items"]] == ["AUGMENTIN 1G"]

    def test_a_box_that_doesnt_last_the_days_of_use_is_left_out(self, shop: Shop) -> None:
        fits = shop.search(days_of_use=30).json()
        too_long = shop.search(days_of_use=90).json()

        assert [item["fits"] for item in fits["items"]] == [True]
        assert too_long["items"] == []
        assert too_long["no_match"]["latest_expiry"] == str(TODAY + timedelta(days=60))

    def test_the_cheapest_first_when_asked(self, shop: Shop) -> None:
        far = shop.api.world.make.pharmacy(name="Far Pharmacy", lat=33.95, lon=35.60)
        # Closer to its expiry, so cheaper (N-4).
        shop.api.world.make.item(pharmacy_id=far, product_id=shop.augmentin, days_left=20)

        nearest = shop.search(sort="nearest").json()
        cheapest = shop.search(sort="cheapest").json()

        assert nearest["items"][0]["pharmacy"]["name"] == "Hamra Pharmacy"
        assert cheapest["items"][0]["pharmacy"]["name"] == "Far Pharmacy"
        assert cheapest["total_found"] == 2

    def test_the_clients_place_goes_in_the_body_and_never_comes_back(self, shop: Shop) -> None:
        answer = shop.search(location={"lat": 33.89612345, "lon": 35.48321987})

        assert answer.status_code == 200
        assert answer.json()["location"] == {"source": "shared", "label": "Your location"}
        # Not the point, not even rounded. (The pharmacy's own pin is public.)
        assert "33.896" not in answer.text
        assert "35.483" not in answer.text

    def test_a_district_can_be_chosen_instead(self, shop: Shop) -> None:
        answer = shop.search(location={"district_id": 2}).json()
        nowhere = shop.search(location={"district_id": 999})

        assert answer["location"]["source"] == "district"
        assert code_of(nowhere) == "VALIDATION_ERROR"

    def test_new_points_may_be_sent_only_so_often(self, shop: Shop) -> None:
        shop.http.app.state.locations_per_client = Limiter(1, 3600)  # type: ignore[attr-defined]
        here = {"lat": 33.896, "lon": 35.483}

        first = shop.search(location=here)
        same_place = shop.search(location=here)
        elsewhere = shop.search(location={"lat": 33.95, "lon": 35.60})

        assert (first.status_code, same_place.status_code) == (200, 200)
        assert (elsewhere.status_code, code_of(elsewhere)) == (429, "RATE_LIMITED")

    def test_an_unverified_client_may_search_but_not_reserve(self, api: Api, shop: Shop) -> None:
        headers = api.token(api.client("UNVERIFIED"))
        body = {"product_id": str(shop.augmentin)}

        found = shop.http.post("/api/v1/listings/search", json=body, headers=headers)
        listing = found.json()["items"][0]
        refused = shop.http.post(
            "/api/v1/reservations",
            json={
                "listing_id": listing["id"],
                "qty": 1,
                "expected_price_lbp": listing["price"]["lbp"],
                "pickup_day": listing["pickup_days_allowed"][0],
            },
            headers=headers | {"Idempotency-Key": "x"},
        )

        assert found.status_code == 200
        assert (refused.status_code, code_of(refused)) == (403, "EMAIL_NOT_VERIFIED")


class TestOneOffer:
    def test_the_offers_page_has_the_pharmacys_week(self, shop: Shop) -> None:
        detail = shop.http.post(
            f"/api/v1/listings/{shop.box}/view", json={"days_of_use": 90}, headers=shop.headers
        ).json()

        assert detail["listing"]["id"] == str(shop.box)
        # Shown although it doesn't last 90 days: the page says so (R-F4).
        assert detail["listing"]["fits"] is False
        assert detail["listing"]["pickup_days_allowed"] == []
        assert len(detail["week"]) == 7
        assert detail["week"][0]["hours"] == "08:00-21:00"

    def test_an_offer_that_is_gone_is_not_found(self, shop: Shop) -> None:
        with shop.api.world.as_owner():
            shop.api.world.connection.exec_driver_sql("UPDATE inventory_items SET qty_on_hand = 0")

        gone = shop.http.post(f"/api/v1/listings/{shop.box}/view", json={}, headers=shop.headers)

        assert (gone.status_code, code_of(gone)) == (404, "NOT_FOUND")


class TestReservingFromSearch:
    def test_the_box_is_reserved_at_once(self, shop: Shop) -> None:
        answer = shop.reserve()

        assert answer.status_code == 201
        reserved = answer.json()
        assert (reserved["state"], reserved["source"]) == ("RESERVED", "search")
        assert reserved["ref"].startswith("R-")
        assert reserved["status_text"].startswith("Reserved: pick up by ")
        ticket = shop.http.get(f"/api/v1/reservations/{reserved['id']}", headers=shop.headers)
        assert ticket.json()["ref"] == reserved["ref"]

    def test_the_agent_is_never_told_about_a_search_reservation(self, shop: Shop) -> None:
        """R-AG5: the search page stays agent-free, even while the client has a chat open."""
        chat = shop.api.world.make.conversation(client_id=shop.client)

        shop.reserve()

        assert shop.api.world.all("SELECT 1 FROM chat_messages") == []
        assert shop.api.world.one(
            "SELECT pending_turn_at FROM conversations WHERE id = :id", id=chat
        ) == (None,)
        assert shop.api.world.all("SELECT 1 FROM agent_runs") == []

    def test_a_double_tap_reserves_one_box(self, shop: Shop) -> None:
        first = shop.reserve("the-same-tap")
        again = shop.reserve("the-same-tap")
        another = shop.reserve("another-tap")

        assert (first.status_code, again.status_code) == (201, 201)
        assert again.json()["id"] == first.json()["id"]
        assert another.json()["id"] != first.json()["id"]
        assert shop.api.world.one("SELECT count(*), sum(qty_locked) FROM orders") == (2, 2)

    def test_a_tap_needs_its_key(self, shop: Shop) -> None:
        listing = shop.search().json()["items"][0]

        answer = shop.http.post(
            "/api/v1/reservations",
            json={
                "listing_id": listing["id"],
                "qty": 1,
                "expected_price_lbp": listing["price"]["lbp"],
                "pickup_day": listing["pickup_days_allowed"][0],
            },
            headers=shop.headers,
        )

        assert (answer.status_code, code_of(answer)) == (400, "IDEMPOTENCY_KEY_REQUIRED")

    def test_nothing_is_reserved_at_a_price_higher_than_shown(self, shop: Shop) -> None:
        answer = shop.reserve(expected_price_lbp=1)

        assert (answer.status_code, code_of(answer)) == (409, "PRICE_CHANGED")
        assert shop.api.world.all("SELECT 1 FROM orders") == []

    def test_a_box_that_wont_last_is_refused(self, shop: Shop) -> None:
        answer = shop.reserve(days_of_use=90)

        assert (answer.status_code, code_of(answer)) == (409, "DOES_NOT_FIT")

    def test_a_pickup_day_the_pharmacy_doesnt_allow_is_refused(self, shop: Shop) -> None:
        answer = shop.reserve(pickup_day=str(TODAY + timedelta(days=9)))

        assert (answer.status_code, code_of(answer)) == (422, "PICKUP_DAY_INVALID")

    def test_more_packs_than_the_limit_are_refused_by_the_form(self, shop: Shop) -> None:
        answer = shop.reserve(qty=4)

        assert code_of(answer) == "VALIDATION_ERROR"
