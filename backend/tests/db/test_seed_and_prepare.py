"""Reference data, the demo seed and the whole preparation step (docs/05 §9, docs/12 §7)."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, text

from dawalink.catalog.moph import CatalogRow, write_catalog
from dawalink.config import ConfigError
from dawalink.db.reference import read_districts, seed_districts, seed_pricing_tiers
from dawalink.domain.numbers import DISCOUNT_TIERS, NEAR_EXPIRY_MAX_DAYS
from dawalink.ops.build_catalog import CATALOG_FILE, DETAILS_FILE
from dawalink.ops.prepare_db import login_passwords, prepare
from dawalink.ops.seed_demo import seed_demo
from tests.conftest import DatabaseUrls, make_settings, run_as_admin
from tests.db import factories as make
from tests.db.factories import NOW, TODAY


class TestReferenceData:
    def test_lebanon_has_26_districts_in_9_governorates(self) -> None:
        districts = read_districts()

        assert len(districts) == 26
        assert len({d["id"] for d in districts}) == len({d["name"] for d in districts}) == 26
        assert len({d["governorate"] for d in districts}) == 9

    def test_every_reference_point_is_inside_lebanon(self) -> None:
        for district in read_districts():
            assert 33.0 <= float(district["ref_lat"]) <= 34.7, district["name"]  # type: ignore[arg-type]
            assert 35.1 <= float(district["ref_lon"]) <= 36.7, district["name"]  # type: ignore[arg-type]

    def test_writing_it_twice_changes_nothing(self, db: Connection) -> None:
        seed_pricing_tiers(db)
        seed_districts(db)

        tiers = db.execute(text("SELECT min_days, max_days, discount_pct FROM pricing_tiers")).all()
        assert sorted(tuple(t) for t in tiers) == sorted(DISCOUNT_TIERS)
        assert db.execute(text("SELECT count(*) FROM districts")).scalar() == 26

    def test_the_tiers_cover_the_whole_published_window_without_a_gap(self) -> None:
        """Every visible box has a price: days 0 to 180 each fall in exactly one tier (N-1, N-4)."""
        for days in range(NEAR_EXPIRY_MAX_DAYS + 1):
            assert sum(low <= days <= high for low, high, _ in DISCOUNT_TIERS) == 1, days


def stock_some_products(db: Connection, count: int = 12) -> None:
    key = "paracetamol=500mg | tablet"
    for number in range(count):
        make.product(db, equivalence_key=key if number < 6 else None)
    make.product(db, controlled=True, equivalence_key=key)


def snapshot(db: Connection) -> dict[str, Sequence[Any]]:
    return {
        "pharmacies": db.execute(
            text("SELECT id, name, lat, lon, pickup_days FROM pharmacies ORDER BY license_number")
        ).all(),
        "hours": db.execute(
            text("SELECT * FROM pharmacy_hours ORDER BY pharmacy_id, weekday, seq")
        ).all(),
        "items": db.execute(
            text(
                "SELECT id, pharmacy_id, batch, expiry_date, qty_on_hand "
                "FROM inventory_items ORDER BY id"
            )
        ).all(),
        "clients": db.execute(
            text("SELECT user_id, district_id FROM client_profiles ORDER BY 1")
        ).all(),
    }


class TestDemoSeed:
    def test_it_adds_pharmacies_with_hours_clients_and_stock(self, db: Connection) -> None:
        stock_some_products(db)

        result = seed_demo(db, seed=42, now=NOW)

        assert (result.pharmacies, result.clients) == (16, 6)
        assert result.inventory_items == 16 * 12
        assert (
            db.execute(text("SELECT count(DISTINCT pharmacy_id) FROM pharmacy_hours")).scalar()
            == 16
        )
        statuses = db.execute(text("SELECT DISTINCT status FROM pharmacies")).scalars()
        assert set(statuses) == {"APPROVED"}

    def test_the_same_seed_gives_the_same_data(self, db: Connection) -> None:
        stock_some_products(db)

        with db.begin_nested() as first:
            seed_demo(db, seed=42, now=NOW)
            one = snapshot(db)
            first.rollback()
        with db.begin_nested() as second:
            seed_demo(db, seed=42, now=NOW)
            again = snapshot(db)
            second.rollback()
        seed_demo(db, seed=7, now=NOW)

        assert one == again
        assert snapshot(db)["pharmacies"] != one["pharmacies"]

    def test_no_controlled_medicine_is_ever_stocked(self, db: Connection) -> None:
        stock_some_products(db)

        seed_demo(db, seed=42, now=NOW)

        stocked = db.execute(
            text(
                "SELECT count(*) FROM inventory_items ii JOIN products p ON p.id = ii.product_id "
                "WHERE p.controlled"
            )
        ).scalar()
        assert stocked == 0

    def test_the_stock_covers_visible_early_release_and_private_boxes(self, db: Connection) -> None:
        stock_some_products(db)

        seed_demo(db, seed=42, now=NOW)

        zones = db.execute(
            text("SELECT DISTINCT expiry_zone(expiry_date - :today) FROM inventory_items"),
            {"today": TODAY},
        ).scalars()
        assert set(zones) == {"NEAR_EXPIRY", "EARLY_RELEASE", "PRIVATE"}
        visible = db.execute(
            text("SELECT count(*) FROM visible_listings(:today)"), {"today": TODAY}
        ).scalar()
        assert visible is not None
        assert visible > 50

    def test_the_demo_accounts_cannot_log_in_yet_and_hold_no_real_details(
        self, db: Connection
    ) -> None:
        seed_demo(db, seed=42, now=NOW)

        users = db.execute(text("SELECT email, password_hash, full_name FROM users")).all()

        assert {u.password_hash for u in users} == {"!"}
        assert all(u.email.endswith("@demo.dawalink.test") for u in users)
        assert all(u.full_name.startswith("Demo ") for u in users)

    def test_without_a_catalog_it_still_adds_the_accounts(self, db: Connection) -> None:
        db.execute(text("DELETE FROM product_ingredients"))
        assert db.execute(text("SELECT count(*) FROM products")).scalar() == 0

        result = seed_demo(db, seed=42, now=NOW)

        assert (result.pharmacies, result.inventory_items) == (16, 0)


CATALOG = [
    CatalogRow(
        701 + n,
        "1/1",
        f"TESTAMOL {n}",
        "500mg",
        "20",
        "Tablet",
        "Maker",
        500_000 + n,
        "N02BE01",
        "G",
        "Paracetamol - 500mg",
    )
    for n in range(8)
]


@pytest.fixture
def catalog_folder(tmp_path: Path) -> Path:
    write_catalog(tmp_path / CATALOG_FILE, CATALOG)
    details = {
        "file_name": "WebMarketed-test.xls",
        "source_date": "2026-11-11",
        "lbp_per_usd": "89500.00",
        "rows_total": 9,
    }
    (tmp_path / DETAILS_FILE).write_text(json.dumps(details), encoding="utf-8")
    return tmp_path


def count(url: str, table: str) -> int:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # type: ignore[no-any-return]
    finally:
        engine.dispose()


def test_preparing_an_empty_database_twice_gives_a_working_one(
    development_urls: DatabaseUrls, tmp_path: Path, catalog_folder: Path
) -> None:
    """docs/12 §7: logins, migrations, grants, reference data, the catalog and the demo data."""
    name = "dawalink_prepare_test"
    scratch = development_urls.on(name)
    run_as_admin(
        development_urls,
        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',
        f'CREATE DATABASE "{name}"',
    )
    settings = make_settings(
        scratch.app,
        tmp_path,
        demo_mode=True,
        database_admin_url=scratch.admin,
        database_migrator_url=scratch.migrator,
        database_retention_url=scratch.retention,
    )
    try:
        prepare(settings, wait_seconds=5, catalog_folder=catalog_folder)
        first = {t: count(scratch.app, t) for t in ("products", "pharmacies", "inventory_items")}
        prepare(settings, wait_seconds=5, catalog_folder=catalog_folder)
        second = {t: count(scratch.app, t) for t in ("products", "pharmacies", "inventory_items")}

        assert first == second == {"products": 8, "pharmacies": 16, "inventory_items": 16 * 8}
        assert count(scratch.app, "districts") == 26
        assert count(scratch.app, "pricing_tiers") == len(DISCOUNT_TIERS)
        assert count(scratch.app, "catalog_imports") == 1
    finally:
        run_as_admin(development_urls, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_without_demo_mode_or_a_catalog_file_it_only_builds_the_schema(
    development_urls: DatabaseUrls, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    name = "dawalink_prepare_test"
    scratch = development_urls.on(name)
    run_as_admin(
        development_urls,
        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',
        f'CREATE DATABASE "{name}"',
    )
    settings = make_settings(
        scratch.app,
        tmp_path,
        database_admin_url=scratch.admin,
        database_migrator_url=scratch.migrator,
        database_retention_url=scratch.retention,
    )
    try:
        prepare(settings, wait_seconds=5, catalog_folder=tmp_path / "nothing-here")

        assert count(scratch.app, "products") == 0
        assert count(scratch.app, "pharmacies") == 0
        assert count(scratch.app, "districts") == 26
    finally:
        run_as_admin(development_urls, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


class TestTheLoginsSettings:
    def settings(self, tmp_path: Path, urls: DatabaseUrls, **overrides: object) -> Any:
        values: dict[str, object] = {
            "database_admin_url": urls.admin,
            "database_migrator_url": urls.migrator,
            "database_retention_url": urls.retention,
        }
        return make_settings(urls.app, tmp_path, **(values | overrides))

    def test_all_four_addresses_are_needed(self, tmp_path: Path, urls: DatabaseUrls) -> None:
        settings = self.settings(
            tmp_path, urls, database_admin_url=None, database_retention_url=None
        )

        with pytest.raises(ConfigError, match="DATABASE_ADMIN_URL, DATABASE_RETENTION_URL"):
            login_passwords(settings)

    def test_each_address_must_use_its_own_login(self, tmp_path: Path, urls: DatabaseUrls) -> None:
        """The grants and a trigger name the logins, so the names are fixed."""
        settings = self.settings(tmp_path, urls, database_migrator_url=urls.admin)

        with pytest.raises(ConfigError, match="DATABASE_MIGRATOR_URL") as error:
            login_passwords(settings)

        assert "dawalink_migrator" in str(error.value)
        assert "local-only" not in str(error.value)

    def test_the_passwords_come_from_the_addresses(
        self, tmp_path: Path, urls: DatabaseUrls
    ) -> None:
        admin, migrator, passwords = login_passwords(self.settings(tmp_path, urls))

        assert (admin, migrator) == (urls.admin, urls.migrator)
        assert set(passwords) == {"dawalink_migrator", "dawalink_app", "dawalink_retention"}
        assert all(passwords.values())
