"""The schema as a whole: tables, value lists, time, and the migration itself (docs/05)."""

import re
from enum import StrEnum
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, text

import dawalink.db.models  # noqa: F401  (registers every table)
from dawalink.db.base import Base
from dawalink.domain.accounts import ClientStatus, PharmacyStatus
from dawalink.domain.claims import ClaimState
from dawalink.domain.early_release import AskState, EarlyReleaseState
from dawalink.domain.inventory import ListingControl
from dawalink.domain.orders import OrderSource, OrderState
from dawalink.domain.requests import ItemState, RequestOutcome, RequestState
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import (
    AgentMode,
    BrandOrGeneric,
    ClaimKind,
    ClaimSource,
    CloseReason,
    ConversationKind,
    ConversationStatus,
    EscalationReason,
    EscalationState,
    FlagRule,
    FlagSeverity,
    FlagState,
    FlagSubject,
    LocationSource,
    MessageAuthor,
    MessageKind,
    OutboxState,
    ProposalKind,
    ReportState,
    RunOutcome,
    TravelMode,
    TravelSource,
    TurnTrigger,
    UploadStatus,
    UserRole,
)
from tests.conftest import DatabaseUrls, prepare_database, run_as_admin

# Every column that holds one value of a fixed list, and the rules' own list for it.
VALUE_LISTS: dict[tuple[str, str], type[StrEnum]] = {
    ("users", "role"): UserRole,
    ("client_profiles", "status"): ClientStatus,
    ("pharmacies", "status"): PharmacyStatus,
    ("products", "brand_generic"): BrandOrGeneric,
    ("inventory_uploads", "status"): UploadStatus,
    ("inventory_items", "listing_control"): ListingControl,
    ("orders", "state"): OrderState,
    ("orders", "source"): OrderSource,
    ("orders", "close_reason"): CloseReason,
    ("sourcing_requests", "state"): RequestState,
    ("sourcing_requests", "outcome"): RequestOutcome,
    ("sourcing_requests", "loc_source"): LocationSource,
    ("request_items", "state"): ItemState,
    ("claims", "kind"): ClaimKind,
    ("claims", "source"): ClaimSource,
    ("claims", "state"): ClaimState,
    ("early_release_requests", "state"): EarlyReleaseState,
    ("early_release_asks", "state"): AskState,
    ("conversations", "kind"): ConversationKind,
    ("conversations", "status"): ConversationStatus,
    ("conversations", "loc_source"): LocationSource,
    ("chat_messages", "author"): MessageAuthor,
    ("chat_messages", "kind"): MessageKind,
    ("proposals", "kind"): ProposalKind,
    ("agent_runs", "mode"): AgentMode,
    ("agent_runs", "trigger"): TurnTrigger,
    ("agent_runs", "outcome"): RunOutcome,
    ("answer_reports", "state"): ReportState,
    ("escalations", "reason"): EscalationReason,
    ("escalations", "state"): EscalationState,
    ("abuse_flags", "subject_type"): FlagSubject,
    ("abuse_flags", "rule"): FlagRule,
    ("abuse_flags", "severity"): FlagSeverity,
    ("abuse_flags", "state"): FlagState,
    ("email_outbox", "state"): OutboxState,
    ("audit_events", "actor_type"): Actor,
    ("travel_time_cache", "mode"): TravelMode,
    ("travel_time_cache", "source"): TravelSource,
}


def test_the_database_has_the_35_tables_of_the_design(db: Connection) -> None:
    in_database = set(
        db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars()
    ) - {"alembic_version"}

    assert in_database == set(Base.metadata.tables)
    assert len(in_database) == 35


@pytest.mark.parametrize(("table", "column"), sorted(VALUE_LISTS))
def test_each_value_list_in_the_database_is_the_rules_own_list(
    db: Connection, table: str, column: str
) -> None:
    """The migration is frozen text; this fails if a rule's list changes without a migration."""
    definition = db.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = :name AND conrelid = CAST(:table AS regclass)"
        ),
        {"name": f"ck_{table}_{column}_values", "table": table},
    ).scalar_one()

    in_database = set(re.findall(r"'([^']*)'", definition))

    assert in_database == {member.value for member in VALUE_LISTS[(table, column)]}


