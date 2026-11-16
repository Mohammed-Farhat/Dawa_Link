"""Sourcing requests, offers and the demo clock over HTTP (docs/06 §6.3, §6.5, §6.10;
docs/04 SM-8, R-RQ9, O9, O10, R-DEMO; docs/09 FS-16)."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dawalink.services import requests
from dawalink.services.requests import RequestLine
from tests.agent.conftest import HAMRA
from tests.api.conftest import Api, code_of
from tests.db.factories import TODAY

KEY = {"Idempotency-Key": "a-tap"}


@dataclass
class Sourcing:
    api: Api
    http: TestClient
    client: uuid.UUID
    headers: dict[str, str]
    pharmacy: uuid.UUID
    augmentin: uuid.UUID
    concor: uuid.UUID
    request: uuid.UUID

    def get(self, path: str, **params: Any) -> Any:
        return self.http.get(f"/api/v1{path}", params=params, headers=self.headers)

    def post(self, path: str, body: dict[str, Any] | None = None, **headers: str) -> Any:
        return self.http.post(f"/api/v1{path}", json=body or {}, headers=self.headers | headers)

    def offer_arrives(self) -> str:
        """The agent waits for Concor; then a pharmacy lists a box of it: an offer."""
        world = self.api.world
        (item,) = world.one(
            "SELECT id FROM request_items WHERE request_id = :r AND product_id = :p",
            r=self.request,
            p=self.concor,
        )
        tx = world.tx()
        requests.open_claim(tx, item)
        world.settle(tx)
        world.make.item(pharmacy_id=self.pharmacy, product_id=self.concor, days_left=60)
        world.clock_tasks().matching_sweep()
        (offer,) = self.get("/offers").json()["items"]
        return str(offer["id"])


@pytest.fixture
def sourcing(api: Api) -> Sourcing:
    """A client with an open request for two medicines, none of them listed yet."""
    make = api.world.make
    client = api.client()
    augmentin = make.product(moph_name="AUGMENTIN 1G", search_name="augmentin 1g")
    concor = make.product(moph_name="CONCOR 5MG", search_name="concor 5mg")
    tx = api.world.tx()
    request = requests.create_request(
        tx,
        client_id=client,
        lines=(RequestLine(augmentin, qty=2), RequestLine(concor)),
        location=HAMRA,
        alternatives_ok=False,
        idempotency_key=f"start-{uuid.uuid4()}",
    )
    api.world.settle(tx)
    return Sourcing(
        api,
        api.http(assistant=False),
        client,
        api.token(client),
        make.pharmacy(name="Hamra Pharmacy", lat=33.897, lon=35.484),
        augmentin,
        concor,
        request.id,
    )


class TestARequestsPage:
    def test_it_says_in_words_what_is_happening_to_each_medicine(self, sourcing: Sourcing) -> None:
        page = sourcing.get(f"/requests/{sourcing.request}").json()

        assert page["ref"].startswith("Q-")
        assert (page["state"], page["outcome"]) == ("OPEN", None)
        assert [item["product"]["name"] for item in page["items"]] == ["AUGMENTIN 1G", "CONCOR 5MG"]
        assert [item["status_text"] for item in page["items"]] == ["Searching", "Searching"]
        assert (page["units_wanted"], page["units_secured"]) == (3, 0)
        # Its thread is a conversation like the chat: the same messages endpoint reads it.
        thread = sourcing.get(f"/conversations/{page['conversation_id']}/messages").json()
        assert (thread["kind"], thread["request_id"]) == ("request", str(sourcing.request))

    def test_the_open_requests_are_listed(self, sourcing: Sourcing) -> None:
        opened = sourcing.get("/requests").json()["items"]
        closed = sourcing.get("/requests", state="closed").json()["items"]

        assert [row["id"] for row in opened] == [str(sourcing.request)]
        assert closed == []

    def test_a_message_in_the_thread_is_answered_later_by_the_worker(
        self, sourcing: Sourcing
    ) -> None:
        thread = sourcing.get(f"/requests/{sourcing.request}").json()["conversation_id"]

        answer = sourcing.post(
            f"/conversations/{thread}/messages",
            {"text": "any news?", "client_message_id": str(uuid.uuid4())},
        )

        # Not a stream: the worker runs the turn, and the page sees the reply by polling.
        assert (answer.status_code, set(answer.json())) == (202, {"message_seq"})

    def test_the_client_stops_the_search_once(self, sourcing: Sourcing) -> None:
        stopped = sourcing.post(f"/requests/{sourcing.request}/cancel")
        again = sourcing.post(f"/requests/{sourcing.request}/cancel")

        assert (stopped.json()["state"], stopped.json()["outcome"]) == ("CLOSED", "CANCELLED")
        assert [item["status_text"] for item in stopped.json()["items"]] == ["Stopped"] * 2
        assert (again.status_code, code_of(again)) == (409, "REQUEST_CLOSED")

    def test_someone_elses_request_does_not_exist(self, sourcing: Sourcing) -> None:
        other = sourcing.api.token(sourcing.api.client())

        answers = [
            sourcing.http.get(f"/api/v1/requests/{sourcing.request}", headers=other),
            sourcing.http.post(f"/api/v1/requests/{sourcing.request}/cancel", headers=other),
        ]

        assert [(a.status_code, code_of(a)) for a in answers] == [(404, "NOT_FOUND")] * 2
        assert sourcing.http.get("/api/v1/requests", headers=other).json()["items"] == []


class TestAnOffer:
    def test_new_stock_becomes_an_offer_the_client_can_accept(self, sourcing: Sourcing) -> None:
        offer = sourcing.offer_arrives()

        (shown,) = sourcing.get("/offers").json()["items"]
        waiting = sourcing.get(f"/requests/{sourcing.request}").json()["items"][1]["waiting"]
        accepted = sourcing.post(f"/offers/{offer}/accept", {"pickup_day": str(TODAY)}, **KEY)

        assert (shown["kind"], shown["product"]["name"]) == ("matching", "CONCOR 5MG")
        # The pharmacy is named now that it holds a box for this client (INV-8).
        assert shown["pharmacy"]["name"] == "Hamra Pharmacy"
        assert shown["pickup_days_allowed"][0] == str(TODAY)
        assert shown["request_id"] == str(sourcing.request)
        assert waiting["open_offer_ids"] == [offer]
        assert (accepted.status_code, accepted.json()["state"]) == (201, "RESERVED")
        assert accepted.json()["request_id"] == str(sourcing.request)
        item = sourcing.get(f"/requests/{sourcing.request}").json()["items"][1]
        assert (item["state"], item["status_text"]) == ("SECURED", "Reserved")
        assert [held["ref"] for held in item["reservations"]] == [accepted.json()["ref"]]
        assert sourcing.get("/offers").json()["items"] == []

    def test_an_offer_is_accepted_once_and_needs_its_key(self, sourcing: Sourcing) -> None:
        offer = sourcing.offer_arrives()
        body = {"pickup_day": str(TODAY)}

        no_key = sourcing.post(f"/offers/{offer}/accept", body)
        sourcing.post(f"/offers/{offer}/accept", body, **KEY)
        twice = sourcing.post(f"/offers/{offer}/accept", body, **KEY)

        assert code_of(no_key) == "IDEMPOTENCY_KEY_REQUIRED"
        assert (twice.status_code, code_of(twice)) == (409, "OFFER_NOT_OPEN")

    def test_no_thanks_gives_the_box_back(self, sourcing: Sourcing) -> None:
        offer = sourcing.offer_arrives()

        declined = sourcing.post(f"/offers/{offer}/decline")
        again = sourcing.post(f"/offers/{offer}/decline")

        assert declined.status_code == 204
        assert sourcing.get("/offers").json()["items"] == []
        assert (again.status_code, code_of(again)) == (409, "OFFER_NOT_OPEN")

    def test_someone_elses_offer_does_not_exist(self, sourcing: Sourcing) -> None:
        offer = sourcing.offer_arrives()
        other = sourcing.api.token(sourcing.api.client())

        answers = [
            sourcing.http.post(
                f"/api/v1/offers/{offer}/accept",
                json={"pickup_day": str(TODAY)},
                headers=other | KEY,
            ),
            sourcing.http.post(f"/api/v1/offers/{offer}/decline", headers=other),
        ]

        assert [(a.status_code, code_of(a)) for a in answers] == [(404, "NOT_FOUND")] * 2
        assert sourcing.http.get("/api/v1/offers", headers=other).json()["items"] == []


class TestTheDemoClock:
    def admin(self, api: Api) -> dict[str, str]:
        return api.token(api.world.make.user("admin", totp_secret=b"not-a-real-secret"))

    def test_only_an_admin_moves_it_and_only_in_demo_mode(self, sourcing: Sourcing) -> None:
        admin = self.admin(sourcing.api)

        as_client = sourcing.post("/admin/demo-clock/advance", {"minutes": 30})
        off = sourcing.http.post(
            "/api/v1/admin/demo-clock/advance", json={"minutes": 30}, headers=admin
        )

        assert (as_client.status_code, code_of(as_client)) == (403, "FORBIDDEN")
        # This app runs with demo mode off: the clock doesn't exist (docs/09 FS-16).
        assert (off.status_code, code_of(off)) == (404, "DEMO_MODE_OFF")
        assert (
            sourcing.http.get("/api/v1/admin/demo-clock", headers=admin).json()["demo_mode"]
            is False
        )

    def test_a_move_is_audited_with_its_admin(self, api: Api) -> None:
        http = api.http(assistant=False, demo_mode=True)
        admin = self.admin(api)

        moved = http.post(
            "/api/v1/admin/demo-clock/advance",
            json={"minutes": 120, "reason": "showing an offer expiring"},
            headers=admin,
        )
        backwards = http.post(
            "/api/v1/admin/demo-clock/advance", json={"minutes": -5}, headers=admin
        )

        assert (moved.status_code, moved.json()["offset_minutes"]) == (200, 120)
        assert code_of(backwards) == "VALIDATION_ERROR"
        assert api.world.one(
            "SELECT actor_type, reason FROM audit_events WHERE action = 'clock.advance'"
        ) == ("ADMIN", "showing an offer expiring")
        # Logins are counted in real time: the admin who moved the clock is still in.
        assert http.get("/api/v1/auth/me", headers=admin).status_code == 200
