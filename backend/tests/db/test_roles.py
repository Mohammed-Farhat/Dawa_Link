"""The three database logins can do exactly what they should (docs/05 §7, DB-D10).

These tests connect as each login. Running them as the owner would prove nothing.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

import dawalink.db.models  # noqa: F401
from dawalink.db.base import Base
from dawalink.db.roles import (
    APP,
    MIGRATOR,
    RETENTION,
    RETENTION_DELETES,
    RETENTION_DELETES_FOUND_BY,
    RETENTION_ERASES,
    RETENTION_FINDS_DELETED,
    RETENTION_LOCKS,
    RETENTION_MARKS_EMPTIED,
    RoleSetupError,
    app_privileges,
    ensure_roles,
)
from dawalink.domain.numbers import DB_STATEMENT_TIMEOUT_S
from tests.conftest import DatabaseUrls
from tests.db import factories as make
from tests.db.factories import NOW


@pytest.fixture
def as_app(urls: DatabaseUrls) -> Iterator[Connection]:
    engine = create_engine(urls.app)
    with engine.connect() as connection:
        yield connection
        connection.rollback()
    engine.dispose()


@pytest.fixture
def as_retention(urls: DatabaseUrls) -> Iterator[Connection]:
    engine = create_engine(urls.retention)
    with engine.connect() as connection:
        yield connection
        connection.rollback()
    engine.dispose()


def denied(connection: Connection, statement: str) -> None:
    refusal = "permission denied|must be owner"
    with pytest.raises(ProgrammingError, match=refusal), connection.begin_nested():
        connection.execute(text(statement))


def test_every_table_has_a_decision_for_the_app_login() -> None:
    assert set(app_privileges()) == set(Base.metadata.tables)


def test_the_grants_in_the_database_are_exactly_the_lists(db: Connection) -> None:
    granted: dict[tuple[str, str], set[str]] = {}
    for role, table, privilege in db.execute(
        text(
            "SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'public' AND grantee IN (:app, :retention)"
        ),
        {"app": APP, "retention": RETENTION},
    ):
        granted.setdefault((role, table), set()).add(privilege)

    expected: dict[tuple[str, str], set[str]] = {
        (APP, table): set(privileges) for table, privileges in app_privileges().items()
    }
    expected |= {(RETENTION, table): {"SELECT", "DELETE"} for table in RETENTION_DELETES}
    expected |= {(RETENTION, table): {"SELECT"} for table in RETENTION_ERASES}
    # On these it may delete, and read a few columns only (checked below, by column).
    expected |= {(RETENTION, table): {"DELETE"} for table in RETENTION_DELETES_FOUND_BY}
    assert granted == expected

    by_column: dict[tuple[str, str], set[str]] = {}
    for table, column, privilege in db.execute(
        text(
            "SELECT table_name, column_name, privilege_type "
            "FROM information_schema.column_privileges "
            "WHERE table_schema = 'public' AND grantee = :retention AND table_name = ANY(:tables)"
        ),
        {"retention": RETENTION, "tables": list(RETENTION_DELETES_FOUND_BY)},
    ):
        by_column.setdefault((table, privilege), set()).add(column)
    assert by_column == {
        **{(table, "SELECT"): set(cols) for table, cols in RETENTION_DELETES_FOUND_BY.items()},
        **{(table, "UPDATE"): set(cols) for table, cols in RETENTION_LOCKS.items()},
    }

    # A deleted account (R-AU10): found by three columns of the profile, one of them set.
    profile_columns: dict[str, set[str]] = {}
    for column, privilege in db.execute(
        text(
            "SELECT column_name, privilege_type FROM information_schema.column_privileges "
            "WHERE table_schema = 'public' AND grantee = :retention "
            "AND table_name = 'client_profiles'"
        ),
        {"retention": RETENTION},
    ):
        profile_columns.setdefault(privilege, set()).add(column)
    assert profile_columns == {
        "SELECT": set(RETENTION_FINDS_DELETED["client_profiles"]),
        "UPDATE": set(RETENTION_MARKS_EMPTIED["client_profiles"]),
    }


class TestTheAppLogin:
    def test_it_reads_and_writes_rows(self, as_app: Connection) -> None:
        client = make.client(as_app)
        conversation = make.conversation(as_app, client_id=client)

        as_app.execute(
            text("UPDATE conversations SET status = 'ARCHIVED' WHERE id = :id"),
            {"id": conversation},
        )

        assert (
            as_app.execute(
                text("SELECT status FROM conversations WHERE id = :id"), {"id": conversation}
            ).scalar()
            == "ARCHIVED"
        )

    def test_it_cannot_change_the_schema(self, as_app: Connection) -> None:
        denied(as_app, "CREATE TABLE sneaky (id int)")
        denied(as_app, "ALTER TABLE orders ADD COLUMN priority int")
        denied(as_app, "DROP TABLE claims")
        denied(as_app, "ALTER TABLE orders DISABLE TRIGGER orders_guard")

    def test_it_adds_audit_events_and_can_never_change_or_delete_them(
        self, as_app: Connection
    ) -> None:
        as_app.execute(
            text(
                "INSERT INTO audit_events (occurred_at, actor_type, entity_type, action) "
                "VALUES (:now, 'SYSTEM', 'order', 'order.expire')"
            ),
            {"now": NOW},
        )

        denied(as_app, "UPDATE audit_events SET action = 'tampered'")
        denied(as_app, "DELETE FROM audit_events")
        denied(as_app, "TRUNCATE audit_events")

    def test_it_cannot_change_the_catalog_or_the_reference_data(self, as_app: Connection) -> None:
        """Prices and the controlled flag change only through the import."""
        assert as_app.execute(text("SELECT count(*) FROM districts")).scalar() == 26
        denied(as_app, "UPDATE products SET controlled = false")
        denied(as_app, "UPDATE products SET public_price_lbp = 1")
        denied(as_app, "UPDATE pricing_tiers SET discount_pct = 99")
        denied(as_app, "DELETE FROM districts")

    def test_it_cannot_delete_orders_or_claims(self, as_app: Connection) -> None:
        denied(as_app, "DELETE FROM orders")
        denied(as_app, "DELETE FROM claims")
        denied(as_app, "DELETE FROM users")

    def test_its_statements_are_cut_off_after_the_timeout(self, as_app: Connection) -> None:
        """N-40: nothing hangs on the database."""
        assert (
            as_app.execute(text("SHOW statement_timeout")).scalar() == f"{DB_STATEMENT_TIMEOUT_S}s"
        )

    def test_it_uses_the_price_and_visibility_functions(self, as_app: Connection) -> None:
        assert (
            as_app.execute(text("SELECT effective_price_lbp(1000000, NULL, 60)")).scalar()
            == 600_000
        )
        assert (
            as_app.execute(
                text("SELECT count(*) FROM visible_listings(DATE '2026-10-20')")
            ).scalar()
            is not None
        )


class TestTheRetentionLogin:
    def test_it_deletes_an_old_conversation_with_its_messages_and_keeps_the_run(
        self, urls: DatabaseUrls
    ) -> None:
        """docs/05 §8: the chat goes after 30 days; the turn's numbers stay, unlinked."""
        owner = create_engine(urls.migrator)
        retention = create_engine(urls.retention)
        try:
            with owner.begin() as connection:
                client = make.client(connection)
                conversation = make.conversation(connection, client_id=client)
                run = connection.execute(
                    text(
                        "INSERT INTO agent_runs "
                        "(conversation_id, mode, trigger, model, prompt_version, started_at) "
                        "VALUES (:c, 'assistant', 'client_message', 'fake', 'v1', :now) "
                        "RETURNING id"
                    ),
                    {"c": conversation, "now": NOW},
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO chat_messages "
                        "(conversation_id, seq, author, kind, text_redacted) "
                        "VALUES (:c, 1, 'client', 'text', 'baddi panadol')"
                    ),
                    {"c": conversation},
                )

            with retention.begin() as connection:
                connection.execute(
                    text("DELETE FROM conversations WHERE id = :c"), {"c": conversation}
                )

            with owner.begin() as connection:
                messages = connection.execute(
                    text("SELECT count(*) FROM chat_messages WHERE conversation_id = :c"),
                    {"c": conversation},
                ).scalar()
                kept = connection.execute(
                    text("SELECT conversation_id FROM agent_runs WHERE id = :r"), {"r": run}
                ).one()
                # This test commits, so it removes what it added.
                connection.execute(text("DELETE FROM agent_runs WHERE id = :r"), {"r": run})
                connection.execute(
                    text("DELETE FROM client_profiles WHERE user_id = :u"), {"u": client}
                )
                connection.execute(text("DELETE FROM users WHERE id = :u"), {"u": client})
            assert messages == 0
            assert kept[0] is None
        finally:
            owner.dispose()
            retention.dispose()

    def test_it_deletes_old_audit_events(self, urls: DatabaseUrls) -> None:
        """The only login that may, and its task decides the cutoff from the app clock."""
        owner = create_engine(urls.migrator)
        retention = create_engine(urls.retention)
        try:
            with owner.begin() as connection:
                event = connection.execute(
                    text(
                        "INSERT INTO audit_events (occurred_at, actor_type, entity_type, action) "
                        "VALUES (:then, 'SYSTEM', 'order', 'retention.test') RETURNING id"
                    ),
                    {"then": NOW.replace(year=2024)},
                ).scalar_one()
            with retention.begin() as connection:
                deleted = connection.execute(
                    text("DELETE FROM audit_events WHERE id = :id AND occurred_at < :cutoff"),
                    {"id": event, "cutoff": NOW.replace(year=2025)},
                ).rowcount
            assert deleted == 1
        finally:
            owner.dispose()
            retention.dispose()

    def test_it_cannot_change_an_audit_event_or_write_anything(
        self, as_retention: Connection
    ) -> None:
        denied(as_retention, "UPDATE audit_events SET action = 'tampered'")
        denied(
            as_retention,
            "INSERT INTO sessions (user_id, token_hash, expires_at) "
            "VALUES (gen_random_uuid(), 'x', now())",
        )
        denied(as_retention, "DELETE FROM orders")
        denied(as_retention, "SELECT email FROM users")

    def test_it_finds_an_unconfirmed_registration_without_reading_who_it_is(
        self, as_retention: Connection
    ) -> None:
        """The owner's Q49: it may delete a registration nobody confirmed. It reads the
        columns that find one, and nothing that says whose it is."""
        as_retention.execute(text("SELECT id, role, email_verified_at, created_at FROM users"))
        as_retention.execute(text("SELECT id, owner_user_id, status FROM pharmacies"))

        for statement in (
            "SELECT full_name FROM users",
            "SELECT phone FROM users",
            "SELECT password_hash FROM users",
            "SELECT totp_secret FROM users",
            "SELECT * FROM users",
            "SELECT name FROM pharmacies",
            "SELECT license_number FROM pharmacies",
            "SELECT phone FROM pharmacies",
            "SELECT params FROM email_outbox",
            "UPDATE users SET email = 'x@example.com'",
            "UPDATE users SET email_verified_at = now()",
            "UPDATE pharmacies SET status = 'APPROVED'",
            "DELETE FROM client_profiles",
            "DELETE FROM inventory_items",
        ):
            denied(as_retention, statement)

    def test_it_finds_a_deleted_account_without_reading_who_it_was(
        self, as_retention: Connection
    ) -> None:
        """R-AU10: it empties an account its client deleted. It reads the columns that
        find one, sets the one that says it is done, and reads nothing personal."""
        as_retention.execute(
            text(
                "SELECT user_id FROM client_profiles "
                "WHERE status = 'DELETED' AND emptied_at IS NULL FOR UPDATE"
            )
        )
        as_retention.execute(text("UPDATE client_profiles SET emptied_at = now() WHERE false"))

        for statement in (
            "SELECT first_name FROM client_profiles",
            "SELECT last_name FROM client_profiles",
            "SELECT birth_date FROM client_profiles",
            "SELECT home_lat, home_lon FROM client_profiles",
            "SELECT district_id FROM client_profiles",
            "SELECT deleted_at FROM client_profiles",
            "SELECT * FROM client_profiles",
            "UPDATE client_profiles SET status = 'ACTIVE'",
            "DELETE FROM client_profiles",
        ):
            denied(as_retention, statement)

    def test_it_cannot_delete_a_client_or_a_pharmacy_that_trades(
        self, urls: DatabaseUrls, as_retention: Connection
    ) -> None:
        """What hangs on them is in tables this login may not touch, so the database
        itself refuses."""
        owner = create_engine(urls.migrator)
        try:
            with owner.begin() as connection:
                client = make.client(connection)
                pharmacy = make.pharmacy(connection)
                box = make.item(connection, pharmacy_id=pharmacy)
            for statement, values in (
                ("DELETE FROM users WHERE id = :id", {"id": client}),
                ("DELETE FROM pharmacies WHERE id = :id", {"id": pharmacy}),
            ):
                with pytest.raises(IntegrityError), as_retention.begin_nested():
                    as_retention.execute(text(statement), values)
        finally:
            with owner.begin() as connection:
                # This test commits, so it removes what it added.
                (product,) = connection.execute(
                    text("SELECT product_id FROM inventory_items WHERE id = :i"), {"i": box}
                ).one()
                (pharmacist,) = connection.execute(
                    text("SELECT owner_user_id FROM pharmacies WHERE id = :p"), {"p": pharmacy}
                ).one()
                for statement, value in (
                    ("DELETE FROM inventory_items WHERE id = :v", box),
                    ("DELETE FROM products WHERE id = :v", product),
                    ("DELETE FROM pharmacy_hours WHERE pharmacy_id = :v", pharmacy),
                    ("DELETE FROM pharmacies WHERE id = :v", pharmacy),
                    ("DELETE FROM client_profiles WHERE user_id = :v", client),
                    ("DELETE FROM users WHERE id IN (:v, :w)", client),
                ):
                    connection.execute(text(statement), {"v": value, "w": pharmacist})
            owner.dispose()

    def test_it_erases_a_location_and_nothing_else_on_a_request(
        self, as_retention: Connection
    ) -> None:
        """docs/05 §8: the request is kept; the client's location on it is not."""
        as_retention.execute(
            text("UPDATE sourcing_requests SET loc_lat = NULL, loc_lon = NULL, loc_source = NULL")
        )
        as_retention.execute(text("UPDATE claims SET loc_lat = NULL, loc_lon = NULL"))

        denied(as_retention, "UPDATE sourcing_requests SET state = 'CLOSED'")
        denied(as_retention, "UPDATE claims SET qty_missing = 0")


def test_a_missing_password_is_refused_before_anything_runs() -> None:
    with pytest.raises(RoleSetupError, match="dawalink_migrator, dawalink_retention"):
        ensure_roles("postgresql+psycopg://x:y@127.0.0.1:1/z", {APP: "s3cret-value"})


def test_a_failed_login_setup_never_shows_a_password(urls: DatabaseUrls) -> None:
    """The failing statement holds the password, so the error must not repeat it (FX-17)."""
    passwords = {MIGRATOR: "s3cret-value", APP: "s3cret-value", RETENTION: "s3cret-value"}

    with pytest.raises(RoleSetupError) as error:
        # The app login may not create or alter logins, so the first statement fails.
        ensure_roles(urls.app, passwords)

    assert "s3cret-value" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__
