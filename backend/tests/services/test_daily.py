"""The once-a-day tasks: retention and the stale-inventory reminder (docs/04 R-RET, N-16)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from dawalink.services import daily, inventory
from tests.conftest import logged
from tests.db.factories import NOW
from tests.services.conftest import World

DAY = timedelta(days=1)


def insert(world: World, table: str, **values: Any) -> None:
    """One row, written as the tables' owner."""
    columns = ", ".join(values)
    places = ", ".join(f":{name}" for name in values)
    with world.as_owner():
        world.connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({places})"), values)


def count(world: World, table: str, where: str = "TRUE", **values: Any) -> int:
    return int(world.one(f"SELECT count(*) AS n FROM {table} WHERE {where}", **values).n)


def run(world: World) -> int:
    return world.clock_tasks().run_daily_tasks()


class TestOnceADay:
    def test_they_run_once_per_day(self, world: World) -> None:
        insert(
            world,
            "notifications",
            user_id=world.make.client(),
            type="CN-3",
            dedupe_key="a",
            created_at=NOW - 91 * DAY,
        )

        assert run(world) == 1
        assert run(world) == 0

        world.later(hours=3)
        assert run(world) == 0

    def test_they_run_again_the_next_day_in_beirut(self, world: World) -> None:
        run(world)  # 10:00 in Beirut
        world.later(hours=13, minutes=59)  # 23:59
        insert(
            world,
            "notifications",
            user_id=world.make.client(),
            type="CN-3",
            dedupe_key="a",
            created_at=NOW - 91 * DAY,
        )
        assert run(world) == 0

        world.later(minutes=1)  # midnight in Beirut
        assert run(world) == 1

    def test_without_the_retention_login_nothing_is_deleted(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        insert(
            world,
            "notifications",
            user_id=world.make.client(),
            type="CN-3",
            dedupe_key="a",
            created_at=NOW - 91 * DAY,
        )

        assert world.clock_tasks(retention=False).run_daily_tasks() == 0

        assert count(world, "notifications") == 1
        assert len(logged(caplog, "retention_skipped")) == 1

    def test_the_app_login_may_not_purge(self, world: World) -> None:
        with (
            pytest.raises(ProgrammingError, match="permission denied"),
            world.session.begin_nested(),
        ):
            daily.purge(world.tx())


class TestWhenThePurgeFails:
    """docs/09 FO-4."""

    def test_the_rest_of_the_day_is_done_and_the_next_day_deletes_what_was_left(
        self, world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        insert(
            world,
            "notifications",
            user_id=world.make.client(),
            type="CN-3",
            dedupe_key="a",
            created_at=NOW - 91 * DAY,
        )
        stale = world.make.pharmacy()
        world.make.item(pharmacy_id=stale, last_edited_at=NOW - 8 * DAY)
        purge = daily.purge

        def failing(_: Any) -> dict[str, int]:
            raise RuntimeError("the retention login was refused")

        monkeypatch.setattr(daily, "purge", failing)
        first = run(world)
        again_the_same_day = run(world)
        world.later(days=1)
        second = run(world)
        failed_twice = daily.last_checks(world.tx())
        monkeypatch.setattr(daily, "purge", purge)
        world.later(days=1)
        third = run(world)

        # The reminder went out on the first day; the failed purge is not tried again
        # that day, and is counted day after day until it works.
        assert (first, again_the_same_day, second) == (1, 0, 0)
        assert world.notifications(
            world.one("SELECT owner_user_id AS id FROM pharmacies WHERE id = :id", id=stale).id
        ) == ["PN-10"]
        assert len(logged(caplog, "retention_failed")) == 2
        assert failed_twice["retention_failed_days"] == 2
        assert third >= 1
        assert count(world, "notifications", "type = 'CN-3'") == 0
        assert daily.last_checks(world.tx())["retention_failed_days"] == 0


class TestTheBooks:
    """docs/09 FO-3, docs/05 §4: once a day, every count is compared with what it counts."""

    def test_books_that_add_up_are_quiet(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        world.make.item()

        run(world)

        kept = daily.last_checks(world.tx())
        assert (kept["stock_off_count"], kept["requests_off_count"]) == (0, 0)
        assert kept["day"] == world.tx().today.isoformat()
        assert logged(caplog, "books_do_not_add_up") == []

    @pytest.mark.rows_by_hand
    def test_a_box_whose_reserved_count_is_wrong_is_named_and_left_as_it_is(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        fine = world.make.item(qty_on_hand=5)
        off = world.make.item(qty_on_hand=5)
        with world.as_owner():
            # Two units reserved, and no reservation that holds them.
            world.connection.execute(
                text("UPDATE inventory_items SET qty_reserved = 2 WHERE id = :id"), {"id": off}
            )

        run(world)

        kept = daily.last_checks(world.tx())
        assert kept["stock_off"] == [str(off)]
        assert str(fine) not in kept["stock_off"]
        (said,) = logged(caplog, "books_do_not_add_up")
        assert (said["stock_off"], said["stock_off_count"]) == ([str(off)], 1)
        # Read only: the wrong count is for a person to look into.
        assert (
            world.one("SELECT qty_reserved AS n FROM inventory_items WHERE id = :id", id=off).n == 2
        )


class TestRegistrationsNobodyConfirmed:
    """The owner, 2026-11-17 (Q49); docs/10 RR-18: a licence number and a phone belong to
    one pharmacy, so a registration that was never confirmed must not keep them."""

    def registration(
        self, world: World, *, hours_ago: float, confirmed: bool = False, **details: Any
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """A pharmacy that waits, registered so many hours ago: `(pharmacy, its user)`."""
        pharmacy: uuid.UUID = world.make.pharmacy("PENDING", **details)
        user = world.one("SELECT owner_user_id AS id FROM pharmacies WHERE id = :p", p=pharmacy).id
        with world.as_owner():
            world.connection.execute(
                text(
                    "UPDATE users SET created_at = now() - make_interval(secs => :s), "
                    "email_verified_at = CASE WHEN :c THEN now() END WHERE id = :u"
                ),
                {"s": hours_ago * 3600, "c": confirmed, "u": user},
            )
        return pharmacy, user

    def link(self, world: World, user: uuid.UUID, *, good_for_hours: float) -> None:
        insert(
            world,
            "email_verification_tokens",
            id=uuid.uuid4(),
            user_id=user,
            token_hash=uuid.uuid4().bytes,
            expires_at=datetime.now(UTC) + timedelta(hours=good_for_hours),
        )

    def email(self, world: World, user: uuid.UUID, state: str) -> None:
        insert(
            world,
            "email_outbox",
            user_id=user,
            template="CN-1",
            dedupe_key=f"confirm-{uuid.uuid4()}",
            state=state,
            next_attempt_at=NOW,
        )

    def test_it_goes_with_everything_that_hung_on_it_and_its_licence_is_free_again(
        self, world: World
    ) -> None:
        pharmacy, user = self.registration(
            world, hours_ago=25, license_number="LB-777", phone="+96170555123"
        )
        # Everything a registration can leave behind before anyone approves it.
        self.link(world, user, good_for_hours=-1)
        self.email(world, user, "SENT")
        insert(world, "notifications", user_id=user, type="PN-1", dedupe_key="n", created_at=NOW)
        insert(
            world,
            "sessions",
            id=uuid.uuid4(),
            user_id=user,
            token_hash=uuid.uuid4().bytes,
            expires_at=datetime.now(UTC) + DAY,
        )

        run(world)

        assert count(world, "users", "id = :u", u=user) == 0
        assert count(world, "pharmacies", "id = :p", p=pharmacy) == 0
        assert count(world, "pharmacy_hours", "pharmacy_id = :p", p=pharmacy) == 0
        for table in ("sessions", "email_outbox", "notifications", "email_verification_tokens"):
            assert count(world, table, "user_id = :u", u=user) == 0, table
        # The real pharmacy can register with its own licence and phone now.
        again = world.make.pharmacy("PENDING", license_number="LB-777", phone="+96170555123")
        assert count(world, "pharmacies", "id = :p", p=again) == 1

    def test_what_is_kept(self, world: World) -> None:
        """Still within the link's 24 hours; confirmed, however long it waits for an
        admin; a new link that is still good; an email that was never sent; a client."""
        young, _ = self.registration(world, hours_ago=23)
        confirmed, _ = self.registration(world, hours_ago=200, confirmed=True)
        asked_again, asking = self.registration(world, hours_ago=30)
        self.link(world, asking, good_for_hours=10)
        never_mailed, unmailed = self.registration(world, hours_ago=30)
        self.email(world, unmailed, "FAILED")
        client = world.make.client("UNVERIFIED")
        with world.as_owner():
            world.connection.execute(
                text("UPDATE users SET created_at = now() - interval '30 hours' WHERE id = :u"),
                {"u": client},
            )
        approved = world.make.pharmacy()

        run(world)

        kept = {row.id for row in world.all("SELECT id FROM pharmacies")}
        assert kept >= {young, confirmed, asked_again, never_mailed, approved}
        assert count(world, "users", "id = :u", u=client) == 1

    def test_the_demo_clock_never_ages_a_registration(self, world: World) -> None:
        """R-T11: a link's 24 hours are real hours. Moving the app's clock three days on,
        as a demo does, deletes nobody who registered a minute ago."""
        pharmacy, _ = self.registration(world, hours_ago=0.1)

        world.later(days=3)
        run(world)

        assert count(world, "pharmacies", "id = :p", p=pharmacy) == 1


class TestConversations:
    def chat(self, world: World, last_activity: datetime) -> uuid.UUID:
        conversation: uuid.UUID = world.make.conversation(last_activity_at=last_activity)
        client = world.one("SELECT client_id FROM conversations WHERE id = :id", id=conversation)
        insert(
            world,
            "chat_messages",
            conversation_id=conversation,
            seq=1,
            author="client",
            kind="text",
            text_redacted="hello",
        )
        insert(
            world,
            "proposals",
            id=uuid.uuid4(),
            conversation_id=conversation,
            client_id=client.client_id,
            kind="reserve",
            payload="{}",
            expires_at=last_activity + timedelta(hours=2),
        )
        return conversation

    def test_a_chat_goes_30_days_after_its_last_activity(self, world: World) -> None:
        old = self.chat(world, NOW - 30 * DAY - timedelta(minutes=1))
        recent = self.chat(world, NOW - 30 * DAY + timedelta(minutes=1))

        run(world)

        assert count(world, "conversations", "id = :id", id=old) == 0
        assert count(world, "chat_messages", "conversation_id = :id", id=old) == 0
        assert count(world, "proposals", "conversation_id = :id", id=old) == 0
        assert count(world, "conversations", "id = :id", id=recent) == 1
        assert count(world, "chat_messages", "conversation_id = :id", id=recent) == 1
        assert count(world, "proposals", "conversation_id = :id", id=recent) == 1

    def test_a_requests_thread_goes_30_days_after_the_request_closed(self, world: World) -> None:
        closed_long_ago = world.make.request(
            state="CLOSED", outcome="UNFULFILLED", closed_at=NOW - 31 * DAY
        )
        closed_recently = world.make.request(
            state="CLOSED", outcome="UNFULFILLED", closed_at=NOW - 29 * DAY
        )
        still_open = world.make.request()
        threads = {
            request: world.make.conversation(
                kind="request", request_id=request, last_activity_at=NOW - 60 * DAY
            )
            for request in (closed_long_ago, closed_recently, still_open)
        }

        run(world)

        assert count(world, "conversations", "id = :id", id=threads[closed_long_ago]) == 0
        assert count(world, "conversations", "id = :id", id=threads[closed_recently]) == 1
        assert count(world, "conversations", "id = :id", id=threads[still_open]) == 1
        # The request itself is kept.
        assert count(world, "sourcing_requests", "id = :id", id=closed_long_ago) == 1

    def test_the_agents_run_is_kept_without_its_conversation(self, world: World) -> None:
        """docs/05 §8: the metrics carry no personal data, so they outlive the chat."""
        conversation = self.chat(world, NOW - 31 * DAY)
        run_id = uuid.uuid4()
        insert(
            world,
            "agent_runs",
            id=run_id,
            conversation_id=conversation,
            mode="assistant",
            trigger="client_message",
            model="fake",
            prompt_version="v0",
            started_at=NOW - 31 * DAY,
        )

        run(world)

        kept = world.one("SELECT conversation_id FROM agent_runs WHERE id = :id", id=run_id)
        assert kept.conversation_id is None


class TestLocations:
    def test_the_location_is_erased_30_days_after_a_request_closed(self, world: World) -> None:
        where = {"loc_lat": 33.894, "loc_lon": 35.502, "loc_source": "shared"}
        old = world.make.request(
            state="CLOSED", outcome="UNFULFILLED", closed_at=NOW - 31 * DAY, **where
        )
        recent = world.make.request(
            state="CLOSED", outcome="UNFULFILLED", closed_at=NOW - 29 * DAY, **where
        )
        still_open = world.make.request(**where)

        run(world)

        row = world.one("SELECT * FROM sourcing_requests WHERE id = :id", id=old)
        assert (row.loc_lat, row.loc_lon, row.loc_source) == (None, None, None)
        for kept in (recent, still_open):
            assert world.one("SELECT loc_lat FROM sourcing_requests WHERE id = :id", id=kept)[0]

    def test_the_location_is_erased_30_days_after_a_claim_closed(self, world: World) -> None:
        where = {"loc_lat": 33.894, "loc_lon": 35.502}
        old = world.make.claim(state="EXPIRED", closed_at=NOW - 31 * DAY, **where)
        waiting = world.make.claim(**where)

        run(world)

        row = world.one("SELECT loc_lat, loc_lon FROM claims WHERE id = :id", id=old)
        assert (row.loc_lat, row.loc_lon) == (None, None)
        assert world.one("SELECT loc_lat FROM claims WHERE id = :id", id=waiting)[0]


class TestOtherRows:
    def test_notifications_go_after_90_days(self, world: World) -> None:
        client = world.make.client()
        insert(
            world,
            "notifications",
            user_id=client,
            type="CN-3",
            dedupe_key="old",
            created_at=NOW - 91 * DAY,
        )
        insert(
            world,
            "notifications",
            user_id=client,
            type="CN-3",
            dedupe_key="recent",
            created_at=NOW - 89 * DAY,
        )

        run(world)

        assert [row.dedupe_key for row in world.all("SELECT dedupe_key FROM notifications")] == [
            "recent"
        ]

    def test_sessions_go_once_expired_or_revoked(self, world: World) -> None:
        """Logins are counted in real time (R-T11), whatever the app clock says."""
        client = world.make.client()
        real = datetime.now(UTC)
        rows = {
            b"expired": {"expires_at": real - DAY},
            b"revoked": {"expires_at": real + DAY, "revoked_at": real - DAY},
            b"live": {"expires_at": real + DAY},
        }
        for token, values in rows.items():
            insert(world, "sessions", id=uuid.uuid4(), user_id=client, token_hash=token, **values)
        # The demo clock jumps far ahead: a session that is still good must survive it.
        world.later(days=60)

        run(world)

        left = world.all("SELECT token_hash FROM sessions WHERE user_id = :id", id=client)
        assert [bytes(row.token_hash) for row in left] == [b"live"]

    def test_verification_links_go_once_used_or_expired(self, world: World) -> None:
        client = world.make.client()
        real = datetime.now(UTC)
        rows = {
            b"expired": {"expires_at": real - DAY},
            b"used": {"expires_at": real + DAY, "used_at": real - DAY},
            b"waiting": {"expires_at": real + DAY},
        }
        for token, values in rows.items():
            insert(
                world,
                "email_verification_tokens",
                id=uuid.uuid4(),
                user_id=client,
                token_hash=token,
                **values,
            )

        run(world)

        left = world.all("SELECT token_hash FROM email_verification_tokens")
        assert [bytes(row.token_hash) for row in left] == [b"waiting"]

    def test_reset_links_go_once_used_or_expired_in_real_time(self, world: World) -> None:
        """R-AU9: a link that is still good survives a demo clock moved a week ahead."""
        client = world.make.client()
        real = datetime.now(UTC)
        rows = {
            b"expired": {"expires_at": real - timedelta(minutes=1)},
            b"used": {"expires_at": real + timedelta(minutes=20), "used_at": real},
            b"waiting": {"expires_at": real + timedelta(minutes=20)},
        }
        for token, values in rows.items():
            insert(
                world,
                "password_reset_tokens",
                id=uuid.uuid4(),
                user_id=client,
                token_hash=token,
                **values,
            )
        world.later(days=7)

        run(world)

        left = world.all("SELECT token_hash FROM password_reset_tokens")
        assert [bytes(row.token_hash) for row in left] == [b"waiting"]

    def test_travel_times_go_after_24_hours(self, world: World) -> None:
        pharmacy = world.make.pharmacy()
        for cell, age in (("33.894,35.502", 25), ("33.895,35.502", 23)):
            insert(
                world,
                "travel_time_cache",
                pharmacy_id=pharmacy,
                origin_cell=cell,
                mode="car",
                minutes=10,
                km=4,
                source="road",
                computed_at=NOW - timedelta(hours=age),
            )

        run(world)

        left = world.all("SELECT origin_cell FROM travel_time_cache")
        assert [row.origin_cell for row in left] == ["33.895,35.502"]

    def test_a_skip_goes_when_it_has_passed(self, world: World) -> None:
        past, ahead = world.make.claim(), world.make.claim()
        item = world.make.item()
        insert(world, "claim_skips", claim_id=past, inventory_item_id=item, skip_until=NOW - DAY)
        insert(world, "claim_skips", claim_id=ahead, inventory_item_id=item, skip_until=NOW + DAY)

        run(world)

        assert [row.claim_id for row in world.all("SELECT claim_id FROM claim_skips")] == [ahead]

    def test_the_audit_log_is_kept_a_year(self, world: World) -> None:
        for reason, age in (("old", 366), ("recent", 364)):
            insert(
                world,
                "audit_events",
                occurred_at=NOW - age * DAY,
                actor_type="SYSTEM",
                entity_type="order",
                action="test.event",
                reason=reason,
            )

        run(world)

        left = world.all("SELECT reason FROM audit_events WHERE action = 'test.event'")
        assert [row.reason for row in left] == ["recent"]


class TestStaleInventory:
    def stock(self, world: World, *, edited: datetime, **pharmacy: Any) -> uuid.UUID:
        """A pharmacy whose only box was last touched at `edited`. Returns its owner."""
        pharmacy_id = world.make.pharmacy(**pharmacy)
        world.make.item(pharmacy_id=pharmacy_id, last_edited_at=edited)
        owner: uuid.UUID = world.one(
            "SELECT owner_user_id FROM pharmacies WHERE id = :id", id=pharmacy_id
        ).owner_user_id
        return owner

    def test_a_pharmacy_is_reminded_after_a_week_without_a_change(self, world: World) -> None:
        """N-16, PN-10."""
        stale = self.stock(world, edited=NOW - 7 * DAY - timedelta(minutes=1))
        fresh = self.stock(world, edited=NOW - 7 * DAY + timedelta(minutes=1))

        run(world)

        assert world.notifications(stale) == ["PN-10"]
        assert world.notifications(fresh) == []

    def test_the_newest_change_is_what_counts(self, world: World) -> None:
        pharmacy = world.make.pharmacy()
        world.make.item(pharmacy_id=pharmacy, last_edited_at=NOW - 30 * DAY)
        world.make.item(pharmacy_id=pharmacy, last_edited_at=NOW - DAY)
        owner = world.one("SELECT owner_user_id FROM pharmacies WHERE id = :id", id=pharmacy)

        run(world)

        assert world.notifications(owner.owner_user_id) == []

    def test_at_most_one_reminder_a_week(self, world: World) -> None:
        owner = self.stock(world, edited=NOW - 8 * DAY)  # NOW is a Tuesday

        for _ in range(6):  # Tuesday to Sunday
            run(world)
            world.later(days=1)
        assert world.notifications(owner) == ["PN-10"]

        run(world)  # Monday: a new week
        assert world.notifications(owner) == ["PN-10", "PN-10"]

    def test_an_edit_ends_the_reminders(self, world: World) -> None:
        pharmacy = world.make.pharmacy()
        item = world.make.item(pharmacy_id=pharmacy, last_edited_at=NOW - 8 * DAY)
        owner = world.one("SELECT owner_user_id FROM pharmacies WHERE id = :id", id=pharmacy)
        run(world)

        tx = world.tx()
        inventory.edit_item(tx, pharmacy, item, quantity=4)
        world.settle(tx)
        world.later(days=7)
        run(world)

        assert world.notifications(owner.owner_user_id) == ["PN-10"]

    def test_a_pharmacy_that_is_not_approved_is_left_alone(self, world: World) -> None:
        owner = self.stock(world, edited=NOW - 30 * DAY, status="SUSPENDED")

        run(world)

        assert world.notifications(owner) == []
