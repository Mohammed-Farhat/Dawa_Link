"""The pharmacy's stock over HTTP: its boxes, its prices, its stock files (docs/06 §6.9;
docs/04 SM-3, SM-4, R-U1 to R-U5, R-PR1, INV-16; docs/03 PS-6, PS-7; docs/10 TH-34)."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import Api, code_of
from tests.api.test_pharmacy import login_of
from tests.db.factories import TODAY

UPLOADS = "/api/v1/pharmacy/inventory/uploads"
HEADER = "product,strength,batch,expiry,quantity\n"


@dataclass
class Shop:
    api: Api
    http: TestClient
    pharmacy: uuid.UUID
    headers: dict[str, str]
    panadol: uuid.UUID
    concor: uuid.UUID

    def get(self, path: str, **params: Any) -> Any:
        return self.http.get(f"/api/v1/pharmacy{path}", params=params, headers=self.headers)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.http.post(f"/api/v1/pharmacy{path}", json=body or {}, headers=self.headers)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self.http.patch(f"/api/v1/pharmacy{path}", json=body, headers=self.headers)

    def upload(self, text: str | bytes, name: str = "stock.csv") -> Any:
        content = text.encode("utf-8") if isinstance(text, str) else text
        return self.http.post(
            UPLOADS, files={"file": (name, content, "text/csv")}, headers=self.headers
        )

    def box(self, product: uuid.UUID | None = None, **values: Any) -> uuid.UUID:
        made: uuid.UUID = self.api.world.make.item(
            pharmacy_id=self.pharmacy, product_id=product or self.panadol, **values
        )
        return made

    def stock(self, **params: Any) -> list[dict[str, Any]]:
        answer = self.get("/inventory", **params)
        assert answer.status_code == 200, answer.text
        items: list[dict[str, Any]] = answer.json()["items"]
        return items


@pytest.fixture
def shop(api: Api) -> Shop:
    make = api.world.make
    pharmacy = make.pharmacy(name="Hamra Pharmacy")
    return Shop(
        api,
        api.http(assistant=False),
        pharmacy,
        login_of(api, pharmacy),
        make.product(
            moph_name="PANADOL",
            search_name="panadol",
            dosage_text="500mg",
            public_price_lbp=1_000_000,
        ),
        make.product(moph_name="CONCOR", search_name="concor", dosage_text="5mg"),
    )


class TestTheStockList:
    @pytest.mark.rows_by_hand
    def test_each_box_with_its_zone_its_price_and_whether_clients_see_it(self, shop: Shop) -> None:
        shop.box(batch="SOON", days_left=20, qty_on_hand=5, qty_reserved=2)
        shop.box(batch="LATER", days_left=200)
        shop.box(batch="EMPTY", days_left=30, qty_on_hand=0)

        soon, empty, later = shop.stock()

        assert (soon["batch"], soon["zone"], soon["days_left"]) == ("SOON", "NEAR_EXPIRY", 20)
        assert (soon["qty_on_hand"], soon["qty_reserved"], soon["qty_available"]) == (5, 2, 3)
        assert soon["visible"] is True
        # 60% off in the last 30 days (N-4), with the public price next to it.
        assert soon["price"]["effective"]["lbp"] == 400_000
        assert soon["price"]["system"]["lbp"] == 400_000
        assert (soon["price"]["override"], soon["price"]["discount_pct"]) == (None, 60)
        assert soon["product"]["public_price"]["lbp"] == 1_000_000
        # Nothing left to sell, or not near its expiry yet: clients don't see it.
        assert (empty["batch"], empty["visible"]) == ("EMPTY", False)
        assert (later["zone"], later["visible"], later["price"]["effective"]) == (
            "EARLY_RELEASE",
            False,
            None,
        )

    def test_the_listings_are_the_boxes_near_their_expiry(self, shop: Shop) -> None:
        shop.box(batch="SOON", days_left=20)
        shop.box(shop.concor, batch="LATER", days_left=200)

        assert [box["batch"] for box in shop.stock(zone="NEAR_EXPIRY")] == ["SOON"]
        assert [box["batch"] for box in shop.stock(q="conc")] == ["LATER"]
        assert [box["batch"] for box in shop.stock(q="soon")] == ["SOON"]

    def test_a_percent_sign_or_an_underscore_in_the_search_is_only_itself(self, shop: Shop) -> None:
        """They mean "anything" to the database: typed by a pharmacist, they must not."""
        shop.box(batch="SOON", days_left=20)
        shop.box(shop.concor, batch="LOT_7", days_left=200)

        assert shop.stock(q="%") == []
        assert shop.stock(q="s%n") == []
        assert shop.stock(q="s__n") == []
        assert [box["batch"] for box in shop.stock(q="t_7")] == ["LOT_7"]

    def test_it_comes_in_pages(self, shop: Shop) -> None:
        for number in range(3):
            shop.box(batch=f"B{number}", days_left=10 + number)

        first = shop.get("/inventory", limit=2).json()
        rest = shop.get("/inventory", limit=2, cursor=first["next_cursor"]).json()

        assert [box["batch"] for box in first["items"]] == ["B0", "B1"]
        assert ([box["batch"] for box in rest["items"]], rest["next_cursor"]) == (["B2"], None)

    def test_another_pharmacys_stock_does_not_exist(self, shop: Shop) -> None:
        """A pharmacy's full inventory is private (docs/03 §2.1)."""
        theirs = shop.api.world.make.item(product_id=shop.panadol)

        answer = shop.patch(f"/inventory/items/{theirs}", {"qty_on_hand": 0})

        assert shop.stock() == []
        assert (answer.status_code, code_of(answer)) == (404, "NOT_FOUND")

    @pytest.mark.parametrize("status", ["PENDING", "REJECTED", "SUSPENDED"])
    def test_only_an_approved_pharmacy_has_an_inventory(self, api: Api, status: str) -> None:
        """P-D2."""
        pharmacy = api.world.make.pharmacy(status)
        headers = login_of(api, pharmacy)
        http = api.http(assistant=False)

        for answer in (
            http.get("/api/v1/pharmacy/inventory", headers=headers),
            http.get("/api/v1/pharmacy/inventory/uploads/waiting", headers=headers),
            http.post(UPLOADS, files={"file": ("s.csv", HEADER.encode())}, headers=headers),
        ):
            assert (answer.status_code, code_of(answer)) == (403, "PHARMACY_NOT_APPROVED")


