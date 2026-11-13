"""What every service builds on: the transaction, audit, notifications, events, the clock."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

from dawalink.domain.clock import ManualClock
from dawalink.domain.state_machine import Actor
from dawalink.services import audit, events
from dawalink.services.clock import OFFSET_KEY, AppClock, advance_demo_clock, demo_offset
from dawalink.services.context import unit_of_work
from dawalink.services.errors import Code, ServiceError
from dawalink.services.events import Decision
from dawalink.services.notify import Template, notify
from tests.conftest import DatabaseUrls
from tests.db.factories import NOW, TODAY
from tests.services.conftest import World


class TestTransaction:
    def test_time_comes_from_the_app_clock(self, world: World) -> None:
        tx = world.tx()

        assert (tx.now, tx.today) == (NOW, TODAY)
        world.later(hours=20)
        assert world.tx().today == TODAY + timedelta(days=1)

    def test_the_services_run_as_the_app_login(self, world: World) -> None:
        assert world.one("SELECT current_user AS login").login == "dawalink_app"
        with pytest.raises(ProgrammingError, match="permission denied"):
            world.one("UPDATE products SET controlled = false RETURNING id")

    def test_deferred_work_runs_once_per_key_after_the_transaction(self, world: World) -> None:
        ran: list[str] = []
        tx = world.tx()
        tx.defer("match:a", lambda later: ran.append("a"))
        tx.defer("match:a", lambda later: ran.append("a again"))
        tx.defer("match:b", lambda later: ran.append("b"))

        assert ran == []
        world.settle(tx)

        assert ran == ["a", "b"]

    def test_a_unit_of_work_commits_then_runs_deferred_work_in_new_transactions(
        self, urls: DatabaseUrls
    ) -> None:
        engine = create_engine(urls.app)
        sessions = sessionmaker(engine, expire_on_commit=False)
        clock = ManualClock(NOW)
        seen: list[tuple[str, bool]] = []
        try:
            with unit_of_work(sessions, clock) as tx:
                first = tx.session
                tx.defer("later", lambda later: seen.append(("later", later.session is first)))
                seen.append(("first", True))

            assert seen == [("first", True), ("later", False)]
        finally:
            engine.dispose()

    def test_an_error_rolls_everything_back_and_runs_nothing_deferred(
        self, urls: DatabaseUrls
    ) -> None:
        engine = create_engine(urls.app)
        sessions = sessionmaker(engine, expire_on_commit=False)
        ran: list[str] = []

        def fail_halfway() -> None:
            with unit_of_work(sessions, ManualClock(NOW)) as tx:
                audit.record(tx, Actor.SYSTEM, "test.rolled_back", "test", None)
                tx.defer("later", lambda later: ran.append("later"))
                raise ServiceError(Code.NOT_FOUND, "nothing here")

        try:
            with pytest.raises(ServiceError):
                fail_halfway()

            with sessions() as session:
                count = session.execute(
                    text("SELECT count(*) FROM audit_events WHERE action = 'test.rolled_back'")
                ).scalar()
            assert (count, ran) == (0, [])
        finally:
            engine.dispose()


@pytest.mark.rows_by_hand
def test_an_audit_event_names_its_actor_and_holds_states_only(world: World) -> None:
    client = world.make.client()
    order = world.make.order(client_id=client)

    audit.record(
        world.tx(),
        Actor.CLIENT,
        "order.cancel",
        "order",
        order,
        actor_id=client,
        before={"state": "RESERVED"},
        after={"state": "CANCELLED_BY_CLIENT"},
    )

    event = world.one("SELECT * FROM audit_events WHERE entity_id = :id", id=order)
    assert (event.actor_type, event.actor_id, event.action) == ("CLIENT", client, "order.cancel")
    assert (event.before, event.after) == ({"state": "RESERVED"}, {"state": "CANCELLED_BY_CLIENT"})
    assert event.occurred_at == NOW


class TestNotifications:
    def test_one_event_gives_one_notification_and_one_email(self, world: World) -> None:
        user = world.make.user()
        tx = world.tx()

        first = notify(tx, user, Template.RESERVED, {"order_ref": "R-7K3Q2F"}, event="order:1")
        again = notify(tx, user, Template.RESERVED, {"order_ref": "R-7K3Q2F"}, event="order:1")

        assert (first, again) == (True, False)
        assert world.notifications(user) == ["CN-3"]
        email = world.one("SELECT * FROM email_outbox WHERE user_id = :id", id=user)
        assert (email.template, email.state, email.next_attempt_at) == ("CN-3", "QUEUED", NOW)
        assert email.params == {"order_ref": "R-7K3Q2F"}

    def test_the_same_event_reaches_each_recipient(self, world: World) -> None:
        client, pharmacist = world.make.user(), world.make.user("pharmacist")
        tx = world.tx()

        notify(tx, client, Template.RESERVED, {"order_ref": "R-7K3Q2F"}, event="order:1")
        notify(tx, pharmacist, Template.NEW_RESERVATION, {"order_ref": "R-7K3Q2F"}, event="order:1")
        notify(
            tx,
            client,
            Template.NOT_AVAILABLE,
            {"order_ref": "R-7K3Q2F"},
            event="order:1:not-available:1",
        )
        notify(
            tx,
            client,
            Template.NOT_AVAILABLE,
            {"order_ref": "R-7K3Q2F"},
            event="order:1:not-available:2",
        )

        assert world.notifications(client) == ["CN-3", "CN-5", "CN-5"]
        assert world.notifications(pharmacist) == ["PN-4"]

    def test_a_notification_can_skip_the_email(self, world: World) -> None:
        user = world.make.user()

        notify(world.tx(), user, Template.PLAN_READY, {}, event="request:1", email=False)

        assert world.notifications(user) == ["CN-15"]
        assert world.all("SELECT 1 FROM email_outbox WHERE user_id = :id", id=user) == []


class TestConversationEvents:
    def messages(self, world: World, conversation: object) -> list[tuple[int, str, str]]:
        rows = world.all(
            "SELECT seq, author, kind FROM chat_messages WHERE conversation_id = :c ORDER BY seq",
            c=conversation,
        )
        return [tuple(row) for row in rows]

    def test_a_card_is_a_numbered_system_message_with_no_agent_turn(self, world: World) -> None:
        """R-AG3: informational events never call the LLM."""
        conversation = world.make.conversation()
        world.later(minutes=5)
        tx = world.tx()

        events.post_card(tx, conversation, "reserved", order_ref="R-7K3Q2F")
        events.post_card(tx, conversation, "picked_up", order_ref="R-7K3Q2F")

        assert self.messages(world, conversation) == [(1, "system", "card"), (2, "system", "card")]
        row = world.one("SELECT * FROM conversations WHERE id = :c", c=conversation)
        assert row.pending_turn_at is None
        assert row.last_activity_at == NOW + timedelta(minutes=5)
        card = world.one(
            "SELECT cards FROM chat_messages WHERE conversation_id = :c AND seq = 1",
            c=conversation,
        )
        assert card.cards == [{"template": "reserved", "order_ref": "R-7K3Q2F"}]

    def test_a_decision_event_asks_for_a_turn_once(self, world: World) -> None:
        """R-AG4: the event is a system message; the clock check will run the turn."""
        conversation = world.make.conversation()
        tx = world.tx()

        events.post_decision(tx, conversation, Decision.NOT_AVAILABLE, order_id="o-1", units=1)
        world.later(minutes=1)
        events.post_decision(world.tx(), conversation, Decision.WINDOW_CHECK, request_id="q-1")

        row = world.one("SELECT * FROM conversations WHERE id = :c", c=conversation)
        assert row.pending_turn_at == NOW
        body = world.one(
            "SELECT text_redacted FROM chat_messages WHERE conversation_id = :c AND seq = 1",
            c=conversation,
        )
        assert json.loads(body.text_redacted) == {
            "type": "not_available",
            "order_id": "o-1",
            "units": 1,
        }
        assert [m[2] for m in self.messages(world, conversation)] == ["event", "event"]

    def test_search_orders_never_reach_a_conversation(self, world: World) -> None:
        """R-AG5: the search page stays agent-free, which the evaluation baseline needs."""
        client = world.make.client()
        chat = world.make.conversation(client_id=client)
        tx = world.tx()

        from_search = events.conversation_for(
            tx, source="search", client_id=client, request_item_id=None
        )
        from_chat = events.conversation_for(
            tx, source="assistant", client_id=client, request_item_id=None
        )

        assert (from_search, from_chat) == (None, chat)
        events.post_card(tx, from_search, "reserved")
        events.post_decision(tx, from_search, Decision.NOT_AVAILABLE)
        assert self.messages(world, chat) == []

    def test_everything_about_a_request_goes_to_its_own_thread(self, world: World) -> None:
        client = world.make.client()
        world.make.conversation(client_id=client)
        request = world.make.request(client_id=client)
        thread = world.make.conversation(client_id=client, kind="request", request_id=request)
        item = world.make.request_item(request)

        found = events.conversation_for(
            world.tx(), source="request", client_id=client, request_item_id=item
        )

        assert found == thread

    def test_a_client_without_a_chat_gets_notifications_only(self, world: World) -> None:
        client = world.make.client()

        found = events.conversation_for(
            world.tx(), source="assistant", client_id=client, request_item_id=None
        )

        assert found is None


class TestDemoClock:
    def test_an_admin_moves_the_clock_forward_and_it_is_audited(self, world: World) -> None:
        """R-DEMO."""
        admin = world.make.user("admin", totp_secret=b"x")
        tx = world.tx()

        advance_demo_clock(tx, admin, timedelta(hours=2), demo_mode=True, reason="show an expiry")
        total = advance_demo_clock(
            tx, admin, timedelta(minutes=30), demo_mode=True, reason="and a no-show"
        )

        assert total == demo_offset(tx) == timedelta(hours=2, minutes=30)
        events_ = world.all("SELECT * FROM audit_events WHERE action = 'clock.advance' ORDER BY id")
        assert [e.after for e in events_] == [{"offset_seconds": 7200}, {"offset_seconds": 9000}]
        assert {(e.actor_type, e.actor_id) for e in events_} == {("ADMIN", admin)}

    def test_it_only_works_in_demo_mode_and_only_forward(self, world: World) -> None:
        admin = world.make.user("admin", totp_secret=b"x")

        with pytest.raises(ServiceError) as off:
            advance_demo_clock(world.tx(), admin, timedelta(hours=1), demo_mode=False, reason="x")
        with pytest.raises(ServiceError) as backwards:
            advance_demo_clock(world.tx(), admin, timedelta(hours=-1), demo_mode=True, reason="x")

        assert (off.value.code, backwards.value.code) == (Code.NOT_FOUND, Code.VALIDATION_ERROR)

    def test_the_app_clock_adds_the_offset_only_in_demo_mode(self, urls: DatabaseUrls) -> None:
        engine = create_engine(urls.admin)
        real = ManualClock(NOW)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO app_state (key, value) VALUES (:key, '10800') "
                        "ON CONFLICT (key) DO UPDATE SET value = '10800'"
                    ),
                    {"key": OFFSET_KEY},
                )

            assert AppClock(engine, demo_mode=True, real=real).now() == NOW + timedelta(hours=3)
            assert AppClock(engine, demo_mode=False, real=real).now() == NOW
        finally:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM app_state WHERE key = :key"), {"key": OFFSET_KEY}
                )
            engine.dispose()
