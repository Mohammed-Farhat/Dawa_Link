"""A pharmacy's stock: edits and uploads (docs/04 SM-3, SM-4, R-U1 to R-U5, R-C6)."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from dawalink.domain.inventory import ListingControl
from dawalink.domain.orders import OrderSource
from dawalink.domain.vocabulary import ClaimSource
from dawalink.services import claims, controlled, inventory, orders
from dawalink.services.errors import Code, ServiceError
from dawalink.services.orders import ReserveLine
from dawalink.services.travel import shared_location
from tests.db.factories import NOW, TODAY
from tests.services.conftest import World

HAMRA = shared_location(33.896, 35.483)
DAY = timedelta(days=1)


@dataclass
class Store:
    world: World
    pharmacy: uuid.UUID
    owner: uuid.UUID
    panadol: uuid.UUID
    concor: uuid.UUID

    def upload(self, text: str) -> Any:
        tx = self.world.tx()
        upload = inventory.validate_upload(
            tx, self.pharmacy, self.owner, "stock.csv", text.encode("utf-8")
        )
        self.world.settle(tx)
        return self.world.one("SELECT * FROM inventory_uploads WHERE id = :id", id=upload.id)

    def apply(self, upload_id: uuid.UUID) -> Any:
        tx = self.world.tx()
        inventory.apply_upload(tx, self.pharmacy, upload_id)
        self.world.settle(tx)
        return self.world.one("SELECT * FROM inventory_uploads WHERE id = :id", id=upload_id)

    def items(self) -> dict[tuple[str, str], Any]:
        rows = self.world.all(
            "SELECT p.moph_name, ii.* FROM inventory_items ii "
            "JOIN products p ON p.id = ii.product_id "
            "WHERE ii.pharmacy_id = :p",
            p=self.pharmacy,
        )
        return {(row.moph_name, row.batch): row for row in rows}


@pytest.fixture
def store(world: World) -> Store:
    owner = world.make.user("pharmacist")
    return Store(
        world,
        pharmacy=world.make.pharmacy(owner_user_id=owner, lat=33.897, lon=35.484),
        owner=owner,
        panadol=world.make.product(
            moph_name="PANADOL",
            search_name="panadol",
            dosage_text="500mg",
            public_price_lbp=1_000_000,
        ),
        concor=world.make.product(moph_name="CONCOR", search_name="concor", dosage_text="5mg"),
    )


def refusal(action: Any) -> ServiceError:
    with pytest.raises(ServiceError) as refused:
        action()
    return refused.value


class TestTheManualForm:
    def test_a_new_box_appears_and_a_waiting_client_is_offered_it(
        self, store: Store, world: World
    ) -> None:
        """R-PRI1: every change that adds stock triggers matching."""
        tx = world.tx()
        watch = claims.create_watch(
            tx,
            client_id=world.make.client(),
            product_id=store.panadol,
            location=HAMRA,
            source=ClaimSource.SEARCH,
        )
        world.settle(tx)

        tx = world.tx()
        item = inventory.add_item(
            tx,
            store.pharmacy,
            product_id=store.panadol,
            batch="B1",
            expiry_date=TODAY + 60 * DAY,
            quantity=3,
        )
        world.settle(tx)

        offer = world.one("SELECT * FROM orders WHERE claim_id = :c", c=watch.id)
        assert (offer.state, offer.inventory_item_id) == ("OFFERED", item.id)
        assert world.audit_actions(item.id) == ["inventory.add"]

    def test_the_same_box_twice_is_refused(self, store: Store, world: World) -> None:
        box: dict[str, Any] = {
            "product_id": store.panadol,
            "batch": "B1",
            "expiry_date": TODAY + 60 * DAY,
            "quantity": 3,
        }
        first = inventory.add_item(world.tx(), store.pharmacy, **box)

        error = refusal(lambda: inventory.add_item(world.tx(), store.pharmacy, **box))

        assert (error.code, error.details) == (Code.ITEM_EXISTS, {"item_id": first.id})

    def test_what_cannot_be_added(self, store: Store, world: World) -> None:
        controlled = world.make.product(controlled=True)
        pending = world.make.pharmacy("PENDING")
        box: dict[str, Any] = {"batch": "B1", "expiry_date": TODAY + 60 * DAY, "quantity": 1}

        def code(pharmacy: uuid.UUID = store.pharmacy, **values: Any) -> Code:
            asked = {"product_id": store.panadol} | box | values
            return refusal(lambda: inventory.add_item(world.tx(), pharmacy, **asked)).code

        assert code(product_id=controlled) is Code.PRODUCT_NOT_ALLOWED
        assert code(expiry_date=TODAY - DAY) is Code.VALIDATION_ERROR
        assert code(price_override_lbp=1_000_001) is Code.PRICE_ABOVE_PUBLIC
        assert code(pharmacy=pending) is Code.PHARMACY_NOT_APPROVED

    def test_a_lower_quantity_never_takes_a_reserved_box_away(
        self, store: Store, world: World
    ) -> None:
        """R-U3, FR-11."""
        item = world.make.item(pharmacy_id=store.pharmacy, product_id=store.panadol, qty_on_hand=5)
        tx = world.tx()
        orders.reserve(
            tx,
            client_id=world.make.client(),
            lines=[ReserveLine(item, 2, expected_price_lbp=600_000)],
            pickup_day=TODAY,
            source=OrderSource.SEARCH,
            idempotency_key="a",
        )
        world.settle(tx)

        edited = inventory.edit_item(world.tx(), store.pharmacy, item, quantity=1)

        assert edited.reserved_kept is True
        assert (edited.item.qty_on_hand, edited.item.qty_reserved) == (2, 2)

    def test_a_price_override_and_a_pause(self, store: Store, world: World) -> None:
        """R-PR1; a paused listing is hidden."""
        item = world.make.item(pharmacy_id=store.pharmacy, product_id=store.panadol)

        inventory.edit_item(world.tx(), store.pharmacy, item, price_override_lbp=0)
        too_dear = refusal(
            lambda: inventory.edit_item(
                world.tx(), store.pharmacy, item, price_override_lbp=1_000_001
            )
        )
        inventory.edit_item(world.tx(), store.pharmacy, item, listing_control=ListingControl.PAUSED)

        row = world.one("SELECT * FROM inventory_items WHERE id = :i", i=item)
        assert (row.price_override_lbp, row.listing_control, row.last_edited_at) == (
            0,
            "PAUSED",
            NOW,
        )
        assert too_dear.code is Code.PRICE_ABOVE_PUBLIC
        visible = world.all(
            "SELECT 1 FROM visible_listings(:t) WHERE inventory_item_id = :i", t=TODAY, i=item
        )
        assert visible == []

    def test_another_pharmacys_box_does_not_exist(self, store: Store, world: World) -> None:
        other = world.make.item()

        error = refusal(lambda: inventory.edit_item(world.tx(), store.pharmacy, other, quantity=0))

        assert error.code is Code.NOT_FOUND


GOOD_FILE = """product,strength,batch,expiry,quantity
Panadol,500mg,B1,2026-12,10
PANADOL,,B1,2026-12-31,5
Concor,5 mg,C7,2027-03-15,4
"""


class TestUploads:
    def test_a_file_is_checked_and_staged_and_changes_nothing_yet(
        self, store: Store, world: World
    ) -> None:
        """SM-4: VALIDATED shows the summary; nothing is applied."""
        upload = store.upload(GOOD_FILE)

        assert (upload.status, upload.rows_total, upload.rows_ok, upload.rows_error) == (
            "VALIDATED",
            3,
            3,
            0,
        )
        assert upload.summary == {"new": 2, "changed": 0, "zeroed": 0, "reserved_kept": 0}
        staged = world.all(
            "SELECT quantity, expiry_date FROM inventory_upload_rows "
            "WHERE upload_id = :u ORDER BY quantity",
            u=upload.id,
        )
        # R-U1: the two Panadol rows are one box (a month means its last day), summed.
        assert [tuple(row) for row in staged] == [
            (4, TODAY.replace(year=2027, month=3, day=15)),
            (15, TODAY.replace(month=12, day=31)),
        ]
        assert store.items() == {}

    def test_a_row_with_a_problem_is_reported_and_never_blocks_the_others(
        self, store: Store, world: World
    ) -> None:
        """R-U5, R-C9, FI-10."""
        world.make.product(moph_name="TRAMAL", search_name="tramal", controlled=True)
        world.make.product(moph_name="CONCOR", search_name="concor", dosage_text="10mg")

        upload = store.upload(
            "product,strength,batch,expiry,quantity\n"
            "Panadol,,B1,2026-12,10\n"
            "Panadoll,,B2,2026-12,1\n"
            "Tramal,,B3,2026-12,1\n"
            "Concor,,B4,2026-12,1\n"
            "Panadol,,B5,12/2026,1\n"
            "Panadol,,B6,2026-09,1\n"
            "Panadol,,B7,2026-12,-3\n"
            "Panadol,,,2026-12,3\n"
        )

        assert (upload.rows_ok, upload.rows_error) == (1, 7)
        problems = {error["row"]: error["problem"] for error in upload.errors}
        assert problems == {
            3: "no product with this name",
            4: "this medicine can't be listed on DawaLink",
            5: "several products have this name: add the strength",
            6: "the expiry must be YYYY-MM or YYYY-MM-DD",
            7: "this box has already expired",
            8: "the quantity must be a whole number, 0 or more",
            9: "the batch is missing",
        }
        assert upload.errors[0]["did_you_mean"] == ["PANADOL"]

    @pytest.mark.parametrize(
        ("content", "reason"),
        [
            ("name,qty\nPanadol,1\n", "the columns must be"),
            ("product,batch,expiry,quantity\n", "no rows"),
            ("product,batch,expiry,quantity\n=cmd|calc,B1,2026-12,1\n", "formulas"),
            (
                "product,batch,expiry,quantity,price\nPanadol,B1,2026-12,1,5\n",
                "the columns must be",
            ),
        ],
    )
    def test_a_file_that_cannot_be_used_is_refused_whole(
        self, store: Store, content: str, reason: str
    ) -> None:
        """SM-4: FAILED. A formula is never stored or echoed back (FS-10)."""
        error = refusal(lambda: store.upload(content))

        assert error.code is Code.UPLOAD_FAILED
        assert reason in error.details["reason"]

    def test_a_file_over_five_megabytes_is_refused(self, store: Store, world: World) -> None:
        big = b"product,batch,expiry,quantity\n" + b"x" * (5 * 1024 * 1024)

        error = refusal(
            lambda: inventory.validate_upload(
                world.tx(), store.pharmacy, store.owner, "big.csv", big
            )
        )

        assert error.code is Code.FILE_TOO_LARGE

    def test_applying_makes_the_file_the_stock(self, store: Store, world: World) -> None:
        """R-U2, R-U4: new boxes, changed quantities, missing boxes set to 0 and kept."""
        kept = world.make.item(
            pharmacy_id=store.pharmacy,
            product_id=store.concor,
            batch="C7",
            expiry_date=TODAY.replace(year=2027, month=3, day=15),
            qty_on_hand=9,
            price_override_lbp=100_000,
            listing_control="PAUSED",
        )
        world.make.item(
            pharmacy_id=store.pharmacy, product_id=store.panadol, batch="OLD", qty_on_hand=6
        )
        upload = store.upload(GOOD_FILE)

        applied = store.apply(upload.id)

        items = store.items()
        assert {key: row.qty_on_hand for key, row in items.items()} == {
            ("PANADOL", "B1"): 15,
            ("CONCOR", "C7"): 4,
            ("PANADOL", "OLD"): 0,
        }
        # The pharmacy's own price and its pause survive the upload.
        assert items[("CONCOR", "C7")].id == kept
        assert items[("CONCOR", "C7")].price_override_lbp == 100_000
        assert items[("CONCOR", "C7")].listing_control == "PAUSED"
        assert (applied.status, applied.applied_at) == ("APPLIED", NOW)
        assert (
            world.all("SELECT 1 FROM inventory_upload_rows WHERE upload_id = :u", u=upload.id) == []
        )
        assert upload.summary == {"new": 1, "changed": 1, "zeroed": 1, "reserved_kept": 0}

    def test_an_upload_never_takes_a_reserved_box_away(self, store: Store, world: World) -> None:
        """R-U3."""
        item = world.make.item(
            pharmacy_id=store.pharmacy, product_id=store.panadol, batch="OLD", qty_on_hand=6
        )
        tx = world.tx()
        orders.reserve(
            tx,
            client_id=world.make.client(),
            lines=[ReserveLine(item, 2, expected_price_lbp=600_000)],
            pickup_day=TODAY,
            source=OrderSource.SEARCH,
            idempotency_key="a",
        )
        world.settle(tx)

        applied = store.apply(store.upload(GOOD_FILE).id)

        old = store.items()[("PANADOL", "OLD")]
        assert (old.qty_on_hand, old.qty_reserved) == (2, 2)
        assert applied.summary["reserved_kept"] == 1

    def test_a_new_upload_replaces_the_one_that_was_waiting(self, store: Store) -> None:
        first = store.upload(GOOD_FILE)
        second = store.upload(GOOD_FILE)

        error = refusal(lambda: store.apply(first.id))

        assert error.code is Code.UPLOAD_NOT_VALIDATED
        assert store.apply(second.id).status == "APPLIED"
        assert refusal(lambda: store.apply(second.id)).code is Code.UPLOAD_NOT_VALIDATED


def test_a_medicine_that_becomes_controlled_is_withdrawn_everywhere(
    store: Store, world: World
) -> None:
    """R-C6, FR-24: open orders are cancelled, waiting claims end, listings are hidden."""
    item = world.make.item(pharmacy_id=store.pharmacy, product_id=store.panadol, qty_on_hand=5)
    client = world.make.client()
    tx = world.tx()
    (order,) = orders.reserve(
        tx,
        client_id=client,
        lines=[ReserveLine(item, 1, expected_price_lbp=600_000)],
        pickup_day=TODAY,
        source=OrderSource.SEARCH,
        idempotency_key="a",
    )
    watch = claims.create_watch(
        tx,
        client_id=world.make.client(),
        product_id=store.panadol,
        location=shared_location(34.437, 35.850),
        source=ClaimSource.SEARCH,
    )
    world.settle(tx)
    with world.as_owner():
        world.connection.exec_driver_sql(
            "UPDATE products SET controlled = true WHERE id = %s", (store.panadol,)
        )

    withdrawn = controlled.withdraw_everything(world.sessions(), world.clock)

    assert withdrawn == controlled.Withdrawn(orders=1, claims=1, items=0)
    # Running it again finds nothing left to do.
    assert controlled.withdraw_everything(world.sessions(), world.clock) == (
        controlled.Withdrawn(orders=0, claims=0, items=0)
    )
    assert (
        world.one("SELECT state FROM orders WHERE id = :o", o=order.id).state
        == "CANCELLED_BY_SYSTEM"
    )
    assert world.one("SELECT state FROM claims WHERE id = :c", c=watch.id).state == "EXPIRED"
    assert (
        world.one("SELECT qty_reserved FROM inventory_items WHERE id = :i", i=item).qty_reserved
        == 0
    )
    assert world.notifications(client) == ["CN-3", "CN-12"]
    # The client who was watching is told too.
    assert world.notifications(watch.client_id) == ["CN-11"]
    assert (
        world.all(
            "SELECT 1 FROM visible_listings(:t) WHERE inventory_item_id = :i", t=TODAY, i=item
        )
        == []
    )


def test_a_request_item_for_a_controlled_medicine_becomes_unavailable(world: World) -> None:
    """R-C6: the request carries on with its other medicines, or closes if it has none."""
    product = world.make.product()
    request = world.make.request()
    item = world.make.request_item(request, product_id=product)
    with world.as_owner():
        world.connection.exec_driver_sql(
            "UPDATE products SET controlled = true WHERE id = %s", (product,)
        )

    withdrawn = controlled.withdraw_everything(world.sessions(), world.clock)

    assert withdrawn == controlled.Withdrawn(orders=0, claims=0, items=1)
    assert world.one("SELECT state FROM request_items WHERE id = :i", i=item).state == "UNAVAILABLE"
    closed = world.one("SELECT state, outcome FROM sourcing_requests WHERE id = :r", r=request)
    assert (closed.state, closed.outcome) == ("CLOSED", "UNFULFILLED")