class TestEditingABox:
    def test_a_box_typed_by_hand(self, shop: Shop) -> None:
        expiry = (TODAY + timedelta(days=45)).isoformat()
        body = {"product_id": str(shop.panadol), "batch": " A12 ", "expiry_date": expiry, "qty": 4}

        added = shop.post("/inventory/items", body)
        twice = shop.post("/inventory/items", body)

        assert added.status_code == 201
        assert (added.json()["batch"], added.json()["qty_on_hand"]) == ("A12", 4)
        assert added.json()["visible"] is True
        assert (twice.status_code, code_of(twice)) == (409, "ITEM_EXISTS")

    def test_what_cannot_be_added(self, shop: Shop) -> None:
        make = shop.api.world.make
        controlled = make.product(moph_name="TRAMAL", search_name="tramal", controlled=True)
        soon = (TODAY + timedelta(days=45)).isoformat()
        good = {"product_id": str(shop.panadol), "batch": "A1", "expiry_date": soon, "qty": 1}

        expired = shop.post(
            "/inventory/items", good | {"expiry_date": (TODAY - timedelta(days=1)).isoformat()}
        )
        bad_batch = shop.post("/inventory/items", good | {"batch": "=1+1"})
        not_listed = shop.post("/inventory/items", good | {"product_id": str(controlled)})
        unknown = shop.post("/inventory/items", good | {"product_id": str(uuid.uuid4())})

        assert code_of(expired) == "VALIDATION_ERROR"
        assert bad_batch.json()["error"]["details"]["field"] == "batch"
        assert code_of(not_listed) == "PRODUCT_NOT_ALLOWED"
        assert (unknown.status_code, code_of(unknown)) == (404, "NOT_FOUND")
        assert shop.stock() == []

    @pytest.mark.rows_by_hand
    def test_a_lower_quantity_never_takes_a_reserved_pack_away(self, shop: Shop) -> None:
        """R-U3: after a sale in the shop the pharmacy types what is left. Packs a client
        reserved stay: to give one up, [Not available] on the reservation."""
        box = shop.box(qty_on_hand=5, qty_reserved=2)

        fine = shop.patch(f"/inventory/items/{box}", {"qty_on_hand": 3})
        too_low = shop.patch(f"/inventory/items/{box}", {"qty_on_hand": 0})

        assert (fine.json()["item"]["qty_on_hand"], fine.json()["reserved_kept"]) == (3, False)
        assert (too_low.json()["item"]["qty_on_hand"], too_low.json()["reserved_kept"]) == (2, True)
        assert too_low.json()["item"]["qty_available"] == 0

    def test_its_own_price_a_donation_and_back_to_the_systems_price(self, shop: Shop) -> None:
        """R-PR1: from 0 (a donation) up to the public price, never above."""
        box = shop.box(days_left=20)
        path = f"/inventory/items/{box}"

        own = shop.patch(path, {"price_override_lbp": 250_000}).json()["item"]["price"]
        free = shop.patch(path, {"price_override_lbp": 0}).json()["item"]["price"]
        above = shop.patch(path, {"price_override_lbp": 1_000_001})
        back = shop.patch(path, {"price_override_lbp": None}).json()["item"]["price"]

        assert (own["effective"]["lbp"], own["override"]["lbp"], own["discount_pct"]) == (
            250_000,
            250_000,
            75,
        )
        # The system's price stays in view, to go back to.
        assert own["system"]["lbp"] == 400_000
        assert (free["effective"]["lbp"], free["discount_pct"]) == (0, 100)
        assert (above.status_code, code_of(above)) == (422, "PRICE_ABOVE_PUBLIC")
        assert (back["effective"]["lbp"], back["override"]) == (400_000, None)

    def test_a_paused_box_is_hidden_from_clients_until_it_is_resumed(self, shop: Shop) -> None:
        box = shop.box(days_left=20)
        listed = "SELECT count(*) FROM visible_listings(:today) WHERE inventory_item_id = :id"

        paused = shop.patch(f"/inventory/items/{box}", {"paused": True}).json()["item"]
        hidden = shop.api.world.one(listed, today=TODAY, id=box)[0]
        resumed = shop.patch(f"/inventory/items/{box}", {"paused": False}).json()["item"]

        assert (paused["paused"], paused["visible"], hidden) == (True, False, 0)
        assert (resumed["paused"], resumed["visible"]) == (False, True)
        assert shop.api.world.one(listed, today=TODAY, id=box)[0] == 1

    def test_the_pharmacy_decides_when_its_boxes_are_listed(self, shop: Shop) -> None:
        """The owner, 2026-11-19 (BLD-D44). It starts as before: everything with 180 days
        left or fewer. With "at 30 days", a box with 90 days left is held back."""
        near, far = shop.box(days_left=20), shop.box(shop.concor, days_left=90)

        def state() -> dict[str, tuple[bool, bool]]:
            return {item["id"]: (item["visible"], item["held_back"]) for item in shop.stock()}

        before = state()
        me = shop.patch("/me", {"auto_list_days": 30})
        after = state()

        assert before == {str(near): (True, False), str(far): (True, False)}
        assert (me.status_code, me.json()["auto_list_days"]) == (200, 30)
        assert me.json()["auto_list_choices"] == [0, 30, 60, 90, 180]
        assert after == {str(near): (True, False), str(far): (False, True)}

    def test_list_now_lists_a_box_that_was_held_back_and_takes_it_back(self, shop: Shop) -> None:
        shop.patch("/me", {"auto_list_days": 0})
        box = shop.box(days_left=90)
        listed = "SELECT count(*) FROM visible_listings(:today) WHERE inventory_item_id = :id"

        waiting = shop.stock()[0]
        by_hand = shop.patch(f"/inventory/items/{box}", {"listed": True}).json()["item"]
        seen = shop.api.world.one(listed, today=TODAY, id=box)[0]
        back = shop.patch(f"/inventory/items/{box}", {"listed": False}).json()["item"]

        assert (waiting["visible"], waiting["held_back"], waiting["listed_by_hand"]) == (
            False,
            True,
            False,
        )
        assert (by_hand["visible"], by_hand["held_back"], by_hand["listed_by_hand"], seen) == (
            True,
            False,
            True,
            1,
        )
        assert (back["visible"], back["held_back"], back["listed_by_hand"]) == (False, True, False)

    def test_what_listing_by_hand_refuses(self, shop: Shop) -> None:
        too_far = shop.box(days_left=200)
        box = shop.box(shop.concor, days_left=90)

        far = shop.patch(f"/inventory/items/{too_far}", {"listed": True})
        both = shop.patch(f"/inventory/items/{box}", {"listed": True, "paused": True})
        odd_rule = shop.patch("/me", {"auto_list_days": 45})
        too_long = shop.patch("/me", {"auto_list_days": 365})

        for answer in (far, both, odd_rule, too_long):
            assert (answer.status_code, code_of(answer)) == (422, "VALIDATION_ERROR"), answer.text
        assert shop.get("/me").json()["auto_list_days"] == 180

    def test_only_what_is_sent_changes(self, shop: Shop) -> None:
        box = shop.box(days_left=20, qty_on_hand=5, price_override_lbp=300_000)

        changed = shop.patch(f"/inventory/items/{box}", {"qty_on_hand": 4}).json()["item"]

        assert (changed["qty_on_hand"], changed["price"]["override"]["lbp"]) == (4, 300_000)
        assert changed["paused"] is False


