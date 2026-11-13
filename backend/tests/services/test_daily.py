"""The once-a-day tasks: retention and the stale-inventory reminder (docs/04 R-RET, N-16)."""

import uuid
from datetime import datetime, timedelta
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
        client = world.make.client()
        rows = {
            b"expired": {"expires_at": NOW - DAY},
            b"revoked": {"expires_at": NOW + DAY, "revoked_at": NOW - DAY},
            b"live": {"expires_at": NOW + DAY},
        }
        for token, values in rows.items():
            insert(world, "sessions", id=uuid.uuid4(), user_id=client, token_hash=token, **values)

        run(world)

        left = world.all("SELECT token_hash FROM sessions WHERE user_id = :id", id=client)
        assert [bytes(row.token_hash) for row in left] == [b"live"]

    def test_verification_links_go_once_used_or_expired(self, world: World) -> None:
        client = world.make.client()
        rows = {
            b"expired": {"expires_at": NOW - DAY},
            b"used": {"expires_at": NOW + DAY, "used_at": NOW - DAY},
            b"waiting": {"expires_at": NOW + DAY},
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
