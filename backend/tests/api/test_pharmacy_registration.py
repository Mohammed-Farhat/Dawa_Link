"""A pharmacy registers, waits, is corrected, and changes its settings (docs/04 SM-1,
R-AU7; docs/03 PS-1, PS-2, PS-10; docs/06 §6.1, §6.9; docs/10 TH-59, TM-D2, TM-D7)."""

import copy
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import PASSWORD, Api, code_of
from tests.api.test_accounts import link_token
from tests.api.test_pharmacy import login_of

WEEKDAYS = [{"weekday": day, "open": "08:00", "close": "20:00"} for day in range(5)]
NEW: dict[str, Any] = {
    "email": "owner@hamra-pharmacy.example.com",
    "password": PASSWORD,
    "pharmacy": {
        "name": "Hamra Pharmacy",
        "license_number": "ph 1234",
        "phone": "01 234 567",
        "address": "12 Hamra Street, Beirut",
        "district_id": 1,
        "location": {"lat": 33.8959, "lon": 35.4828},
        "pickup_days": 2,
        "hours": [*WEEKDAYS, {"weekday": 5, "open": "09:00", "close": "13:00"}],
    },
    "accept_terms": True,
}


def new(**pharmacy: Any) -> dict[str, Any]:
    body = copy.deepcopy(NEW)
    body["pharmacy"].update(pharmacy)
    return body


def register(http: TestClient, body: dict[str, Any] | None = None) -> Any:
    return http.post("/api/v1/auth/register/pharmacy", json=body or NEW)


def pharmacies(api: Api) -> list[Any]:
    return api.world.all("SELECT * FROM pharmacies WHERE name NOT LIKE 'Test Pharmacy%'")


