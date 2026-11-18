"""The admin's console, second half (docs/03 AS-4, AS-5, AS-7, AS-9, AS-10; slice 7f):
suspending a pharmacy or a client with everything that follows, a client's contact
details, the no-show contest, abuse flags, the catalog and the health numbers.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from dawalink.domain.clock import beirut_date
from dawalink.domain.orders import OrderSource
from dawalink.services import daily, orders
from dawalink.services.orders import ReserveLine
from tests.api.conftest import PASSWORD, Api, code_of

ADMIN = "/api/v1/admin"
PERSON = {"full_name": "Rana Khoury", "email": "rana@example.com", "phone": "+96170123456"}


@pytest.fixture
def admin(api: Api) -> dict[str, str]:
    return api.token(api.world.make.user("admin", totp_secret=b"not-a-real-secret"))


@dataclass
class Shop:
    """A pharmacy with one listed box, and a client who can reserve it."""

    api: Api
    pharmacy: uuid.UUID
    product: uuid.UUID
    box: uuid.UUID
    client: uuid.UUID

    @property
    def pharmacist(self) -> dict[str, str]:
        (owner,) = self.api.world.one(
            "SELECT owner_user_id FROM pharmacies WHERE id = :id", id=self.pharmacy
        )
        return self.api.token(owner)

    @property
    def today(self) -> date:
        """The day on the test's clock: a test may move it forward."""
        return beirut_date(self.api.world.clock.now())

    def reserve(self, qty: int = 1) -> Any:
        tx = self.api.world.tx()
        price = self.api.world.one(
            "SELECT price_lbp FROM visible_listings(:today) WHERE inventory_item_id = :id",
            today=self.today,
            id=self.box,
        )[0]
        (made,) = orders.reserve(
            tx,
            client_id=self.client,
            lines=[ReserveLine(self.box, qty, price)],
            pickup_day=self.today,
            source=OrderSource.SEARCH,
            idempotency_key=f"test-{uuid.uuid4()}",
        )
        self.api.world.settle(tx)
        return made

    def no_show(self) -> Any:
        """A reservation nobody collected: it expires and counts as a no-show."""
        made = self.reserve()
        self.api.world.later(days=2)
        tx = self.api.world.tx()
        orders.expire_no_show(tx, made.id)
        self.api.world.settle(tx)
        return made

    def visible(self) -> int:
        return self.api.world.one(  # type: ignore[no-any-return]
            "SELECT count(*) FROM visible_listings(:today) WHERE pharmacy_id = :id",
            today=self.today,
            id=self.pharmacy,
        )[0]

    def state_of(self, order_id: uuid.UUID) -> str:
        return self.api.world.one("SELECT state FROM orders WHERE id = :id", id=order_id)[0]  # type: ignore[no-any-return]


@pytest.fixture
def shop(api: Api) -> Shop:
    make = api.world.make
    owner = make.user("pharmacist", email_verified_at=api.world.clock.now())
    pharmacy = make.pharmacy(owner_user_id=owner, name="Hamra Pharmacy")
    product = make.product(moph_name="AUGMENTIN 1G", search_name="augmentin 1g")
    return Shop(
        api,
        pharmacy,
        product,
        make.item(pharmacy_id=pharmacy, product_id=product, days_left=60, qty_on_hand=5),
        api.client(**PERSON),
    )


