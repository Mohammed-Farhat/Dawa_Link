"""A pharmacy's stock: edits and uploads (docs/04 SM-3, SM-4, R-U1 to R-U5, R-C6)."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from dawalink.domain.expiry import Zone
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
            "Panadol,,B5,soon,1\n"
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


class TestFilesAsExcelSavesThem:
    """The owner chose CSV only (2026-11-16, build plan Q40) because a spreadsheet saves
    one in two clicks. So the reader takes what a spreadsheet really writes."""

    def test_semicolons_empty_columns_and_a_windows_code_page(self, store: Store) -> None:
        """A computer whose decimal sign is a comma writes semicolons; Excel's plain
        "CSV" isn't UTF-8; a stray click leaves an empty column at the end."""
        tx = store.world.tx()
        content = (
            "Product;Strength;Batch;Expiry;Quantity;;\r\n"
            "Panadol;;B1;2026-12;10;;\r\n"
            "Concor;5mg;caf\u00e9-1;2027-01;2;;\r\n"
        ).encode("cp1252")

        upload = inventory.validate_upload(tx, store.pharmacy, store.owner, "s.csv", content)

        # The accent in the batch is the one row refused: a batch is plain letters.
        assert (upload.rows_ok, upload.rows_error) == (1, 1)
        assert upload.errors[0]["row"] == 3
        assert "batch" in upload.errors[0]["problem"]

    def test_tabs_work_too(self, store: Store) -> None:
        upload = store.upload("product\tbatch\texpiry\tquantity\nPanadol\tB1\t2026-12\t3\n")

        assert (upload.rows_ok, upload.rows_error) == (1, 0)

    @pytest.mark.parametrize("written", ["12/2026", "Dec-26", "Dec 2026", "2026/12", "2026/12/31"])
    def test_a_month_the_way_a_spreadsheet_rewrites_it(self, store: Store, written: str) -> None:
        """Typed "2026-12", a spreadsheet shows and saves "Dec-26"."""
        upload = store.upload(f"product,batch,expiry,quantity\nPanadol,B1,{written},3\n")
        store.apply(upload.id)

        assert str(store.items()[("PANADOL", "B1")].expiry_date) == "2026-12-31"

    @pytest.mark.parametrize("written", ["03/04/2027", "3-4-27"])
    def test_a_day_and_a_month_as_two_numbers_are_never_guessed(
        self, store: Store, written: str
    ) -> None:
        """3 April or 4 March? Reading it wrong would show a box as valid a month longer
        than it is. With no other date in the file to show which comes first, the row
        is refused with what to write instead."""
        upload = store.upload(f"product,batch,expiry,quantity\nPanadol,B1,{written},3\n")

        assert (upload.rows_ok, upload.rows_error) == (0, 1)
        assert "two ways" in upload.errors[0]["problem"]

    def test_an_excel_workbook_is_refused_with_what_to_do(self, store: Store, world: World) -> None:
        workbook = b"PK\x03\x04" + b"\x00" * 200

        error = refusal(
            lambda: inventory.validate_upload(
                world.tx(), store.pharmacy, store.owner, "stock.xlsx", workbook
            )
        )

        assert error.code is Code.UPLOAD_FAILED
        assert "Save As" in error.details["reason"]

    def test_more_problems_than_are_kept_are_still_counted(self, store: Store) -> None:
        rows = "".join(f"Nothing like this {n},B{n},2026-12,1\n" for n in range(520))

        upload = store.upload("product,batch,expiry,quantity\nPanadol,B0,2026-12,1\n" + rows)

        assert (upload.rows_total, upload.rows_ok, upload.rows_error) == (521, 1, 520)
        assert len(upload.errors) == 500


