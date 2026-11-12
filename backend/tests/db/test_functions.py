"""The SQL functions give exactly what the Python rules give (docs/05 §5).

The migration holds frozen copies of a few numbers and formulas. These tests compare them
with dawalink/domain over every boundary, so the two can never drift apart unnoticed.
"""

import itertools
from datetime import timedelta

import pytest
from sqlalchemy import Connection, text

from dawalink.domain import pricing
from dawalink.domain.accounts import PharmacyStatus
from dawalink.domain.expiry import days_left, fits, zone_of
from dawalink.domain.inventory import ListingControl, is_visible
from dawalink.domain.numbers import DISCOUNT_TIERS, EARLY_RELEASE_MAX_DAYS, NEAR_EXPIRY_MAX_DAYS
from tests.db import factories as make
from tests.db.factories import TODAY

BOUNDARY_DAYS = sorted(
    {-2, -1, 0, 1, NEAR_EXPIRY_MAX_DAYS, NEAR_EXPIRY_MAX_DAYS + 1}
    | {EARLY_RELEASE_MAX_DAYS, EARLY_RELEASE_MAX_DAYS + 1, 400}
    | {
        edge + step
        for low, high, _ in DISCOUNT_TIERS
        for edge in (low, high)
        for step in (-1, 0, 1)
    }
)
PRICES = [
    0,
    1,
    999,
    1_000,
    1_001,
    1_500,
    19_999,
    333_333,
    716_000,
    1_234_567,
    519_366_124,
    9_999_999_999,
]


def test_the_tiers_table_holds_the_rules_tiers(db: Connection) -> None:
    rows = db.execute(text("SELECT min_days, max_days, discount_pct FROM pricing_tiers")).all()

    assert sorted(tuple(row) for row in rows) == sorted(DISCOUNT_TIERS)


def test_the_price_function_matches_the_price_rule_everywhere(db: Connection) -> None:
    """SM-3, R-PR2, INV-5: whole-number maths, rounded down, never above the public price."""
    for public, days in itertools.product(PRICES, BOUNDARY_DAYS):
        for override in (None, 0, 1, public // 2, public, public + 1, public * 3):
            case = {"public": public, "override": override, "days": days}
            in_sql = db.execute(
                text("SELECT effective_price_lbp(:public, :override, :days)"), case
            ).scalar()
            assert in_sql == pricing.effective_price_lbp(public, override, days), case
            if in_sql is not None:
                assert 0 <= in_sql <= public, case


def test_the_price_examples_of_the_rules(db: Connection) -> None:
    def price(public: int, days: int) -> int | None:
        return db.execute(
            text("SELECT effective_price_lbp(:public, NULL, :days)"),
            {"public": public, "days": days},
        ).scalar()

    assert price(1_000_000, 120) == 750_000  # 91-180 days: 25% off
    assert price(1_000_000, 60) == 600_000  # 31-90 days: 40% off
    assert price(1_000_000, 10) == 400_000  # 0-30 days: 60% off
    assert price(1_234_567, 120) == 925_000  # rounded down to 1,000
    assert price(1_000_000, 181) is None  # outside the published window
    assert price(1_000_000, -1) is None


def test_the_zone_function_matches_the_zone_rule(db: Connection) -> None:
    """SM-3, N-1, N-3."""
    for days in range(-5, 400):
        for eligible in (True, False):
            in_sql = db.execute(
                text("SELECT expiry_zone(:days, :eligible)"), {"days": days, "eligible": eligible}
            ).scalar()
            assert in_sql == zone_of(days, eligible=eligible).value, (days, eligible)


def test_the_fit_function_matches_the_fit_rule(db: Connection) -> None:
    """R-F1, INV-25: the box is still valid on the last day of use."""
    for left, pickup_in, days_of_use in itertools.product(range(0, 12), range(0, 5), range(1, 13)):
        expiry, pickup_day = TODAY + timedelta(days=left), TODAY + timedelta(days=pickup_in)
        in_sql = db.execute(
            text("SELECT fits(:expiry, :pickup_day, :days_of_use)"),
            {"expiry": expiry, "pickup_day": pickup_day, "days_of_use": days_of_use},
        ).scalar()
        assert in_sql == fits(expiry, pickup_day, days_of_use), (left, pickup_in, days_of_use)


class TestVisibleListings:
    """INV-16: one definition of "visible to clients", the same in SQL and in Python."""

    def visible(self, db: Connection) -> dict[object, tuple[int, int, int | None]]:
        rows = db.execute(
            text(
                "SELECT inventory_item_id, days_left, qty_available, price_lbp "
                "FROM visible_listings(:today)"
            ),
            {"today": TODAY},
        ).all()
        return {row[0]: (row[1], row[2], row[3]) for row in rows}

    @pytest.mark.parametrize("days", [-1, 0, 1, 30, 180, 181, 270, 271])
    def test_the_window_is_zero_to_180_days_with_no_minimum(
        self, db: Connection, days: int
    ) -> None:
        item = make.item(db, days_left=days)

        expected = zone_of(days).value == "NEAR_EXPIRY"

        assert (item in self.visible(db)) is expected
        assert expected is (0 <= days <= NEAR_EXPIRY_MAX_DAYS)

    def test_every_condition_matters(self, db: Connection) -> None:
        for status, control, controlled, on_hand, reserved in itertools.product(
            PharmacyStatus, ListingControl, (False, True), (0, 1, 3), (0, 1, 3)
        ):
            if reserved > on_hand:
                continue
            item = make.item(
                db,
                pharmacy_id=make.pharmacy(db, status.value),
                product_id=make.product(db, controlled=controlled),
                qty_on_hand=on_hand,
                qty_reserved=reserved,
                listing_control=control.value,
            )
            expected = is_visible(
                zone=zone_of(60),
                control=control,
                pharmacy_status=status,
                qty_available=on_hand - reserved,
                controlled=controlled,
            )
            assert (item in self.visible(db)) is expected, (
                status,
                control,
                controlled,
                on_hand,
                reserved,
            )

    def test_it_reports_the_days_left_the_available_units_and_the_price(
        self, db: Connection
    ) -> None:
        product = make.product(db, public_price_lbp=1_000_000)
        policy = make.item(db, product_id=product, days_left=60, qty_on_hand=5, qty_reserved=2)
        own_price = make.item(db, product_id=product, days_left=60, price_override_lbp=250_000)

        listings = self.visible(db)

        assert listings[policy] == (60, 3, 600_000)
        assert listings[own_price][2] == 250_000
        assert days_left(TODAY + timedelta(days=60), TODAY) == 60

    def test_today_is_a_parameter_so_the_app_clock_decides(self, db: Connection) -> None:
        """DB-D6: moving the app clock forward changes what is visible, with no data change."""
        item = make.item(db, days_left=200)

        later = db.execute(
            text("SELECT inventory_item_id FROM visible_listings(:today)"),
            {"today": TODAY + timedelta(days=30)},
        ).scalars()

        assert item not in self.visible(db)
        assert item in set(later)


def test_the_area_label(db: Connection) -> None:
    """Beirut (1) and Matn (11) share no governorate; Matn and Baabda (12) do."""

    def rank(client: int, pharmacy: int) -> int | None:
        return db.execute(
            text("SELECT area_rank(CAST(:c AS smallint), CAST(:p AS smallint))"),
            {"c": client, "p": pharmacy},
        ).scalar()

    assert rank(1, 1) == 0
    assert rank(11, 12) == 1
    assert rank(1, 11) == 2