class TestAPharmacysActivity:
    def test_the_admin_sees_its_listings_its_last_stock_change_and_what_was_not_available(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        """AS-4; docs/10 RR-2, RR-11: a pharmacy that lists boxes it doesn't have shows
        up as a high share of [Not available]."""
        http = api.http()
        counter = "/api/v1/pharmacy/reservations"
        edited = api.world.clock.now() - timedelta(days=2)
        # A box it keeps private, edited two days ago: not one of the listings.
        api.world.make.item(pharmacy_id=shop.pharmacy, days_left=250, last_edited_at=edited)
        handed, missing, _still_waiting = shop.reserve(), shop.reserve(), shop.reserve()
        http.post(f"{counter}/{handed.id}/picked-up", json={}, headers=shop.pharmacist)
        http.post(
            f"{counter}/{missing.id}/not-available", json={"units": 1}, headers=shop.pharmacist
        )

        seen = http.get(f"{ADMIN}/pharmacies/{shop.pharmacy}", headers=admin).json()

        assert seen["live_listings"] == 1
        assert seen["last_inventory_update"] == edited.isoformat().replace("+00:00", "Z")
        # The reservation that is still open counts for neither.
        assert (seen["handed_over_30d"], seen["not_available_30d"]) == (1, 1)


class TestSuspendingAPharmacy:
    def test_its_listings_hide_its_asks_end_and_what_is_reserved_is_kept(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        """SM-1: a suspended pharmacy can't be found or asked, but a client who already
        reserved a box there can still collect it."""
        http = api.http()
        reserved = shop.reserve()
        ask = api.world.make.early_release_ask(pharmacy_id=shop.pharmacy)
        base = f"{ADMIN}/pharmacies/{shop.pharmacy}"

        silent = http.post(f"{base}/suspend", json={}, headers=admin)
        suspended = http.post(
            f"{base}/suspend", json={"reason": "Sold expired stock."}, headers=admin
        )
        twice = http.post(f"{base}/suspend", json={"reason": "Again."}, headers=admin)

        assert (silent.status_code, code_of(silent)) == (422, "REASON_REQUIRED")
        assert suspended.json()["status"] == "SUSPENDED"
        assert (twice.status_code, code_of(twice)) == (409, "CHANGED_SINCE")
        assert shop.visible() == 0
        assert shop.state_of(reserved.id) == "RESERVED"
        assert api.world.one("SELECT state FROM early_release_asks WHERE id = :id", id=ask)[0] == (
            "WITHDRAWN"
        )
        # The pharmacy can still hand over what is reserved, and nothing else.
        picked = http.post(
            f"/api/v1/pharmacy/reservations/{reserved.id}/picked-up",
            json={},
            headers=shop.pharmacist,
        )
        stock = http.get("/api/v1/pharmacy/inventory", headers=shop.pharmacist)
        assert picked.status_code == 200
        assert (stock.status_code, code_of(stock)) == (403, "PHARMACY_NOT_APPROVED")
        (email,) = [body for _, subject, body in api.emails() if "is suspended" in subject]
        assert "Sold expired stock." in email
        (event,) = [
            row
            for row in api.world.all(
                "SELECT action, after, reason FROM audit_events WHERE entity_id = :id",
                id=shop.pharmacy,
            )
            if row.action == "pharmacy.suspend"
        ]
        assert event.after == {"status": "SUSPENDED", "offers_cancelled": 0, "asks_withdrawn": 1}

    @pytest.mark.rows_by_hand
    def test_an_offer_on_one_of_its_boxes_is_cancelled(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        held = api.world.make.item(
            pharmacy_id=shop.pharmacy, product_id=shop.product, days_left=200, qty_reserved=1
        )
        offer = api.world.make.order(
            "OFFERED",
            client_id=shop.client,
            pharmacy_id=shop.pharmacy,
            product_id=shop.product,
            inventory_item_id=held,
            source="early_release",
        )

        http.post(
            f"{ADMIN}/pharmacies/{shop.pharmacy}/suspend", json={"reason": "why"}, headers=admin
        )

        assert shop.state_of(offer) == "CANCELLED_BY_SYSTEM"
        assert (
            api.world.one("SELECT qty_reserved FROM inventory_items WHERE id = :id", id=held)[0]
            == 0
        )

    def test_reinstated_its_listings_are_back(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        base = f"{ADMIN}/pharmacies/{shop.pharmacy}"
        early = http.post(f"{base}/reinstate", json={"reason": "why"}, headers=admin)
        http.post(f"{base}/suspend", json={"reason": "A check."}, headers=admin)

        back = http.post(f"{base}/reinstate", json={"reason": "The check was fine."}, headers=admin)

        assert (early.status_code, code_of(early)) == (409, "CHANGED_SINCE")
        assert (back.json()["status"], back.json()["status_reason"]) == ("APPROVED", None)
        assert shop.visible() == 1
        assert http.get("/api/v1/pharmacy/inventory", headers=shop.pharmacist).status_code == 200
        assert "Your pharmacy on DawaLink is active again" in [s for _, s, _ in api.emails()]


class TestClients:
    def test_the_list_shows_counts_and_never_a_person(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        made = shop.reserve()
        api.client(full_name="Someone Else")

        everyone = http.get(f"{ADMIN}/clients", headers=admin)
        by_ref = http.get(f"{ADMIN}/clients?ref={made.ref.lower()}", headers=admin).json()
        detail = http.get(f"{ADMIN}/clients/{shop.client}", headers=admin)

        assert len(everyone.json()["items"]) == 2
        (found,) = by_ref["items"]
        assert (found["id"], found["status"], found["open_orders"]) == (
            str(shop.client),
            "ACTIVE",
            1,
        )
        for answer in (everyone, detail):
            for private in ("Rana", "Khoury", "rana@example.com", "70123456", "Someone"):
                assert private not in answer.text

    def test_contact_details_are_read_one_audited_view_at_a_time(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        """A-D3, N-47: every view is in the audit log, and the 31st in an hour is refused
        and noted."""
        http = api.http()
        path = f"{ADMIN}/clients/{shop.client}/contact"

        first = http.get(path, headers=admin)
        for _ in range(29):
            http.get(path, headers=admin)
        too_many = http.get(path, headers=admin)
        api.world.later(hours=1, minutes=1)
        later = http.get(path, headers=admin)

        assert first.json() == {
            "full_name": "Rana Khoury",
            "email": "rana@example.com",
            "phone": "+96170123456",
        }
        assert (too_many.status_code, code_of(too_many)) == (429, "RATE_LIMITED")
        assert later.status_code == 200
        actions = [
            row.action
            for row in api.world.all(
                "SELECT action FROM audit_events WHERE action LIKE 'pii.%' ORDER BY id"
            )
        ]
        assert actions.count("pii.view") == 31
        assert actions.count("pii.view_limit") == 1
        # The log says whose details were seen and by whom, never the details.
        seen = api.world.all("SELECT before, after FROM audit_events WHERE action = 'pii.view'")
        assert all(row.before is None and row.after is None for row in seen)

    def test_a_suspension_ends_everything_the_client_had_going(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        """SM-2. The order matters: the request is closed as cancelled first, so the
        cancelled reservation can't open it again (R-RQ12) or start an agent turn."""
        http = api.http()
        make = api.world.make
        login = api.token(shop.client)
        reserved = shop.reserve(qty=2)
        request = make.request(client_id=shop.client)
        item = make.request_item(request, product_id=shop.product)
        thread = make.conversation(client_id=shop.client, kind="request", request_id=request)
        watch = make.claim(client_id=shop.client)

        suspended = http.post(
            f"{ADMIN}/clients/{shop.client}/suspend",
            json={"reason": "Repeated abuse of the assistant."},
            headers=admin,
        )
        api.world.settle(api.world.tx())

        assert suspended.json()["client"]["status"] == "SUSPENDED"
        # Every login ends at once, and no new one starts.
        assert http.get("/api/v1/auth/me", headers=login).status_code == 401
        again = http.post(
            "/api/v1/auth/login", json={"email": "rana@example.com", "password": PASSWORD}
        )
        assert (again.status_code, code_of(again)) == (403, "ACCOUNT_SUSPENDED")
        # The reservation is cancelled and its packs are back on the shelf.
        assert shop.state_of(reserved.id) == "CANCELLED_BY_SYSTEM"
        assert (
            api.world.one("SELECT qty_reserved FROM inventory_items WHERE id = :id", id=shop.box)[0]
            == 0
        )
        closed = api.world.one(
            "SELECT state, outcome FROM sourcing_requests WHERE id = :id", id=request
        )
        assert tuple(closed) == ("CLOSED", "CANCELLED")
        assert api.world.one("SELECT state FROM request_items WHERE id = :id", id=item)[0] == (
            "CANCELLED"
        )
        assert api.world.one("SELECT state FROM claims WHERE id = :id", id=watch)[0] == "CANCELLED"
        # Nobody is there to answer: no agent turn waits in the request's thread.
        assert (
            api.world.one("SELECT pending_turn_at FROM conversations WHERE id = :id", id=thread)[0]
            is None
        )
        (event,) = [
            row
            for row in api.world.all(
                "SELECT action, after FROM audit_events WHERE entity_id = :id", id=shop.client
            )
            if row.action == "client.suspend"
        ]
        assert event.after == {
            "status": "SUSPENDED",
            "orders_cancelled": 1,
            "requests_closed": 1,
            "watches_ended": 1,
        }

    def test_a_request_that_closed_fulfilled_stays_closed(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        """R-RQ12 opens a closed request again when one of its reserved boxes is
        cancelled by the system inside its 6 hours. A suspension cancels the client's
        boxes by the system: it must not reopen anything, nor start an agent turn."""
        http = api.http()
        make = api.world.make
        reserved = shop.reserve()
        request = make.request(
            client_id=shop.client,
            state="CLOSED",
            outcome="FULFILLED",
            closed_at=api.world.clock.now(),
        )
        item = make.request_item(request, product_id=shop.product, state="SECURED", qty_secured=1)
        thread = make.conversation(client_id=shop.client, kind="request", request_id=request)
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE orders SET request_item_id = %s, source = 'request' WHERE id = %s",
                (item, reserved.id),
            )

        http.post(f"{ADMIN}/clients/{shop.client}/suspend", json={"reason": "why"}, headers=admin)
        api.world.settle(api.world.tx())

        assert shop.state_of(reserved.id) == "CANCELLED_BY_SYSTEM"
        closed = api.world.one(
            "SELECT state, outcome FROM sourcing_requests WHERE id = :id", id=request
        )
        assert closed.state == "CLOSED"
        assert (
            api.world.one("SELECT pending_turn_at FROM conversations WHERE id = :id", id=thread)[0]
            is None
        )
        assert "request.reopen" not in api.world.audit_actions(request)

    def test_reinstating_and_lifting_a_pause(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        paused = api.world.make.client(
            "PAUSED", paused_until=api.world.clock.now() + timedelta(days=5)
        )
        base = f"{ADMIN}/clients"
        http.post(f"{base}/{shop.client}/suspend", json={"reason": "why"}, headers=admin)

        back = http.post(f"{base}/{shop.client}/reinstate", json={"reason": "ok"}, headers=admin)
        not_paused = http.post(
            f"{base}/{shop.client}/lift-pause", json={"reason": "ok"}, headers=admin
        )
        lifted = http.post(
            f"{base}/{paused}/lift-pause", json={"reason": "A mistake."}, headers=admin
        )
        no_reason = http.post(f"{base}/{shop.client}/suspend", json={}, headers=admin)

        assert back.json()["client"]["status"] == "ACTIVE"
        assert (not_paused.status_code, code_of(not_paused)) == (409, "CHANGED_SINCE")
        assert (lifted.json()["client"]["status"], lifted.json()["client"]["paused_until"]) == (
            "ACTIVE",
            None,
        )
        assert (no_reason.status_code, code_of(no_reason)) == (422, "REASON_REQUIRED")
        login = http.post(
            "/api/v1/auth/login", json={"email": "rana@example.com", "password": PASSWORD}
        )
        assert login.status_code == 200


class TestContestingANoShow:
    """R-N3: the pharmacy forgot to press [Picked up]. The client says so once, a person
    looks, and the no-show stops counting."""

    def test_the_client_contests_once_and_a_person_is_asked(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        login = api.token(shop.client)
        missed = shop.no_show()
        other = api.token(api.client())
        path = f"/api/v1/reservations/{missed.id}/contest"

        contested = http.post(path, headers=login)
        twice = http.post(path, headers=login)
        not_theirs = http.post(path, headers=other)

        assert (contested.status_code, contested.json()["contestable"]) == (200, False)
        assert (twice.status_code, code_of(twice)) == (409, "NOT_CONTESTABLE")
        assert (not_theirs.status_code, code_of(not_theirs)) == (404, "NOT_FOUND")
        (escalation,) = http.get(f"{ADMIN}/escalations", headers=admin).json()["items"]
        assert (escalation["reason"], escalation["client_id"]) == ("complaint", str(shop.client))
        assert missed.ref in escalation["summary"]
        overview = http.get(f"{ADMIN}/overview", headers=admin).json()
        assert overview["contests_waiting"] == 1
        detail = http.get(f"{ADMIN}/clients/{shop.client}", headers=admin).json()
        assert [(row["ref"], row["pharmacy"]) for row in detail["contested"]] == [
            (missed.ref, "Hamra Pharmacy")
        ]

    def test_a_reservation_that_is_not_a_counted_no_show_cannot_be_contested(
        self, api: Api, shop: Shop
    ) -> None:
        http = api.http()
        login = api.token(shop.client)
        open_one = shop.reserve()

        answer = http.post(f"/api/v1/reservations/{open_one.id}/contest", headers=login)

        assert (answer.status_code, code_of(answer)) == (409, "NOT_CONTESTABLE")

    def test_clearing_it_lifts_the_pause_it_caused(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        login = api.token(shop.client)
        first, second = shop.no_show(), shop.no_show()
        status = api.world.one(
            "SELECT status FROM client_profiles WHERE user_id = :id", id=shop.client
        )[0]
        http.post(f"/api/v1/reservations/{second.id}/contest", headers=login)
        clear = f"{ADMIN}/reservations/{second.id}/clear-no-show"

        not_contested = http.post(
            f"{ADMIN}/reservations/{first.id}/clear-no-show", json={"reason": "x"}, headers=admin
        )
        no_reason = http.post(clear, json={}, headers=admin)
        cleared = http.post(
            clear, json={"reason": "The pharmacy confirmed the pickup."}, headers=admin
        )
        twice = http.post(clear, json={"reason": "Again."}, headers=admin)

        assert status == "PAUSED"  # two counted no-shows in 30 days (R-N1)
        assert (not_contested.status_code, code_of(not_contested)) == (409, "NOT_CONTESTABLE")
        assert (no_reason.status_code, code_of(no_reason)) == (422, "REASON_REQUIRED")
        shown = cleared.json()["client"]
        assert (shown["status"], shown["no_shows"], shown["contested"]) == ("ACTIVE", 1, 0)
        assert (twice.status_code, code_of(twice)) == (409, "NOT_CONTESTABLE")
        # The reservation itself is still what it was: expired (INV-4).
        assert shop.state_of(second.id) == "EXPIRED_NO_SHOW"
        assert "order.no_show_cleared" in api.world.audit_actions(second.id)


class TestAbuseFlags:
    def test_a_pause_for_no_shows_raises_a_flag_an_admin_handles(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        shop.no_show()
        shop.no_show()

        (flag,) = http.get(f"{ADMIN}/abuse-flags", headers=admin).json()["items"]
        no_reason = http.post(f"{ADMIN}/abuse-flags/{flag['id']}/dismiss", json={}, headers=admin)
        warned = http.post(
            f"{ADMIN}/abuse-flags/{flag['id']}/act",
            json={"action": "warn", "reason": "Told to cancel in time."},
            headers=admin,
        )
        twice = http.post(
            f"{ADMIN}/abuse-flags/{flag['id']}/dismiss", json={"reason": "x"}, headers=admin
        )

        assert (flag["rule"], flag["severity"], flag["subject_id"]) == (
            "no_show_pause",
            "low",
            str(shop.client),
        )
        assert flag["evidence"] == {"counted_no_shows": 2}
        assert (no_reason.status_code, code_of(no_reason)) == (422, "REASON_REQUIRED")
        assert (warned.json()["state"], warned.json()["action"]) == ("ACTIONED", "warn")
        assert (twice.status_code, code_of(twice)) == (409, "CHANGED_SINCE")
        assert http.get(f"{ADMIN}/abuse-flags", headers=admin).json()["items"] == []

    def test_suspending_from_a_flag_is_a_real_suspension(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "INSERT INTO abuse_flags (subject_type, subject_id, rule, severity, evidence) "
                "VALUES ('client', %s, 'guardrail_repeat', 'high', %s::jsonb)",
                (shop.client, '{"triggers_24h": 3}'),
            )
        reserved = shop.reserve()
        (flag,) = http.get(f"{ADMIN}/abuse-flags", headers=admin).json()["items"]
        before = http.get(f"{ADMIN}/overview", headers=admin).json()

        acted = http.post(
            f"{ADMIN}/abuse-flags/{flag['id']}/act",
            json={"action": "suspend", "reason": "Three injection attempts in a day."},
            headers=admin,
        )

        assert (before["flags_open"], before["flags_high"]) == (1, 1)
        assert acted.json()["action"] == "suspend"
        assert shop.state_of(reserved.id) == "CANCELLED_BY_SYSTEM"
        status = api.world.one(
            "SELECT status FROM client_profiles WHERE user_id = :id", id=shop.client
        )[0]
        assert status == "SUSPENDED"


class TestCatalogAndHealth:
    def test_the_catalog_is_read_with_the_controlled_products(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        api.world.make.product(
            moph_name="LOCKEDOL 10MG", search_name="lockedol 10mg", controlled=True
        )

        found = http.get(f"{ADMIN}/catalog/products?q=lockedol", headers=admin).json()["items"]
        everything = http.get(f"{ADMIN}/catalog/products", headers=admin).json()["items"]
        imports = http.get(f"{ADMIN}/catalog/imports", headers=admin).json()["items"]
        described = api.app(assistant=False).openapi()["paths"]

        assert [(row["name"], row["controlled"]) for row in found] == [("LOCKEDOL 10MG", True)]
        assert {"AUGMENTIN 1G", "LOCKEDOL 10MG"} <= {row["name"] for row in everything}
        assert imports
        assert imports[0]["rows_imported"] >= 0
        # Read-only (A-D9): the catalog's addresses take nothing but a read.
        catalog_paths = {path: set(how) for path, how in described.items() if "/catalog" in path}
        assert all(how == {"get"} for how in catalog_paths.values())

    def test_health_counts_what_happened_and_says_what_is_wrong(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        http = api.http()
        make = api.world.make
        now = api.world.clock.now()
        chat = make.conversation(client_id=shop.client)
        for latency, outcome in ((1000, "ok"), (3000, "ok"), (9000, "error")):
            make.agent_run(
                conversation_id=chat,
                started_at=now - timedelta(hours=1),
                latency_ms=latency,
                outcome=outcome,
                tokens_in=1000,
                tokens_out=100,
                cost_usd=0.01,
                guardrails=["injection"] if outcome == "error" else [],
            )
        order = shop.reserve()
        http.post(
            f"/api/v1/pharmacy/reservations/{order.id}/picked-up", json={}, headers=shop.pharmacist
        )

        quiet = http.get(f"{ADMIN}/health?days=7", headers=admin).json()
        # An agent turn that failed four times waits in a thread: an alert (R-AL).
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE conversations SET pending_turn_at = %s, turn_attempts = 4 WHERE id = %s",
                (now, chat),
            )
        loud = http.get(f"{ADMIN}/health", headers=admin).json()

        agent = quiet["agent"]
        assert (agent["turns"], agent["errors"], agent["guardrail_triggers"]) == (3, 1, 1)
        assert (agent["latency_p50_ms"], agent["tokens_in"]) == (3000, 3000)
        assert agent["cost_usd"] == pytest.approx(0.03)
        assert agent["model"] == "scripted"
        market = quiet["marketplace"]
        assert (market["reservations"], market["picked_up"], market["units_saved"]) == (1, 1, 1)
        assert market["picked_up_share"] == 1.0
        assert quiet["system"]["turns_waiting"] == 0
        assert "agent_turn_stuck" not in quiet["alerts"]
        assert loud["system"]["turns_stuck"] == 1
        assert "agent_turn_stuck" in loud["alerts"]
        # Numbers only: nobody's name is in a health answer.
        assert "Rana" not in str(quiet)

    def test_an_admin_locked_out_or_over_the_contact_limit_is_an_alert_for_the_others(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        """R-AL, R-AU6, docs/10 RR-5: both are about an admin's own login, so the other
        admins must see them without reading the audit log."""
        http = api.http()
        api.world.make.user("admin", email="other@example.com", totp_secret=b"not-a-real-secret")
        api.client(email="rami@example.com")

        quiet = http.get(f"{ADMIN}/health", headers=admin).json()["alerts"]
        for email in ("rami@example.com", "other@example.com"):
            for _ in range(5):
                http.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
            if email == "rami@example.com":
                # A client's own lock is nobody's alert.
                after_a_client = http.get(f"{ADMIN}/health", headers=admin).json()["alerts"]
        for _ in range(31):
            http.get(f"{ADMIN}/clients/{shop.client}/contact", headers=admin)
        loud = http.get(f"{ADMIN}/health", headers=admin).json()["alerts"]
        api.world.later(hours=25)
        next_day = http.get(f"{ADMIN}/health", headers=admin).json()["alerts"]

        assert quiet == after_a_client == []
        assert set(loud) == {"admin_login_locked", "contact_views_limit"}
        assert next_day == []

    def test_a_day_that_used_its_share_of_the_ai_budget_is_an_alert(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        """R-AL, N-46: a day may use 10% of the month's budget; the assistant then stops
        for everyone until midnight, and the admins are told why."""
        http = api.http(llm_monthly_budget_usd=Decimal(20))
        chat = api.world.make.conversation(client_id=shop.client)
        spend = {"conversation_id": chat, "started_at": api.world.clock.now()}

        api.world.make.agent_run(**spend, cost_usd=1.5)
        below = http.get(f"{ADMIN}/health", headers=admin).json()["alerts"]
        api.world.make.agent_run(**spend, cost_usd=0.5)
        at_the_cap = http.get(f"{ADMIN}/health", headers=admin).json()["alerts"]

        assert below == []
        assert at_the_cap == ["llm_daily_cap"]

    @pytest.mark.rows_by_hand
    def test_what_the_daily_run_found_is_an_alert(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        """docs/09 FO-3, FO-4: a count that is off, and a purge that failed two days running."""
        http = api.http()
        tasks = api.world.clock_tasks()
        tasks.run_daily_tasks()
        quiet = http.get(f"{ADMIN}/health", headers=admin).json()

        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE inventory_items SET qty_reserved = 1 WHERE id = %s", (shop.box,)
            )
        api.world.later(days=1)
        tasks.run_daily_tasks()
        off = http.get(f"{ADMIN}/health", headers=admin).json()
        tx = api.world.tx()
        for _ in range(2):
            daily.keep_checks(
                tx, tx.today, {"stock_off": [], "requests_off": []}, retention_failed=True
            )
        api.world.settle(tx)
        failing = http.get(f"{ADMIN}/health", headers=admin).json()

        assert quiet["alerts"] == []
        assert (quiet["system"]["stock_off"], quiet["system"]["retention_failed_days"]) == (0, 0)
        assert off["alerts"] == ["books_do_not_add_up"]
        assert off["system"]["stock_off"] == 1
        assert failing["alerts"] == ["retention_failing"]
        assert failing["system"]["retention_failed_days"] == 2

    def test_a_worker_that_is_late_on_deadlines_is_an_alert_until_it_catches_up(
        self, api: Api, shop: Shop, admin: dict[str, str]
    ) -> None:
        """FX-14, R-AL: the API can't see the worker, so it reads how old the oldest
        deadline is that nobody acted on."""
        http = api.http()
        order = shop.reserve()

        on_time = http.get(f"{ADMIN}/health", headers=admin).json()
        api.world.later(days=2)  # long past the pickup deadline, and no worker ran
        late = http.get(f"{ADMIN}/health", headers=admin).json()
        expired = api.world.clock_tasks().expire_reservations()
        caught_up = http.get(f"{ADMIN}/health", headers=admin).json()

        assert (on_time["system"]["clock_check_late_s"], on_time["alerts"]) == (0, [])
        assert late["system"]["clock_check_late_s"] > 120
        assert late["alerts"] == ["clock_check_late"]
        assert (expired, shop.state_of(order.id)) == (1, "EXPIRED_NO_SHOW")
        assert (caught_up["system"]["clock_check_late_s"], caught_up["alerts"]) == (0, [])
