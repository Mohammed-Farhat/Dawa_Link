"""A client deletes their own account (docs/04 R-AU10; the owner, 2026-11-20).

What ends and in which order (as a suspension, but by the client's own hand), what is
erased at once, what the clean-up erases a moment later, what is kept, and that nothing
in flight can act for the account afterwards.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from dawalink.agent.llm.scripted import ScriptedModel
from dawalink.agent.pending import PendingTurns
from dawalink.agent.turn import Agent
from dawalink.domain.clock import beirut_date
from dawalink.domain.orders import OrderSource
from dawalink.domain.vocabulary import ClaimSource, EscalationReason
from dawalink.services import (
    account_deletion,
    auth,
    claims,
    daily,
    escalations,
    orders,
    proposals,
    search_history,
)
from dawalink.services.errors import Code, ServiceError
from dawalink.services.orders import ReserveLine
from dawalink.services.travel import shared_location
from tests.agent.conftest import no_sleep
from tests.api.conftest import PASSWORD, Api, code_of
from tests.fakes import FakeRouting

DELETE = "/api/v1/me/delete-account"
EMAIL = "rana@example.org"
PERSON = {"full_name": "Rana Khoury", "email": EMAIL, "phone": "+96170000001"}
NEAR = shared_location(33.896, 35.483)


@dataclass
class Leaving:
    """A client with something of every kind going, and the pharmacy that has it."""

    api: Api
    client: uuid.UUID
    owner: uuid.UUID
    reserved_box: uuid.UUID
    offered_box: uuid.UUID
    reservation: uuid.UUID
    request: uuid.UUID
    request_item: uuid.UUID
    thread: uuid.UUID
    watch: uuid.UUID
    offer: uuid.UUID
    chat: uuid.UUID
    message: int
    card: uuid.UUID
    escalation: uuid.UUID
    flag: uuid.UUID

    def one(self, statement: str, **values: Any) -> Any:
        return self.api.world.one(statement, **values)

    def state_of(self, order_id: uuid.UUID) -> str:
        return self.one("SELECT state FROM orders WHERE id = :id", id=order_id)[0]  # type: ignore[no-any-return]

    def reserved_units(self, box: uuid.UUID) -> int:
        return self.one("SELECT qty_reserved FROM inventory_items WHERE id = :id", id=box)[0]  # type: ignore[no-any-return]


@pytest.fixture
def leaving(api: Api) -> Leaving:
    world, make = api.world, api.world.make
    owner = make.user("pharmacist", email_verified_at=world.clock.now())
    pharmacy = make.pharmacy(owner_user_id=owner, lat=33.897, lon=35.484)
    reserved_product = make.product(moph_name="AUGMENTIN 1G", search_name="augmentin 1g")
    watched_product = make.product(moph_name="CONCOR 5MG", search_name="concor 5mg")
    asked_product = make.product(moph_name="PANADOL 500MG", search_name="panadol 500mg")
    reserved_box = make.item(
        pharmacy_id=pharmacy, product_id=reserved_product, days_left=60, qty_on_hand=5
    )
    client = api.client(**PERSON)
    with world.as_owner():
        world.connection.exec_driver_sql(
            "UPDATE client_profiles SET first_name = 'Rana', last_name = 'Khoury', "
            "birth_date = '1990-05-04', home_lat = 33.896, home_lon = 35.483 WHERE user_id = %s",
            (client,),
        )
        world.connection.exec_driver_sql(
            "UPDATE users SET signup_ip_hash = 'abc'::bytea WHERE id = %s", (client,)
        )

    # A reservation of 2 boxes.
    tx = world.tx()
    price = world.one(
        "SELECT price_lbp FROM visible_listings(:today) WHERE inventory_item_id = :id",
        today=beirut_date(world.clock.now()),
        id=reserved_box,
    )[0]
    (reservation,) = orders.reserve(
        tx,
        client_id=client,
        lines=[ReserveLine(reserved_box, 2, price)],
        pickup_day=beirut_date(world.clock.now()),
        source=OrderSource.SEARCH,
        idempotency_key=f"test-{uuid.uuid4()}",
    )
    search_history.record(tx, client, "augmentin")
    world.settle(tx)

    # A watch, and the offer matching made for it.
    offered_box = make.item(
        pharmacy_id=pharmacy, product_id=watched_product, days_left=60, qty_on_hand=1
    )
    tx = world.tx()
    watch = claims.create_watch(
        tx, client_id=client, product_id=watched_product, location=NEAR, source=ClaimSource.SEARCH
    )
    world.settle(tx)
    (offer,) = world.all("SELECT id FROM orders WHERE claim_id = :c", c=watch.id)

    # An open request, with a turn waiting in its thread.
    request = make.request(client_id=client, loc_lat=33.896, loc_lon=35.483, loc_source="shared")
    request_item = make.request_item(request, product_id=asked_product)
    thread = make.conversation(
        client_id=client,
        kind="request",
        request_id=request,
        pending_turn_at=world.clock.now(),
    )

    # A chat with a message, an open card, a follow-up the agent scheduled, a reported
    # answer, and a turn's measurements.
    chat = make.conversation(
        client_id=client,
        loc_lat=33.896,
        loc_lon=35.483,
        loc_source="shared",
        followup_at=world.clock.now() + timedelta(minutes=30),
    )
    run = make.agent_run(conversation_id=chat)
    with world.as_owner():
        (message,) = world.connection.exec_driver_sql(
            "INSERT INTO chat_messages (conversation_id, seq, author, kind, text_redacted) "
            "VALUES (%s, 1, 'client', 'text', 'baddi augmentin') RETURNING id",
            (chat,),
        ).one()
        (card,) = world.connection.exec_driver_sql(
            "INSERT INTO proposals (conversation_id, client_id, kind, payload, agent_run_id, "
            "expires_at) VALUES (%s, %s, 'cancel', %s::jsonb, %s, %s) RETURNING id",
            (
                chat,
                client,
                f'{{"order_id": "{reservation.id}"}}',
                run,
                world.clock.now() + timedelta(hours=2),
            ),
        ).one()
        world.connection.exec_driver_sql(
            "INSERT INTO answer_reports (message_id, client_id, reason, snapshot) "
            "VALUES (%s, %s, 'not_helpful', '{}'::jsonb)",
            (message, client),
        )
        (flag,) = world.connection.exec_driver_sql(
            "INSERT INTO abuse_flags (subject_type, subject_id, rule, severity, evidence) "
            "VALUES ('client', %s, 'guardrail_repeat', 'high', '{}'::jsonb) RETURNING id",
            (client,),
        ).one()
    tx = world.tx()
    escalated = escalations.escalate(
        tx,
        client_id=client,
        reason=EscalationReason.CLIENT_ASKED_HUMAN,
        summary="Asked to speak to a person.",
        conversation_id=chat,
    )
    world.settle(tx)
    return Leaving(
        api,
        client,
        owner,
        reserved_box,
        offered_box,
        reservation.id,
        request,
        request_item,
        thread,
        watch.id,
        offer.id,
        chat,
        message,
        card,
        escalated.escalation_id,
        flag,
    )


def delete(api: Api, login: dict[str, str], password: str = PASSWORD) -> Any:
    answer = api.http().post(DELETE, json={"password": password}, headers=login)
    api.world.settle(api.world.tx())
    return answer


class TestTheProof:
    def test_a_wrong_password_is_counted_logs_nobody_out_and_deletes_nothing(
        self, api: Api, leaving: Leaving
    ) -> None:
        """R-AU2: counted like a failed login, on the same counter. A stolen session
        alone can't delete the account."""
        login = api.token(leaving.client)

        wrong = delete(api, login, "Not the password, 9!")

        assert (wrong.status_code, code_of(wrong)) == (401, "INVALID_CREDENTIALS")
        assert (
            leaving.one("SELECT failed_logins FROM users WHERE id = :id", id=leaving.client)[0] == 1
        )
        assert api.http().get("/api/v1/auth/me", headers=login).status_code == 200
        assert leaving.one(
            "SELECT status FROM client_profiles WHERE user_id = :id", id=leaving.client
        )[0] == ("ACTIVE")
        assert leaving.state_of(leaving.reservation) == "RESERVED"

    def test_five_wrong_passwords_lock_it_like_a_login_and_still_log_nobody_out(
        self, api: Api, leaving: Leaving
    ) -> None:
        login = api.token(leaving.client)
        for _ in range(5):
            delete(api, login, "Not the password, 9!")

        locked = delete(api, login)

        assert (locked.status_code, code_of(locked)) == (429, "ACCOUNT_LOCKED")
        assert api.http().get("/api/v1/auth/me", headers=login).status_code == 200
        assert leaving.state_of(leaving.reservation) == "RESERVED"

    def test_a_pharmacist_and_an_admin_are_refused(self, api: Api, leaving: Leaving) -> None:
        """A pharmacy's account is a business record; an admin is managed by the command."""
        admin = api.world.make.user(
            "admin", totp_secret=b"not-a-real-secret", password_hash=auth.hash_password(PASSWORD)
        )
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (auth.hash_password(PASSWORD), leaving.owner),
            )

        for user in (leaving.owner, admin):
            refused = delete(api, api.token(user))
            assert (refused.status_code, code_of(refused)) == (403, "FORBIDDEN")
            row = leaving.one("SELECT email, full_name FROM users WHERE id = :id", id=user)
            assert not row.email.startswith(" ")

    def test_a_paused_client_may_delete_a_suspended_one_can_not(self, api: Api) -> None:
        """Rule 11. A suspended client has no session at all; the service refuses too."""
        now = api.world.clock.now()
        paused = api.world.make.client(
            "PAUSED",
            person={"password_hash": auth.hash_password(PASSWORD), "email_verified_at": now},
            paused_until=now + timedelta(days=3),
        )
        suspended = api.client("SUSPENDED")

        assert delete(api, api.token(paused)).status_code == 204
        with pytest.raises(ServiceError) as refused:
            account_deletion.delete_own_account(api.world.tx(), suspended, password=PASSWORD)
        assert refused.value.code is Code.ACCOUNT_SUSPENDED


