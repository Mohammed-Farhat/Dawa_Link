"""Each constraint has a test that tries to break it (docs/05 §4, §10)."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, insert, text, update
from sqlalchemy.exc import IntegrityError

from dawalink.db.models import (
    Escalation,
    InventoryItem,
    InventoryUpload,
    Order,
    PharmacyHours,
    PricingTier,
    SourcingRequest,
)
from tests.db import factories as make
from tests.db.factories import NOW


def refused(db: Connection, action: Callable[[], Any], constraint: str) -> None:
    """The action breaks exactly this constraint, and the test's transaction survives."""
    with pytest.raises(IntegrityError, match=constraint), db.begin_nested():
        action()


class TestStock:
    def test_reserved_units_never_exceed_units_on_hand(self, db: Connection) -> None:
        """INV-1."""
        item = make.item(db, qty_on_hand=2)

        def reserve_three() -> None:
            db.execute(update(InventoryItem).where(InventoryItem.id == item).values(qty_reserved=3))

        refused(db, reserve_three, "ck_inventory_items_reserved_within_on_hand")

    @pytest.mark.parametrize(
        ("values", "constraint"),
        [
            ({"qty_on_hand": -1}, "on_hand_not_negative"),
            ({"qty_reserved": -1}, "reserved_not_negative"),
            ({"price_override_lbp": -1}, "price_override_not_negative"),
            ({"listing_control": "HIDDEN"}, "listing_control_values"),
        ],
    )
    def test_quantities_and_prices_are_never_negative(
        self, db: Connection, values: dict[str, Any], constraint: str
    ) -> None:
        refused(db, lambda: make.item(db, **values), constraint)

    def test_one_row_per_pharmacy_product_batch_and_expiry(self, db: Connection) -> None:
        """R-U1."""
        pharmacy, product = make.pharmacy(db), make.product(db)

        def same_batch() -> object:
            return make.item(db, pharmacy_id=pharmacy, product_id=product, batch="B1", days_left=30)

        same_batch()

        refused(db, same_batch, "uq_inventory_items_pharmacy_id_product_id_batch_expiry_date")

    def test_a_pack_holds_at_least_one_unit(self, db: Connection) -> None:
        """INV-19."""
        refused(db, lambda: make.product(db, units_per_pack=0), "units_per_pack_positive")

    def test_one_upload_waits_for_apply_at_a_time(self, db: Connection) -> None:
        pharmacy = make.pharmacy(db)
        upload = {
            "pharmacy_id": pharmacy,
            "status": "VALIDATED",
            "file_name": "stock.csv",
            "created_by": make.user(db, "pharmacist"),
        }
        db.execute(insert(InventoryUpload).values(**upload))

        refused(
            db,
            lambda: db.execute(insert(InventoryUpload).values(**upload)),
            "uq_inventory_uploads_one_validated",
        )
        db.execute(insert(InventoryUpload).values(**upload | {"status": "APPLIED"}))


class TestOrders:
    @pytest.mark.parametrize(
        ("values", "constraint"),
        [
            ({"state": "PICKED_UP", "qty_locked": 1}, "only_open_orders_hold_stock"),
            ({"state": "OFFERED", "offer_expires_at": None}, "offer_has_an_end"),
            ({"state": "RESERVED", "deadline": None}, "reservation_has_a_deadline"),
            ({"state": "RESERVED", "pickup_day": None}, "reservation_has_a_pickup_day"),
            ({"state": "PICKED_UP", "qty_picked_up": None}, "picked_up_has_a_quantity"),
            ({"qty_requested": 0, "qty_locked": 0}, "qty_requested_positive"),
            ({"qty_locked": 2}, "qty_locked_range"),
            ({"days_of_use": 0}, "days_of_use_positive"),
            ({"price_snapshot_lbp": -1}, "price_snapshot_not_negative"),
            ({"state": "LOST"}, "state_values"),
            ({"source": "phone"}, "source_values"),
            ({"ref": "R-70O1IL"}, "ref_format"),
            ({"ref": "7K3Q2F"}, "ref_format"),
        ],
    )
    def test_an_order_that_breaks_a_rule_is_refused(
        self, db: Connection, values: dict[str, Any], constraint: str
    ) -> None:
        """INV-14 and the shape of an order."""
        state = values.pop("state", "RESERVED")

        refused(db, lambda: make.order(db, state, **values), constraint)

    def test_one_idempotency_key_makes_one_order(self, db: Connection) -> None:
        client = make.client(db)
        make.order(db, client_id=client, idempotency_key="tap-1")

        refused(
            db,
            lambda: make.order(db, client_id=client, idempotency_key="tap-1"),
            "uq_orders_client_id_idempotency_key",
        )
        make.order(db, idempotency_key="tap-1")  # another client may use the same key

    def test_a_claim_has_one_offer_per_path(self, db: Connection) -> None:
        """INV-20: one matching offer and one early-release offer at most."""
        claim = make.claim(db)
        make.order(db, "OFFERED", claim_id=claim, source="watch")

        refused(
            db,
            lambda: make.order(db, "OFFERED", claim_id=claim, source="watch"),
            "uq_orders_one_offer_per_path",
        )
        make.order(db, "OFFERED", claim_id=claim, source="early_release")
        # An offer that has ended no longer counts.
        make.order(db, "OFFER_EXPIRED", claim_id=claim, source="watch")

    def test_two_orders_never_share_a_number(self, db: Connection) -> None:
        make.order(db, ref="R-7K3Q2F")

        refused(db, lambda: make.order(db, ref="R-7K3Q2F"), "uq_orders_ref")