class TestTheFileThatWaits:
    def test_discarding_changes_nothing(self, store: Store, world: World) -> None:
        store.apply(store.upload("product,batch,expiry,quantity\nPanadol,B1,2026-12,10\n").id)
        waiting = store.upload("product,batch,expiry,quantity\nPanadol,B1,2026-12,1\n")
        found = inventory.waiting_upload(world.tx(), store.pharmacy)
        assert found is not None
        assert found.id == waiting.id

        tx = world.tx()
        inventory.discard_upload(tx, store.pharmacy, waiting.id)
        world.settle(tx)

        assert store.items()[("PANADOL", "B1")].qty_on_hand == 10
        assert inventory.waiting_upload(world.tx(), store.pharmacy) is None
        again = refusal(lambda: inventory.discard_upload(world.tx(), store.pharmacy, waiting.id))
        assert again.code is Code.UPLOAD_NOT_VALIDATED
        applied = refusal(lambda: inventory.apply_upload(world.tx(), store.pharmacy, waiting.id))
        assert applied.code is Code.UPLOAD_NOT_VALIDATED

    def test_the_errors_file_cannot_run_a_formula(self, store: Store, world: World) -> None:
        """FS-10: what a pharmacy typed in its file comes back in this one. A name that
        starts like a formula is refused whole, so the risk is in the middle of a file:
        a cell a spreadsheet would run must come back as text."""
        upload = store.upload("product,batch,expiry,quantity\n-2+3,B1,2026-12,1\n")
        row = inventory.own_upload(world.tx(), store.pharmacy, upload.id)

        lines = inventory.errors_csv(row).splitlines()

        assert lines[0] == "row,product,problem,did you mean"
        assert lines[1].startswith("2,'-2+3,no product with this name")

    def test_another_pharmacys_file_does_not_exist(self, store: Store, world: World) -> None:
        upload = store.upload("product,batch,expiry,quantity\nPanadol,B1,2026-12,10\n")
        other = world.make.pharmacy()

        assert refusal(lambda: inventory.own_upload(world.tx(), other, upload.id)).code is (
            Code.NOT_FOUND
        )
        assert refusal(lambda: inventory.discard_upload(world.tx(), other, upload.id)).code is (
            Code.NOT_FOUND
        )


class TestReadingTheStock:
    def test_each_box_with_its_zone_and_its_price_of_today(
        self, store: Store, world: World
    ) -> None:
        """R-T9: the zone and the price are computed when they are read, never stored."""
        make = world.make
        soon = make.item(
            pharmacy_id=store.pharmacy, product_id=store.panadol, batch="SOON", days_left=20
        )
        later = make.item(
            pharmacy_id=store.pharmacy, product_id=store.panadol, batch="LATER", days_left=200
        )
        far = make.item(
            pharmacy_id=store.pharmacy, product_id=store.concor, batch="FAR", days_left=400
        )
        make.item(product_id=store.panadol, batch="NOT-MINE", days_left=20)

        lines = inventory.stock_lines(world.tx(), store.pharmacy)

        assert [line.item.id for line in lines] == [soon, later, far]
        assert [line.zone.value for line in lines] == ["NEAR_EXPIRY", "EARLY_RELEASE", "PRIVATE"]
        # 60% off a public price of 1,000,000 in the last 30 days (N-4).
        assert lines[0].price_lbp == 400_000
        # A private box has no price for a client.
        assert lines[1].price_lbp is None
        assert lines[2].price_lbp is None

    def test_finding_by_name_batch_or_zone(self, store: Store, world: World) -> None:
        make = world.make
        make.item(pharmacy_id=store.pharmacy, product_id=store.panadol, batch="A1", days_left=20)
        make.item(pharmacy_id=store.pharmacy, product_id=store.concor, batch="ZX-9", days_left=200)

        def read(query: str = "", zone: Zone | None = None) -> list[str]:
            lines = inventory.stock_lines(world.tx(), store.pharmacy, query=query, zone=zone)
            return [line.item.batch for line in lines]

        assert read(query="pana") == ["A1"]
        assert read(query="zx-9") == ["ZX-9"]
        assert read(zone=Zone.EARLY_RELEASE) == ["ZX-9"]
        assert read(query="nothing") == []


def test_a_name_and_strength_that_several_catalog_rows_share_is_never_guessed(
    store: Store, world: World
) -> None:
    """The Ministry lists some medicines several times, with one name and one strength:
    other pack sizes, other makers, each with its own price. A file can't say which one;
    the row says so and sends the pharmacist to the form, where the box is chosen."""
    for pack in ("B/12", "B/24"):
        world.make.product(
            moph_name="TWINOL",
            search_name="twinol",
            dosage_text="500mg",
            form_text="Tablet",
            presentation_text=pack,
        )

    upload = store.upload("product,strength,batch,expiry,quantity\nTwinol,500mg,B1,2026-12,3\n")

    (error,) = upload.errors
    assert (upload.rows_ok, upload.rows_error) == (0, 1)
    assert "add this box by hand" in error["problem"]
    assert error["did_you_mean"] == ["Tablet B/12", "Tablet B/24"]