class TestWhatEnds:
    def test_everything_they_had_going_ends_as_their_own_acts(
        self, api: Api, leaving: Leaving
    ) -> None:
        """The order of a suspension (requests and watches first), with the client's own
        end states. The packs go back, and the pharmacy is told as for any cancel."""
        deleted = delete(api, api.token(leaving.client))

        assert deleted.status_code == 204
        assert leaving.state_of(leaving.reservation) == "CANCELLED_BY_CLIENT"
        assert leaving.reserved_units(leaving.reserved_box) == 0
        assert "PN-8" in api.world.notifications(leaving.owner)
        assert leaving.state_of(leaving.offer) == "OFFER_WITHDRAWN"
        assert leaving.reserved_units(leaving.offered_box) == 0
        request = leaving.one(
            "SELECT state, outcome FROM sourcing_requests WHERE id = :id", id=leaving.request
        )
        assert tuple(request) == ("CLOSED", "CANCELLED")
        assert leaving.one(
            "SELECT state FROM request_items WHERE id = :id", id=leaving.request_item
        )[0] == ("CANCELLED")
        assert leaving.one("SELECT state FROM claims WHERE id = :id", id=leaving.watch)[0] == (
            "CANCELLED"
        )
        closings = api.world.all(
            "SELECT action, actor_type FROM audit_events WHERE entity_id IN (:r, :w, :o)",
            r=leaving.request,
            w=leaving.watch,
            o=leaving.reservation,
        )
        assert ("request.close", "CLIENT") in {(row.action, row.actor_type) for row in closings}
        assert ("order.cancel", "CLIENT") in {(row.action, row.actor_type) for row in closings}
        # Nothing opened again, and no missed pickup is counted.
        assert "request.reopen" not in api.world.audit_actions(leaving.request)
        assert (
            api.world.one(
                "SELECT count(*) FROM orders WHERE client_id = :c AND counts_as_no_show",
                c=leaving.client,
            )[0]
            == 0
        )
        # The books still add up (INV-2, INV-18).
        assert daily.books_that_are_off(api.world.tx()) == {"stock_off": [], "requests_off": []}

    def test_a_reservation_past_its_deadline_is_ended_without_a_missed_pickup(
        self, api: Api, leaving: Leaving
    ) -> None:
        """Its deadline passed a moment ago and the clock check hasn't called it a missed
        pickup yet: the client can't cancel it any more, and it must not count."""
        # The pharmacy closed at 21:00; it is 22:00, and no clock check has run.
        api.world.later(hours=12)

        assert delete(api, api.token(leaving.client)).status_code == 204
        assert leaving.state_of(leaving.reservation) == "CANCELLED_BY_SYSTEM"
        assert leaving.reserved_units(leaving.reserved_box) == 0
        assert (
            api.world.one(
                "SELECT count(*) FROM orders WHERE client_id = :c AND counts_as_no_show",
                c=leaving.client,
            )[0]
            == 0
        )