class TestNeeds:
    def test_a_client_has_one_live_watch_per_product(self, db: Connection) -> None:
        """R-W2."""
        client, product = make.client(db), make.product(db)
        make.claim(db, client_id=client, product_id=product)

        refused(
            db,
            lambda: make.claim(db, client_id=client, product_id=product),
            "uq_claims_one_live_watch",
        )
        make.claim(db, client_id=client, product_id=product, state="EXPIRED")

    @pytest.mark.parametrize(
        ("values", "constraint"),
        [
            ({"kind": "WATCH", "qty": 4, "qty_missing": 4}, "qty_range"),
            ({"kind": "WATCH", "qty_missing": 2}, "qty_missing_range"),
            ({"kind": "REQUEST_ITEM"}, "request_item_only_for_its_kind"),
            ({"kind": "WATCH", "days_of_use": 0}, "days_of_use_positive"),
            ({"kind": "WATCH", "state": "PAUSED"}, "state_values"),
        ],
    )
    def test_a_claim_that_breaks_a_rule_is_refused(
        self, db: Connection, values: dict[str, Any], constraint: str
    ) -> None:
        kind = values.pop("kind")

        refused(db, lambda: make.claim(db, kind, **values), constraint)

    def test_a_request_is_closed_exactly_when_it_has_an_outcome(self, db: Connection) -> None:
        request = make.request(db)

        def close_without_outcome() -> None:
            db.execute(
                update(SourcingRequest).where(SourcingRequest.id == request).values(state="CLOSED")
            )

        refused(db, close_without_outcome, "closed_has_an_outcome")
        refused(db, lambda: make.request(db, outcome="FULFILLED"), "closed_has_an_outcome")
        db.execute(
            update(SourcingRequest)
            .where(SourcingRequest.id == request)
            .values(state="CLOSED", outcome="PARTIAL", closed_at=NOW)
        )

    @pytest.mark.parametrize(
        ("values", "constraint"),
        [
            ({"position": 6}, "position_range"),
            ({"qty": 4}, "qty_range"),
            ({"qty": 2, "qty_secured": 3}, "qty_secured_range"),
            ({"state": "LOST"}, "state_values"),
        ],
    )
    def test_a_request_item_that_breaks_a_rule_is_refused(
        self, db: Connection, values: dict[str, Any], constraint: str
    ) -> None:
        request = make.request(db)

        refused(db, lambda: make.request_item(db, request, **values), constraint)

    def test_a_request_holds_each_position_once(self, db: Connection) -> None:
        request = make.request(db)
        make.request_item(db, request, position=1)

        refused(
            db,
            lambda: make.request_item(db, request, position=1),
            "uq_request_items_request_id_position",
        )