class TestStockFiles:
    def test_the_template_is_a_file_the_reader_accepts(self, shop: Shop) -> None:
        template = shop.get("/inventory/template")

        assert template.headers["content-type"].startswith("text/csv")
        assert "attachment" in template.headers["content-disposition"]
        assert template.text.lstrip("﻿").startswith(HEADER.strip())
        # Uploaded as it is: read, and its example rows are reported, not applied.
        read = shop.upload(template.content)
        assert (read.status_code, read.json()["rows_ok"], read.json()["rows_error"]) == (201, 0, 2)

    def test_read_summarised_and_applied(self, shop: Shop) -> None:
        """SM-4: nothing changes until [Apply]; then the file is the stock."""
        old = shop.box(batch="OLD", days_left=20, qty_on_hand=5)

        read = shop.upload(
            HEADER + "Panadol,,A1,2027-03,10\nPanadoll,,A2,2027-03,1\nConcor,5mg,C1,2027-01,2\n"
        )

        summary = read.json()
        assert read.status_code == 201
        assert (summary["status"], summary["rows_total"]) == ("VALIDATED", 3)
        assert (summary["rows_ok"], summary["rows_error"]) == (2, 1)
        assert summary["summary"] == {
            "new": 2,
            "changed": 0,
            "zeroed": 1,
            "reserved_kept": 0,
            "left_alone": 0,
        }
        assert summary["errors"] == [
            {
                "row": 3,
                "product": "Panadoll",
                "problem": "no product with this name",
                "did_you_mean": ["PANADOL"],
            }
        ]
        assert [box["batch"] for box in shop.stock()] == ["OLD"]
        assert shop.get("/inventory/uploads/waiting").json()["upload"]["id"] == summary["id"]

        applied = shop.post(f"/inventory/uploads/{summary['id']}/apply")

        assert (applied.status_code, applied.json()["status"]) == (200, "APPLIED")
        boxes = {box["batch"]: box["qty_on_hand"] for box in shop.stock()}
        # R-U2: what the file doesn't name is set to 0, and kept.
        assert boxes == {"OLD": 0, "A1": 10, "C1": 2}
        assert shop.get("/inventory/uploads/waiting").json() == {"upload": None}
        twice = shop.post(f"/inventory/uploads/{summary['id']}/apply")
        assert (twice.status_code, code_of(twice)) == (409, "UPLOAD_NOT_VALIDATED")
        del old

    def test_discarded_and_nothing_changed(self, shop: Shop) -> None:
        shop.box(batch="OLD", qty_on_hand=5)
        read = shop.upload(HEADER + "Panadol,,A1,2027-03,10\n").json()

        discarded = shop.post(f"/inventory/uploads/{read['id']}/discard")

        assert discarded.status_code == 204
        assert {box["batch"]: box["qty_on_hand"] for box in shop.stock()} == {"OLD": 5}
        assert shop.get("/inventory/uploads/waiting").json() == {"upload": None}

    def test_the_errors_come_as_a_file_too(self, shop: Shop) -> None:
        read = shop.upload(HEADER + "Panadoll,,A2,2027-03,1\n").json()

        errors = shop.get(f"/inventory/uploads/{read['id']}/errors.csv")

        assert errors.headers["content-type"].startswith("text/csv")
        lines = errors.text.lstrip("﻿").splitlines()
        assert lines == [
            "row,product,problem,did you mean",
            "2,Panadoll,no product with this name,PANADOL",
        ]

    def test_another_pharmacys_file_does_not_exist(self, shop: Shop, api: Api) -> None:
        read = shop.upload(HEADER + "Panadol,,A1,2027-03,10\n").json()
        other = login_of(api, api.world.make.pharmacy())

        for answer in (
            shop.http.get(f"{UPLOADS}/{read['id']}/errors.csv", headers=other),
            shop.http.post(f"{UPLOADS}/{read['id']}/apply", headers=other),
            shop.http.post(f"{UPLOADS}/{read['id']}/discard", headers=other),
        ):
            assert (answer.status_code, code_of(answer)) == (404, "NOT_FOUND")

    def test_a_file_that_cannot_be_used_says_why(self, shop: Shop) -> None:
        workbook = shop.upload(b"PK\x03\x04" + b"\x00" * 100, name="stock.xlsx")
        wrong_columns = shop.upload("name,qty\nPanadol,1\n")
        no_file = shop.http.post(UPLOADS, headers=shop.headers)

        assert (workbook.status_code, code_of(workbook)) == (422, "UPLOAD_FAILED")
        assert "Save As" in workbook.json()["error"]["details"]["reason"]
        assert "columns" in wrong_columns.json()["error"]["details"]["reason"]
        assert no_file.status_code == 422

    def test_a_zero_byte_anywhere_in_a_file_is_refused_never_a_crash(self, shop: Shop) -> None:
        """A zero byte can't be stored. Near the start it marks a file that is not text;
        further down it would have reached the database."""
        rows = "".join(f"Panadol,500mg,B{number},2027-03,1\n" for number in range(200))
        early = shop.upload((HEADER + "Panadol,500mg,B\x001,2027-03,1\n").encode())
        late = shop.upload((HEADER + rows + "Panadol,500mg,LATE\x00,2027-03,1\n").encode())

        assert len(rows) > 4096
        for answer in (early, late):
            assert (answer.status_code, code_of(answer)) == (422, "UPLOAD_FAILED"), answer.text
        assert shop.api.world.all("SELECT 1 FROM inventory_upload_rows") == []

    def test_a_barcode_in_the_quantity_column_is_a_row_error_never_a_crash(
        self, shop: Shop
    ) -> None:
        """A#9: the number used to reach the database and fail the whole file with a
        500. A row's problem never blocks the others (R-U5)."""
        answer = shop.upload(
            HEADER + "Panadol,,A1,2027-03,6281086011234\nPanadol,,A2,2027-03,500000\n"
            "Panadol,,A3,2027-03,4\n"
        )

        assert answer.status_code == 201, answer.text
        read = answer.json()
        assert (read["rows_ok"], read["rows_error"]) == (1, 2)
        assert [error["problem"] for error in read["errors"]] == [
            "the quantity must be 100,000 or fewer"
        ] * 2