class TestWhatIsErasedAtOnce:
    def test_who_they_were_is_erased_and_every_device_is_logged_out(
        self, api: Api, leaving: Leaving
    ) -> None:
        login, other_device = api.token(leaving.client), api.token(leaving.client)

        delete(api, login)

        user = leaving.one("SELECT * FROM users WHERE id = :id", id=leaving.client)
        assert user.email == auth.deleted_email(leaving.client)
        assert (user.full_name, user.phone, user.signup_ip_hash) == ("Deleted account", None, None)
        assert user.password_hash == auth.DELETED_PASSWORD_HASH
        profile = leaving.one(
            "SELECT * FROM client_profiles WHERE user_id = :id", id=leaving.client
        )
        assert profile.status == "DELETED"
        assert profile.deleted_at is not None
        assert profile.emptied_at is None
        assert (profile.first_name, profile.middle_name, profile.last_name) == (None, None, None)
        assert (profile.birth_date, profile.district_id, profile.home_area_id) == (None, None, None)
        assert (profile.home_lat, profile.home_lon) == (None, None)
        assert (
            api.world.one(
                "SELECT count(*) FROM search_history WHERE client_id = :c", c=leaving.client
            )[0]
            == 0
        )
        for device in (login, other_device):
            assert api.http().get("/api/v1/auth/me", headers=device).status_code == 401
        # The locations kept on their request and watch go now, not in 30 days.
        assert (
            leaving.one("SELECT loc_lat FROM sourcing_requests WHERE id = :id", id=leaving.request)[
                0
            ]
            is None
        )
        assert leaving.one("SELECT loc_lat FROM claims WHERE id = :id", id=leaving.watch)[0] is None

    def test_their_open_case_and_flag_close(self, api: Api, leaving: Leaving) -> None:
        delete(api, api.token(leaving.client))

        case = leaving.one(
            "SELECT state, resolution_note FROM escalations WHERE id = :id", id=leaving.escalation
        )
        assert tuple(case) == ("RESOLVED", account_deletion.CLOSED_BY_DELETION)
        flag = leaving.one(
            "SELECT state, action, resolved_by FROM abuse_flags WHERE id = :id", id=leaving.flag
        )
        assert tuple(flag) == ("DISMISSED", None, None)

    def test_no_email_goes_to_them_and_the_pharmacy_is_still_told(
        self, api: Api, leaving: Leaving
    ) -> None:
        """Rule 9: the address is gone. What ending their things queued is dropped."""
        delete(api, api.token(leaving.client))

        waiting = api.world.all(
            "SELECT state FROM email_outbox WHERE user_id = :c AND state IN ('QUEUED', 'FAILED')",
            c=leaving.client,
        )
        sent = api.emails()

        assert waiting == []
        owner_email = leaving.one("SELECT email FROM users WHERE id = :id", id=leaving.owner)[0]
        assert [to for to, _, _ in sent if to != owner_email] == []
        assert any(to == owner_email for to, _, _ in sent)

    def test_an_email_queued_afterwards_is_dropped_not_sent(
        self, api: Api, leaving: Leaving
    ) -> None:
        delete(api, api.token(leaving.client))
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "INSERT INTO email_outbox (user_id, template, params, dedupe_key, next_attempt_at)"
                " VALUES (%s, 'CN-1', '{}'::jsonb, 'late-one', %s)",
                (leaving.client, api.world.clock.now()),
            )

        sent = api.emails()

        assert all(to != auth.deleted_email(leaving.client) for to, _, _ in sent)
        assert leaving.one("SELECT state FROM email_outbox WHERE dedupe_key = 'late-one'")[0] == (
            "DROPPED"
        )
        assert (
            api.world.one(
                "SELECT count(*) FROM email_verification_tokens "
                "WHERE user_id = :c AND used_at IS NULL",
                c=leaving.client,
            )[0]
            == 0
        )

    def test_the_audit_event_names_the_act_and_the_client_and_no_value(
        self, api: Api, leaving: Leaving
    ) -> None:
        delete(api, api.token(leaving.client))

        (event,) = api.world.all(
            "SELECT actor_type, actor_id, before, after FROM audit_events "
            "WHERE action = 'client.deleted' AND entity_id = :c",
            c=leaving.client,
        )
        assert (event.actor_type, event.actor_id) == ("CLIENT", leaving.client)
        assert event.before == {"status": "ACTIVE"}
        assert event.after == {
            "status": "DELETED",
            "orders_cancelled": 1,
            "requests_closed": 1,
            "watches_ended": 1,
            "escalations_closed": 1,
            "flags_closed": 1,
        }