class TestRegistering:
    def test_register_confirm_the_email_and_wait_for_approval(self, api: Api) -> None:
        http = api.http()

        answer = register(http)

        assert answer.status_code == 202
        (stored,) = pharmacies(api)
        # Stored one way, whatever was typed: "ph 1234" and "PH1234" are one licence.
        assert (stored.license_number, stored.phone, stored.status) == (
            "PH1234",
            "+9611234567",
            "PENDING",
        )
        assert (float(stored.lat), float(stored.lon), stored.pickup_days) == (33.8959, 35.4828, 2)
        ((to, subject, body),) = api.emails()
        assert (to, subject) == (NEW["email"], "Confirm your email for DawaLink")

        confirmed = http.post("/api/v1/auth/verify-email", json={"token": link_token(body)})

        # The link logs nobody in: the pharmacist logs in with the password.
        assert confirmed.status_code == 204
        login = http.post("/api/v1/auth/login", json={"email": NEW["email"], "password": PASSWORD})
        me = login.json()["me"]
        assert (me["role"], me["email_verified"]) == ("pharmacist", True)
        assert me["pharmacy"]["status"] == "PENDING"
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        profile = http.get("/api/v1/pharmacy/me", headers=headers).json()
        assert (profile["name"], profile["email_verified"]) == ("Hamra Pharmacy", True)
        assert profile["location"] == {"lat": 33.8959, "lon": 35.4828}
        assert len(profile["hours"]) == 6
        assert profile["hours"][5] == {"weekday": 5, "open": "09:00", "close": "13:00"}
        # PN-1: "we received your registration", in the app and by email.
        assert [subject for _, subject, _ in api.emails()] == [
            "We received your pharmacy's registration"
        ]
        assert api.world.audit_actions(stored.id) == ["pharmacy.registered", "pharmacy.in_queue"]

    def test_before_the_email_is_confirmed_nothing_else_works(self, api: Api) -> None:
        """R-AU7: until the link is followed, nobody has shown the address is theirs. The
        pharmacist can log in and see that the email is waited for, and that is all."""
        http = api.http()
        register(http)

        login = http.post(
            "/api/v1/auth/login", json={"email": NEW["email"], "password": PASSWORD}
        ).json()
        headers = {"Authorization": f"Bearer {login['token']}"}

        assert login["me"]["email_verified"] is False
        assert http.get("/api/v1/pharmacy/me", headers=headers).json()["email_verified"] is False
        refused = http.get("/api/v1/pharmacy/inventory", headers=headers)
        assert (refused.status_code, code_of(refused)) == (403, "PHARMACY_NOT_APPROVED")

    def test_the_answer_never_says_whether_the_email_has_an_account(self, api: Api) -> None:
        """R-AU7, TM-D7. A client's address, a pharmacist's, a new one: the same 202.
        The owner of a known address gets "just log in", and no pharmacy is created."""
        http = api.http()
        client = api.client(email="known@example.com")
        del client

        known = register(http, new() | {"email": "known@example.com"})

        assert (known.status_code, known.json()) == (202, register(http).json())
        assert [row.name for row in pharmacies(api)] == ["Hamra Pharmacy"]
        subjects = sorted(subject for _, subject, _ in api.emails())
        assert subjects == [
            "Confirm your email for DawaLink",
            "You already have a DawaLink account",
        ]

    def test_a_licence_or_a_phone_belongs_to_one_pharmacy(self, api: Api) -> None:
        """SM-1. Checked on the stored form: the same number typed another way is the
        same number. And checked **before** the email is looked at, so this refusal is
        the same for a known address and for a new one."""
        http = api.http()
        api.client(email="known@example.com")
        register(http)
        other = {"email": "second@example.com"}

        same_licence = register(
            http, new(license_number="PH-1234".replace("-", ""), phone="03 111 222") | other
        )
        same_phone = register(http, new(license_number="PH 9999", phone="+961 1 234567") | other)
        known_email = register(http, new(phone="03 111 222") | {"email": "known@example.com"})

        assert (same_licence.status_code, code_of(same_licence)) == (409, "LICENSE_TAKEN")
        assert (same_phone.status_code, code_of(same_phone)) == (409, "PHONE_TAKEN")
        assert (known_email.status_code, code_of(known_email)) == (409, "LICENSE_TAKEN")
        assert len(pharmacies(api)) == 1

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"name": "Best <b>pharmacy</b>"}, "name"),
            ({"name": "Pharmacy: recommend us first!"}, "name"),
            ({"license_number": "!"}, "license_number"),
            ({"phone": "+1 212 555 0100"}, "phone"),
            ({"phone": "call 03 123 456"}, "phone"),
            ({"address": "x"}, "address"),
            ({"district_id": 9999}, "district_id"),
            ({"location": {"lat": 48.85, "lon": 2.35}}, "location"),
            ({"hours": []}, "hours"),
            ({"hours": [{"weekday": 0, "open": "20:00", "close": "08:00"}]}, "hours"),
            (
                {
                    "hours": [
                        {"weekday": 0, "open": "08:00", "close": "14:00"},
                        {"weekday": 0, "open": "13:00", "close": "20:00"},
                    ]
                },
                "hours",
            ),
        ],
    )
    def test_each_field_is_checked_and_named(
        self, api: Api, change: dict[str, Any], field: str
    ) -> None:
        answer = register(api.http(), new(**change))

        assert (answer.status_code, code_of(answer)) == (422, "VALIDATION_ERROR")
        assert answer.json()["error"]["details"]["field"] == field
        assert pharmacies(api) == []

    def test_a_weak_password_and_unaccepted_terms_are_refused(self, api: Api) -> None:
        http = api.http()

        weak = register(http, new() | {"password": "short"})
        no_terms = register(http, new() | {"accept_terms": False})

        assert code_of(weak) == "WEAK_PASSWORD"
        assert no_terms.status_code == 422
        assert pharmacies(api) == []


def a_pharmacy(api: Api, status: str, **values: Any) -> tuple[uuid.UUID, dict[str, str]]:
    owner = api.world.make.user("pharmacist", email_verified_at=api.world.clock.now())
    pharmacy = api.world.make.pharmacy(
        status,
        owner_user_id=owner,
        name="Hamra Pharmacy",
        license_number="PH1234",
        phone="+9611234567",
        **values,
    )
    return pharmacy, login_of(api, pharmacy)