class TestTheSizeOfWhatIsSent:
    """docs/10 TH-34: a file is refused by its announced size before a byte of it is
    read, and nothing is read whose size wasn't announced."""

    def test_a_file_over_five_megabytes_is_refused(self, shop: Shop) -> None:
        answer = shop.upload(HEADER.encode() + b"x" * (5 * 1024 * 1024 + 70_000))

        assert (answer.status_code, code_of(answer)) == (413, "FILE_TOO_LARGE")

    def test_a_body_sent_in_chunks_is_refused_on_every_path(self, shop: Shop) -> None:
        """Sent without its length, a body could be of any size: it is never read."""

        def pieces() -> Iterator[bytes]:
            yield b"x" * 1024

        file = shop.http.post(
            UPLOADS,
            content=pieces(),
            headers=shop.headers | {"Content-Type": "multipart/form-data; boundary=x"},
        )
        other = shop.http.post(
            f"/api/v1/pharmacy/inventory/uploads/{uuid.uuid4()}/apply",
            content=pieces(),
            headers=shop.headers,
        )

        assert (file.status_code, code_of(file)) == (413, "FILE_TOO_LARGE")
        assert (other.status_code, code_of(other)) == (413, "BODY_TOO_LARGE")

    def test_a_file_sent_to_another_path_gets_the_small_limit(self, shop: Shop) -> None:
        """Only the upload's own path takes megabytes."""
        box = shop.box()

        answer = shop.http.patch(
            f"/api/v1/pharmacy/inventory/items/{box}",
            files={"file": ("s.csv", b"x" * 100_000)},
            headers=shop.headers,
        )

        assert (answer.status_code, code_of(answer)) == (413, "BODY_TOO_LARGE")