class TestNothingInFlightActsForThem:
    def test_a_tap_on_an_old_card_does_nothing(self, api: Api, leaving: Leaving) -> None:
        login = api.token(leaving.client)
        delete(api, login)

        tapped = api.http().post(
            f"/api/v1/proposals/{leaving.card}/execute",
            json={},
            headers=login | {"Idempotency-Key": "late-tap"},
        )
        assert tapped.status_code == 401
        # Even with a session, the card itself has expired.
        with pytest.raises(ServiceError) as refused:
            proposals.execute(api.world.tx(), client_id=leaving.client, proposal_id=leaving.card)
        assert refused.value.code is Code.PROPOSAL_EXPIRED

    def test_a_scheduled_or_waiting_agent_turn_does_nothing(
        self, api: Api, leaving: Leaving
    ) -> None:
        agent = Agent(
            sessions=api.world.sessions(),
            clock=api.world.clock,
            model=ScriptedModel(),
            routing=FakeRouting(),
            sleep=no_sleep,
        )
        delete(api, api.token(leaving.client))
        api.world.later(hours=1)  # the follow-up's time has come
        runs_before = api.world.one("SELECT count(*) FROM agent_runs")[0]

        assert PendingTurns(agent).run_pending_turns() == 0
        assert api.world.one("SELECT count(*) FROM agent_runs")[0] == runs_before
        marks = api.world.all(
            "SELECT status, pending_turn_at, followup_at, turn_owner FROM conversations "
            "WHERE client_id = :c",
            c=leaving.client,
        )
        assert {tuple(row) for row in marks} == {("ARCHIVED", None, None, None)}

        # A mark written afterwards (by a turn that was running) wakes nothing either: the
        # worker only looks at conversations that are still active.
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE conversations SET pending_turn_at = %s WHERE id = %s",
                (api.world.clock.now(), leaving.thread),
            )
        assert PendingTurns(agent).due() == []
        assert PendingTurns(agent).run_pending_turns() == 0

    def test_a_change_already_past_the_login_check_writes_nothing_back(
        self, api: Api, leaving: Leaving
    ) -> None:
        """A request that passed the login check a moment before the deletion committed:
        here a session made afterwards stands for it. Nothing personal is written back
        onto the emptied rows, and the answer is a logged-out person's."""
        delete(api, api.token(leaving.client))
        in_flight = api.token(leaving.client)
        http = api.http()

        changed = http.patch(
            "/api/v1/me/profile",
            json={
                "first_name": "Rana",
                "last_name": "Khoury",
                "phone": "+96170000001",
                "birth_date": "1990-05-04",
                "district_id": 1,
            },
            headers=in_flight,
        )
        placed = http.put(
            "/api/v1/me/home-place", json={"lat": 33.896, "lon": 35.483}, headers=in_flight
        )
        cleared = http.delete("/api/v1/me/home-place", headers=in_flight)
        password = http.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": "A brand new passphrase, 3"},
            headers=in_flight,
        )

        assert [answer.status_code for answer in (changed, placed, cleared)] == [401] * 3
        assert code_of(changed) == "UNAUTHENTICATED"
        # No password matches a deleted account's: refused, and nothing is set.
        assert password.status_code == 401
        user = leaving.one("SELECT * FROM users WHERE id = :id", id=leaving.client)
        assert (user.full_name, user.phone) == ("Deleted account", None)
        assert user.password_hash == auth.DELETED_PASSWORD_HASH
        profile = leaving.one(
            "SELECT * FROM client_profiles WHERE user_id = :id", id=leaving.client
        )
        assert (profile.first_name, profile.last_name, profile.birth_date) == (None, None, None)
        assert (profile.district_id, profile.home_lat, profile.home_lon) == (None, None, None)

    def test_a_search_kept_just_after_the_deletion_is_not_kept(
        self, api: Api, leaving: Leaving
    ) -> None:
        """The same for the list of last searches: a name sent a moment after the
        deletion committed is refused, and nothing waits for the 30-day clean-up."""
        http = api.http()
        live = api.token(leaving.client)
        # While the account is there, the same calls clear and keep a search.
        assert http.delete("/api/v1/me/searches", headers=live).json()["items"] == []
        kept = http.post("/api/v1/me/searches", json={"q": "augmentin"}, headers=live)
        assert kept.json()["items"] == ["augmentin"]
        delete(api, live)
        in_flight = api.token(leaving.client)

        searched = http.post("/api/v1/me/searches", json={"q": "augmentin"}, headers=in_flight)
        cleared = http.delete("/api/v1/me/searches", headers=in_flight)

        assert [(answer.status_code, code_of(answer)) for answer in (searched, cleared)] == [
            (401, "UNAUTHENTICATED")
        ] * 2
        assert leaving.one(
            "SELECT count(*) FROM search_history WHERE client_id = :id", id=leaving.client
        ) == (0,)

    def test_a_turn_that_was_running_opens_no_case(self, api: Api, leaving: Leaving) -> None:
        """The agent's escalate tool, called after the deletion committed: refused."""
        delete(api, api.token(leaving.client))

        with pytest.raises(ServiceError) as refused:
            escalations.escalate(
                api.world.tx(),
                client_id=leaving.client,
                reason=EscalationReason.CANNOT_RESOLVE,
                summary="The client needs a person.",
            )

        assert refused.value.code is Code.NOT_FOUND
        assert api.world.one(
            "SELECT count(*) FROM escalations WHERE client_id = :c AND state <> 'RESOLVED'",
            c=leaving.client,
        ) == (0,)

    def test_nothing_can_be_reserved_or_started_for_them(self, api: Api, leaving: Leaving) -> None:
        """What a turn that was already running would try: every such tool asks whether
        the client may reserve."""
        delete(api, api.token(leaving.client))

        with pytest.raises(ServiceError) as refused:
            claims.create_watch(
                api.world.tx(),
                client_id=leaving.client,
                product_id=api.world.make.product(),
                location=NEAR,
                source=ClaimSource.ASSISTANT,
            )
        assert refused.value.code is Code.ACCOUNT_SUSPENDED