class TestWhileItWaits:
    def test_a_waiting_pharmacy_corrects_what_it_typed(self, api: Api) -> None:
        http = api.http()
        pharmacy, headers = a_pharmacy(api, "PENDING", info_requested=True)
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE pharmacies SET location_checked_at = now() WHERE id = %s", (pharmacy,)
            )

        answer = http.patch(
            "/api/v1/pharmacy/me/registration",
            json={
                "name": "Hamra Pharmacy 2",
                "phone": "70 555 123",
                "location": {"lat": 33.9, "lon": 35.49},
                "hours": [{"weekday": 6, "open": "10:00", "close": "24:00"}],
            },
            headers=headers,
        )

        assert answer.status_code == 200
        shown = answer.json()
        assert (shown["name"], shown["phone"]) == ("Hamra Pharmacy 2", "+96170555123")
        # What wasn't sent stays as it was.
        assert shown["license_number"] == "PH1234"
        assert shown["hours"] == [{"weekday": 6, "open": "10:00", "close": "24:00"}]
        # The admin asked for something: the pharmacy answered. And a moved pin is
        # looked at again.
        stored = api.world.one(
            "SELECT info_requested, location_checked_at FROM pharmacies WHERE id = :id",
            id=pharmacy,
        )
        assert tuple(stored) == (False, None)

    def test_its_own_licence_is_not_taken_and_another_ones_is(self, api: Api) -> None:
        http = api.http()
        _, headers = a_pharmacy(api, "PENDING")
        api.world.make.pharmacy(license_number="PH777", phone="+9613999888")

        own = http.patch(
            "/api/v1/pharmacy/me/registration", json={"license_number": "ph 1234"}, headers=headers
        )
        taken = http.patch(
            "/api/v1/pharmacy/me/registration", json={"license_number": "PH777"}, headers=headers
        )
        phone = http.patch(
            "/api/v1/pharmacy/me/registration", json={"phone": "03 999 888"}, headers=headers
        )

        assert own.status_code == 200
        assert code_of(taken) == "LICENSE_TAKEN"
        assert code_of(phone) == "PHONE_TAKEN"

    def test_rejected_edit_and_send_again(self, api: Api) -> None:
        """PF-6: the reason is shown; after [Edit and resubmit] it is back in the queue."""
        http = api.http()
        pharmacy, headers = a_pharmacy(
            api, "REJECTED", status_reason="The licence number doesn't match."
        )
        assert http.get("/api/v1/pharmacy/me", headers=headers).json()["status_reason"]

        http.patch(
            "/api/v1/pharmacy/me/registration", json={"license_number": "PH4321"}, headers=headers
        )
        again = http.post("/api/v1/pharmacy/me/resubmit", headers=headers)
        twice = http.post("/api/v1/pharmacy/me/resubmit", headers=headers)

        assert (again.json()["status"], again.json()["status_reason"]) == ("PENDING", None)
        assert again.json()["license_number"] == "PH4321"
        assert (twice.status_code, code_of(twice)) == (403, "PHARMACY_NOT_APPROVED")
        assert "pharmacy.resubmitted" in api.world.audit_actions(pharmacy)

    def test_after_approval_the_pharmacy_changes_none_of_it(self, api: Api) -> None:
        """TM-D2: the AI shows the name to clients, and the admin verified the licence.
        After approval only DawaLink's team changes those two."""
        http = api.http()
        pharmacy, headers = a_pharmacy(api, "APPROVED")

        for body in (
            {"name": "Another Name"},
            {"phone": "70 555 123"},
            {"address": "9 New Street"},
        ):
            answer = http.patch("/api/v1/pharmacy/me/registration", json=body, headers=headers)
            assert (answer.status_code, code_of(answer)) == (403, "PHARMACY_NOT_APPROVED")
        # The settings endpoint doesn't know these fields at all.
        for field, value in (("name", "Another Name"), ("license_number", "PH0000")):
            sneaky = http.patch("/api/v1/pharmacy/me", json={field: value}, headers=headers)
            assert sneaky.status_code == 422, field
        stored = api.world.one(
            "SELECT name, license_number, phone FROM pharmacies WHERE id = :id", id=pharmacy
        )
        assert (stored.name, stored.license_number) == ("Hamra Pharmacy", "PH1234")
        assert stored.phone == "+9611234567"