def test_every_checked_value_list_is_covered_by_the_test_above(db: Connection) -> None:
    checked = db.execute(
        text(
            "SELECT conrelid::regclass::text, conname FROM pg_constraint "
            "WHERE contype = 'c' AND conname LIKE '%\\_values'"
        )
    ).all()

    assert {
        (table, name.removeprefix(f"ck_{table}_").removesuffix("_values"))
        for table, name in checked
    } == set(VALUE_LISTS)


def test_every_constraint_has_a_test_that_tries_to_break_it(db: Connection) -> None:
    """docs/05 §10. A new constraint without a test in this folder fails here.

    Value lists are left out: the test above compares each of them with the rules' list.
    """
    names = db.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE contype IN ('c', 'u', 'x') AND connamespace = 'public'::regnamespace "
            "UNION SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexdef LIKE 'CREATE UNIQUE%' "
            "AND left(indexname, 3) <> 'pk_'"
        )
    ).scalars()
    tests = "".join(
        path.read_text(encoding="utf-8") for path in Path(__file__).parent.glob("test_*.py")
    )
    tables = sorted(Base.metadata.tables, key=len, reverse=True)

    def is_tested(name: str) -> bool:
        if name in tests:
            return True
        # A check may be named in a test without its "ck_<table>_" prefix.
        return any(
            name.startswith(f"ck_{table}_") and f'"{name.removeprefix(f"ck_{table}_")}"' in tests
            for table in tables
        )

    untested = sorted(
        name
        for name in names
        if not name.endswith("_values") and name != "alembic_version_pkc" and not is_tested(name)
    )

    assert untested == []


def test_no_table_has_a_priority_column(db: Connection) -> None:
    """Who gets scarce stock first can't be stored, so it can't be changed (R-PRI4, ADR-003)."""
    columns = db.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND "
            "(column_name ILIKE '%priorit%' OR column_name ILIKE '%urgen%' "
            " OR column_name ILIKE '%rank%')"
        )
    ).all()

    assert columns == []


def test_only_bookkeeping_times_default_to_the_database_clock(db: Connection) -> None:
    """Business times come from the app clock, never from the database's (DB-D6, R-T11)."""
    defaults = db.execute(
        text(
            "SELECT DISTINCT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name <> 'alembic_version' "
            "AND column_default ILIKE '%now()%'"
        )
    ).scalars()

    assert set(defaults) == {"created_at", "updated_at", "imported_at"}


OUR_FUNCTIONS = {
    "expiry_zone",
    "effective_price_lbp",
    "fits",
    "visible_listings",
    "area_rank",
    "orders_guard",
    "inventory_items_price_guard",
    "audit_events_append_only",
}


def test_no_function_reads_the_database_clock(db: Connection) -> None:
    """DB-D6 again: `today` and `now` are always passed in by the app."""
    sources: dict[str, str] = dict(
        db.execute(
            text(
                "SELECT proname, lower(prosrc) FROM pg_proc "
                "WHERE pronamespace = 'public'::regnamespace AND proname = ANY(:names)"
            ),
            {"names": sorted(OUR_FUNCTIONS)},
        ).all()
    )

    assert set(sources) == OUR_FUNCTIONS
    for name, source in sources.items():
        assert not re.search(r"current_date|current_time|now\(\)|clock_timestamp", source), name


def test_the_migration_goes_up_down_and_up_again_and_matches_the_models(
    development_urls: DatabaseUrls,
) -> None:
    """On a scratch database: up, down to nothing, up again, then compare with the models."""
    scratch = development_urls.on("dawalink_migration_test")
    run_as_admin(
        development_urls,
        'DROP DATABASE IF EXISTS "dawalink_migration_test" WITH (FORCE)',
        'CREATE DATABASE "dawalink_migration_test"',
    )
    try:
        prepare_database(scratch)
        config = Config(str(Path("alembic.ini")))
        config.attributes["database_url"] = scratch.migrator

        command.downgrade(config, "base")
        engine = create_engine(scratch.migrator)
        try:
            with engine.connect() as connection:
                left = connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars()
                assert set(left) == {"alembic_version"}
                functions = connection.execute(
                    text(
                        "SELECT count(*) FROM pg_proc p "
                        "WHERE p.pronamespace = 'public'::regnamespace AND NOT EXISTS ("
                        "  SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')"
                    )
                ).scalar_one()
                assert functions == 0
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        # Raises if the models and the migrated database differ.
        command.check(config)
    finally:
        run_as_admin(
            development_urls, 'DROP DATABASE IF EXISTS "dawalink_migration_test" WITH (FORCE)'
        )