class TestAfterwards:
    def test_the_email_is_free_as_if_nobody_had_ever_used_it(
        self, api: Api, leaving: Leaving
    ) -> None:
        """Rule 7. A new sign-up is a new account; its missed pickups start at zero
        (accepted)."""
        delete(api, api.token(leaving.client))
        http = api.http()

        login = http.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        typed = auth.deleted_email(leaving.client).strip()
        placeholder = http.post("/api/v1/auth/login", json={"email": typed, "password": PASSWORD})
        reset = http.post("/api/v1/auth/password/forgot", json={"email": EMAIL})
        signed_up = http.post(
            "/api/v1/auth/register/client",
            json={
                "email": EMAIL,
                "password": "A brand new passphrase, 2",
                "first_name": "Rana",
                "last_name": "Khoury",
                "birth_date": "1990-05-04",
                "district_id": 1,
                "accept_terms": True,
            },
        )

        assert (login.status_code, code_of(login)) == (401, "INVALID_CREDENTIALS")
        assert (placeholder.status_code, code_of(placeholder)) == (401, "INVALID_CREDENTIALS")
        assert reset.status_code == 202
        assert signed_up.status_code == 202
        (new,) = api.world.all("SELECT id FROM users WHERE email = :e", e=EMAIL)
        assert new.id != leaving.client
        # Nothing was queued for the deleted account: not a reset, not "already registered".
        assert (
            api.world.one(
                "SELECT count(*) FROM email_outbox WHERE user_id = :c AND state = 'QUEUED'",
                c=leaving.client,
            )[0]
            == 0
        )

    def test_the_admin_sees_the_id_the_status_and_the_past_reservations_and_no_contact(
        self, api: Api, leaving: Leaving
    ) -> None:
        delete(api, api.token(leaving.client))
        admin = api.token(api.world.make.user("admin", totp_secret=b"not-a-real-secret"))
        http = api.http()

        page = http.get(f"/api/v1/admin/clients/{leaving.client}", headers=admin)
        listed = http.get("/api/v1/admin/clients?status=DELETED", headers=admin)
        contact = http.get(f"/api/v1/admin/clients/{leaving.client}/contact", headers=admin)

        assert page.status_code == 200
        assert page.json()["client"]["status"] == "DELETED"
        assert [row["state"] for row in page.json()["reservations"]] == ["CANCELLED_BY_CLIENT"]
        assert [row["id"] for row in listed.json()["items"]] == [str(leaving.client)]
        assert (contact.status_code, code_of(contact)) == (404, "NOT_FOUND")
        assert contact.json()["error"]["details"] == {"reason": "ACCOUNT_DELETED"}
        assert "Rana" not in contact.text
        assert api.world.one("SELECT count(*) FROM audit_events WHERE action = 'pii.view'")[0] == 0
        # Their case, closed by the deletion with no admin, still opens; and so does their
        # page once the clean-up has emptied the account.
        case = http.get(f"/api/v1/admin/escalations/{leaving.escalation}", headers=admin)
        assert case.status_code == 200
        assert api.world.clock_tasks().empty_deleted_accounts() == 1
        assert http.get(f"/api/v1/admin/clients/{leaving.client}", headers=admin).status_code == 200
        case = http.get(f"/api/v1/admin/escalations/{leaving.escalation}", headers=admin)
        assert case.status_code == 200

    def test_a_deleted_account_is_listed_last_and_never_needs_a_look(
        self, api: Api, leaving: Leaving
    ) -> None:
        """A contest it left behind waits for nobody (R-AU10)."""
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE orders SET contested_at = %s, counts_as_no_show = true WHERE id = %s",
                (api.world.clock.now(), leaving.reservation),
            )
        delete(api, api.token(leaving.client))
        someone = api.client()
        admin = api.token(api.world.make.user("admin", totp_secret=b"not-a-real-secret"))
        http = api.http()

        everyone = http.get("/api/v1/admin/clients", headers=admin).json()["items"]
        look = http.get("/api/v1/admin/clients?having=look", headers=admin).json()["items"]

        ids = [row["id"] for row in everyone]
        assert ids.index(str(someone)) < ids.index(str(leaving.client))
        assert ids[-1] == str(leaving.client)
        assert str(leaving.client) not in [row["id"] for row in look]