class TestWhatExcelReallySaved:
    """Typed into the template in Excel on a computer set to US dates, then File, Save
    As, CSV (2026-11-16). The full dates came out month first, the months came out as
    names, a batch lost its leading zeros."""

    SAVED = (
        "product,strength,batch,expiry,quantity\n"
        "Panadol,,A1,3/31/2027,6\n"
        "Panadol,,123,Mar-27,4\n"
        "Panadol,,A3,2027-03,2\n"
        "Panadol,,A5,3/4/2027,1\n"
    )

    def test_its_dates_are_read_because_one_of_them_shows_the_order(self, store: Store) -> None:
        upload = store.upload(self.SAVED)
        store.apply(upload.id)

        assert (upload.rows_ok, upload.rows_error) == (4, 0)
        expiries = {batch: str(row.expiry_date) for (_, batch), row in store.items().items()}
        # 3/31 can only be 31 March, so 3/4 is 4 March: the US way, not the Lebanese one.
        assert expiries == {
            "A1": "2027-03-31",
            "123": "2027-03-31",
            "A3": "2027-03-31",
            "A5": "2027-03-04",
        }

    def test_the_same_dates_written_the_lebanese_way(self, store: Store) -> None:
        upload = store.upload(
            "product,batch,expiry,quantity\nPanadol,A1,31/03/2027,6\nPanadol,A5,3/4/2027,1\n"
        )
        store.apply(upload.id)

        assert str(store.items()[("PANADOL", "A5")].expiry_date) == "2027-04-03"

    def test_a_file_whose_dates_disagree_is_not_guessed(self, store: Store) -> None:
        upload = store.upload(
            "product,batch,expiry,quantity\n"
            "Panadol,A1,31/03/2027,6\nPanadol,A2,3/31/2027,6\nPanadol,A3,03/2027,1\n"
        )

        assert (upload.rows_ok, upload.rows_error) == (1, 2)

    def test_the_template_survives_a_trip_through_a_spreadsheet(self, store: Store) -> None:
        """Its examples are months only: a full date would come back rewritten."""
        expiries = [line.split(",")[3] for line in inventory.TEMPLATE_CSV.splitlines()[1:]]

        assert expiries == ["2027-03", "2027-06"]


class TestABoxNoFileCanName:
    def test_it_is_refused_in_a_file_and_never_set_to_zero_by_one(
        self, store: Store, world: World
    ) -> None:
        """R-U2 sets to 0 what a file doesn't name. But a medicine the Ministry lists
        twice under one name and strength can't be named by any file: its box is added
        by hand, and the next file must leave it alone."""
        packs = [
            world.make.product(
                moph_name="TWINOL",
                search_name="twinol",
                dosage_text="500mg",
                presentation_text=pack,
            )
            for pack in ("B/12", "B/24")
        ]
        tx = world.tx()
        by_hand = inventory.add_item(
            tx,
            store.pharmacy,
            product_id=packs[1],
            batch="T1",
            expiry_date=TODAY + 60 * DAY,
            quantity=7,
        )
        world.settle(tx)
        store.apply(store.upload("product,batch,expiry,quantity\nPanadol,P1,2026-12,5\n").id)

        upload = store.upload(
            "product,strength,batch,expiry,quantity\n"
            "Twinol,500mg,T1,2026-12,9\n"
            "Concor,5mg,C1,2026-12,2\n"
        )
        applied = store.apply(upload.id)

        items = store.items()
        # The file's Twinol row was refused; the box added by hand is as it was.
        assert (upload.rows_ok, upload.rows_error) == (1, 1)
        assert items[("TWINOL", "T1")].qty_on_hand == 7
        assert items[("TWINOL", "T1")].id == by_hand.id
        # Panadol can be named, and wasn't: set to 0, as R-U2 says.
        assert items[("PANADOL", "P1")].qty_on_hand == 0
        assert (upload.summary["zeroed"], applied.summary["new"]) == (1, 1)