class TestPeopleAndPlaces:
    def test_an_admin_always_has_a_second_login_factor(self, db: Connection) -> None:
        """R-AU6."""
        refused(db, lambda: make.user(db, "admin"), "admin_has_totp")
        make.user(db, "admin", totp_secret=b"encrypted-secret")

    def test_emails_are_unique_whatever_their_case(self, db: Connection) -> None:
        make.user(db, email="Someone@Example.test")

        refused(db, lambda: make.user(db, email="someone@example.TEST"), "uq_users_email")

    def test_a_paused_client_has_an_end_date(self, db: Connection) -> None:
        refused(db, lambda: make.client(db, "PAUSED"), "paused_has_an_end")
        make.client(db, "PAUSED", paused_until=NOW + timedelta(days=7))

    @pytest.mark.parametrize("days", [0, 4])
    def test_a_pharmacy_holds_reservations_for_one_to_three_days(
        self, db: Connection, days: int
    ) -> None:
        """N-6."""
        refused(db, lambda: make.pharmacy(db, pickup_days=days), "pickup_days_range")

    def test_one_account_runs_one_pharmacy(self, db: Connection) -> None:
        owner = make.user(db, "pharmacist")
        make.pharmacy(db, owner_user_id=owner)

        refused(db, lambda: make.pharmacy(db, owner_user_id=owner), "uq_pharmacies_owner_user_id")

    @pytest.mark.parametrize(
        ("hours", "constraint"),
        [
            ({"open_minute": 600, "close_minute": 600}, "opens_before_it_closes"),
            ({"weekday": 7}, "weekday_range"),
            ({"seq": 3}, "seq_range"),
            ({"close_minute": 1441}, "close_minute_range"),
        ],
    )
    def test_opening_hours_must_make_sense(
        self, db: Connection, hours: dict[str, int], constraint: str
    ) -> None:
        values = {"pharmacy_id": make.pharmacy(db), "weekday": 0, "seq": 1} | {
            "open_minute": 480,
            "close_minute": 1260,
        }

        refused(db, lambda: db.execute(insert(PharmacyHours).values(**values | hours)), constraint)

    def test_a_client_has_one_active_chat(self, db: Connection) -> None:
        """Decision log D9."""
        client = make.client(db)
        make.conversation(db, client_id=client)

        refused(
            db,
            lambda: make.conversation(db, client_id=client),
            "uq_conversations_one_active_chat",
        )
        make.conversation(db, client_id=client, status="ARCHIVED")

    def test_a_client_has_one_open_escalation(self, db: Connection) -> None:
        """SM-9: a second one is appended to the first."""
        client = make.client(db)
        escalation = {"client_id": client, "reason": "complaint", "summary": "Contests a no-show"}
        db.execute(insert(Escalation).values(**escalation))

        refused(
            db,
            lambda: db.execute(insert(Escalation).values(**escalation)),
            "uq_escalations_one_open",
        )


class TestCatalog:
    def test_discount_tiers_never_overlap(self, db: Connection) -> None:
        """So a number of days left has at most one discount (N-4)."""
        refused(
            db,
            lambda: db.execute(
                insert(PricingTier).values(min_days=20, max_days=40, discount_pct=50)
            ),
            "ex_pricing_tiers_no_overlap",
        )

    def test_the_ministrys_code_identifies_one_product(self, db: Connection) -> None:
        make.product(db, moph_code=123)

        refused(db, lambda: make.product(db, moph_code=123), "uq_products_moph_code")

    def test_a_product_can_be_found_by_a_misspelled_name(self, db: Connection) -> None:
        """Fuzzy search works on the normalized name (pg_trgm)."""
        make.product(db, moph_name="AUGMENTIN", search_name="augmentin")

        found = db.execute(
            text("SELECT moph_name FROM products WHERE search_name % 'ogmentin' ORDER BY 1")
        ).scalars()

        assert "AUGMENTIN" in list(found)


def test_the_claim_order_is_creation_time_then_id(db: Connection) -> None:
    """R-PRI: the first to wait is the first served; the index matching reads says so."""
    definition = db.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_claims_matching'")
    ).scalar_one()

    assert "(equivalence_key, created_at, id)" in definition
    assert "state = 'ACTIVE'" in definition


def test_an_order_in_a_closed_state_cannot_hold_units(db: Connection) -> None:
    order = make.order(db, "RESERVED")

    def close_but_keep_the_lock() -> None:
        db.execute(update(Order).where(Order.id == order).values(state="CANCELLED_BY_CLIENT"))

    refused(db, close_but_keep_the_lock, "only_open_orders_hold_stock")