class TestTheCleanUp:
    def test_it_empties_what_the_app_may_not_delete_and_keeps_the_records(
        self, api: Api, leaving: Leaving
    ) -> None:
        """Run with the retention login, as the worker does, a moment after."""
        delete(api, api.token(leaving.client))

        emptied = api.world.clock_tasks().empty_deleted_accounts()
        again = api.world.clock_tasks().empty_deleted_accounts()

        assert (emptied, again) == (1, 0)
        for table, column in (
            ("conversations", "client_id"),
            ("notifications", "user_id"),
            ("email_outbox", "user_id"),
            ("sessions", "user_id"),
            ("email_verification_tokens", "user_id"),
            ("password_reset_tokens", "user_id"),
            ("search_history", "client_id"),
        ):
            count = api.world.one(
                f"SELECT count(*) FROM {table} WHERE {column} = :c",
                c=leaving.client,
            )[0]
            assert count == 0, table
        assert (
            api.world.one(
                "SELECT count(*) FROM chat_messages WHERE conversation_id IN (:a, :b)",
                a=leaving.chat,
                b=leaving.thread,
            )[0]
            == 0
        )
        assert (
            api.world.one("SELECT count(*) FROM proposals WHERE id = :id", id=leaving.card)[0] == 0
        )
        # Kept on purpose: they name nobody now.
        assert leaving.state_of(leaving.reservation) == "CANCELLED_BY_CLIENT"
        assert (
            api.world.one(
                "SELECT conversation_id FROM escalations WHERE id = :id", id=leaving.escalation
            )[0]
            is None
        )
        assert (
            api.world.one("SELECT count(*) FROM agent_runs WHERE conversation_id IS NULL")[0] >= 1
        )
        assert (
            api.world.one(
                "SELECT count(*) FROM answer_reports WHERE client_id = :c", c=leaving.client
            )[0]
            == 1
        )
        assert (
            api.world.one(
                "SELECT count(*) FROM audit_events WHERE entity_id = :c", c=leaving.client
            )[0]
            >= 1
        )
        assert (
            leaving.one(
                "SELECT emptied_at FROM client_profiles WHERE user_id = :c", c=leaving.client
            )[0]
            is not None
        )

    def test_without_the_retention_login_it_waits(self, api: Api, leaving: Leaving) -> None:
        delete(api, api.token(leaving.client))

        assert api.world.clock_tasks(retention=False).empty_deleted_accounts() == 0
        assert (
            api.world.one(
                "SELECT count(*) FROM conversations WHERE client_id = :c", c=leaving.client
            )[0]
            == 2
        )