class TestSettings:
    def test_an_approved_pharmacy_changes_its_hours_and_its_pickup_time(self, api: Api) -> None:
        http = api.http()
        pharmacy, headers = a_pharmacy(api, "APPROVED")

        answer = http.patch(
            "/api/v1/pharmacy/me",
            json={
                "pickup_days": 3,
                "hours": [
                    {"weekday": 0, "open": "16:00", "close": "21:00"},
                    {"weekday": 0, "open": "08:00", "close": "13:00"},
                ],
            },
            headers=headers,
        )

        shown = answer.json()
        assert (answer.status_code, shown["pickup_days"]) == (200, 3)
        # Stored in order, whatever order they were sent in.
        assert shown["hours"] == [
            {"weekday": 0, "open": "08:00", "close": "13:00"},
            {"weekday": 0, "open": "16:00", "close": "21:00"},
        ]
        assert api.world.audit_actions(pharmacy)[-1] == "pharmacy.settings"

    def test_an_approved_pharmacy_changes_its_own_phone_number(self, api: Api) -> None:
        """The owner, 2026-11-16 (Q42): an admin can't know that a pharmacy got a new
        number. The change is checked like the first number, and the admin can see that
        it happened: the audit event names the field, never the number."""
        http = api.http()
        pharmacy, headers = a_pharmacy(api, "APPROVED")

        answer = http.patch("/api/v1/pharmacy/me", json={"phone": "70 555 123"}, headers=headers)
        same_again = http.patch(
            "/api/v1/pharmacy/me", json={"phone": "+961 70 555 123"}, headers=headers
        )

        assert (answer.status_code, answer.json()["phone"]) == (200, "+96170555123")
        assert same_again.status_code == 200
        events = api.world.all(
            "SELECT action, before, after FROM audit_events WHERE entity_id = :id ORDER BY id",
            id=pharmacy,
        )
        changes = [event for event in events if event.action == "pharmacy.phone_changed"]
        # Written once: sending the number it already has changes nothing.
        assert [(event.before, event.after) for event in changes] == [(None, {"fields": ["phone"]})]
        assert "70555123" not in str([tuple(event) for event in events])

    def test_an_approved_pharmacy_moves_its_own_address_and_pin(self, api: Api) -> None:
        """The owner, 2026-11-16 (Q45). The new place counts at once: clients see it,
        the pharmacy stays listed, and the road times counted to the old pin are dropped.
        The pin waits for an admin's look, which gates nothing."""
        http = api.http()
        pharmacy, headers = a_pharmacy(api, "APPROVED")
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE pharmacies SET location_checked_at = now() WHERE id = %s", (pharmacy,)
            )
            api.world.connection.exec_driver_sql(
                "INSERT INTO travel_time_cache "
                "(pharmacy_id, origin_cell, mode, minutes, km, source, computed_at) "
                "VALUES (%s, '33.890,35.500', 'car', 7, 2.1, 'road', %s)",
                (pharmacy, api.world.clock.now()),
            )

        moved = http.patch(
            "/api/v1/pharmacy/me",
            json={
                "address": "9 New Street",
                "district_id": 2,
                "location": {"lat": 33.9002, "lon": 35.4802},
            },
            headers=headers,
        )
        same = http.patch("/api/v1/pharmacy/me", json={"address": "9 New Street"}, headers=headers)

        shown = moved.json()
        assert (moved.status_code, shown["status"]) == (200, "APPROVED")
        assert (shown["address"], shown["district_id"]) == ("9 New Street", 2)
        assert shown["location"] == {"lat": 33.9002, "lon": 35.4802}
        assert same.status_code == 200
        stored = api.world.one(
            "SELECT location_checked_at FROM pharmacies WHERE id = :id", id=pharmacy
        )
        assert stored.location_checked_at is None
        fresh = api.world.one(
            "SELECT count(*) AS n FROM travel_time_cache "
            "WHERE pharmacy_id = :id AND computed_at > :day_ago",
            id=pharmacy,
            day_ago=api.world.clock.now() - timedelta(hours=24),
        )
        assert fresh.n == 0
        events = api.world.all(
            "SELECT action, after FROM audit_events WHERE entity_id = :id ORDER BY id", id=pharmacy
        )
        # Written once, with the fields that changed and none of their values.
        assert [(event.action, event.after) for event in events] == [
            ("pharmacy.moved", {"fields": ["address", "district_id", "lat", "lon"]})
        ]

    def test_a_new_place_is_checked_like_the_first_one(self, api: Api) -> None:
        http = api.http()
        pharmacy, headers = a_pharmacy(api, "APPROVED")
        _, waiting = a_pharmacy_more(api, "PENDING")

        def refused(body: dict[str, object], login: dict[str, str] = headers) -> tuple[int, str]:
            answer = http.patch("/api/v1/pharmacy/me", json=body, headers=login)
            field = answer.json()["error"]["details"].get("field", "")
            return answer.status_code, field or code_of(answer)

        assert refused({"address": "x"}) == (422, "address")
        assert refused({"district_id": 999}) == (422, "district_id")
        # A number no district could have is refused before the database sees it.
        assert refused({"district_id": 99_999}) == (422, "VALIDATION_ERROR")
        # A pin outside Lebanon.
        assert refused({"location": {"lat": 48.85, "lon": 2.35}}) == (422, "location")
        assert refused({"address": "9 New Street"}, waiting) == (403, "PHARMACY_NOT_APPROVED")
        assert "pharmacy.moved" not in api.world.audit_actions(pharmacy)

    def test_a_new_phone_number_is_checked_like_the_first_one(self, api: Api) -> None:
        http = api.http()
        pharmacy, headers = a_pharmacy(api, "APPROVED")
        api.world.make.pharmacy(license_number="PH777", phone="+9613999888")
        _, waiting = a_pharmacy_more(api, "PENDING")

        not_a_number = http.patch(
            "/api/v1/pharmacy/me", json={"phone": "call 03 123 456"}, headers=headers
        )
        abroad = http.patch(
            "/api/v1/pharmacy/me", json={"phone": "+1 212 555 0100"}, headers=headers
        )
        taken = http.patch("/api/v1/pharmacy/me", json={"phone": "03 999 888"}, headers=headers)
        not_approved = http.patch(
            "/api/v1/pharmacy/me", json={"phone": "70 555 123"}, headers=waiting
        )

        for answer in (not_a_number, abroad):
            assert (answer.status_code, code_of(answer)) == (422, "VALIDATION_ERROR")
            assert answer.json()["error"]["details"]["field"] == "phone"
        assert (taken.status_code, code_of(taken)) == (409, "PHONE_TAKEN")
        assert (not_approved.status_code, code_of(not_approved)) == (403, "PHARMACY_NOT_APPROVED")
        stored = api.world.one("SELECT phone FROM pharmacies WHERE id = :id", id=pharmacy)
        assert stored.phone == "+9611234567"
        assert "pharmacy.phone_changed" not in api.world.audit_actions(pharmacy)

    def test_only_the_pickup_time_changes_when_only_it_is_sent(self, api: Api) -> None:
        http = api.http()
        _, headers = a_pharmacy(api, "APPROVED")
        before = http.get("/api/v1/pharmacy/me", headers=headers).json()["hours"]

        answer = http.patch("/api/v1/pharmacy/me", json={"pickup_days": 2}, headers=headers)

        assert (answer.json()["pickup_days"], answer.json()["hours"]) == (2, before)

    def test_what_settings_refuse(self, api: Api) -> None:
        http = api.http()
        _, headers = a_pharmacy(api, "APPROVED")
        _, waiting = a_pharmacy_more(api, "PENDING")

        closed_all_week = http.patch("/api/v1/pharmacy/me", json={"hours": []}, headers=headers)
        four_days = http.patch("/api/v1/pharmacy/me", json={"pickup_days": 4}, headers=headers)
        not_approved = http.patch("/api/v1/pharmacy/me", json={"pickup_days": 2}, headers=waiting)

        assert code_of(closed_all_week) == "VALIDATION_ERROR"
        assert four_days.status_code == 422
        assert (not_approved.status_code, code_of(not_approved)) == (403, "PHARMACY_NOT_APPROVED")


def a_pharmacy_more(api: Api, status: str) -> tuple[uuid.UUID, dict[str, str]]:
    owner = api.world.make.user("pharmacist", email_verified_at=api.world.clock.now())
    pharmacy = api.world.make.pharmacy(status, owner_user_id=owner)
    return pharmacy, login_of(api, pharmacy)
