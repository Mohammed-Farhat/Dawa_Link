"""A pharmacy sends a stock file twice at the same moment: a double click, or a retry.

Only one file can wait for [Apply] (`uq_inventory_uploads_one_validated`). Both used to
find no file waiting, and the second insert broke that index: a server error. Now the
files of one pharmacy are read one after the other, and the last one replaces the first,
as a new file always does (SM-4).
"""

from typing import Any

from dawalink.services import inventory
from tests.races.conftest import Arena

FILE = b"product,batch,expiry,quantity\nRacetol,B1,2027-03,4\n"


def test_the_same_file_sent_twice_at_once_leaves_one_waiting(arena: Arena) -> None:
    owner = arena.make.user("pharmacist")
    pharmacy = arena.make.pharmacy(owner_user_id=owner)
    arena.make.product(moph_name="RACETOL", search_name="racetol")

    def send(tx: Any) -> Any:
        return inventory.validate_upload(tx, pharmacy, owner, "stock.csv", FILE).id

    results = arena.together(send, send, hold="inventory_uploads")

    for result in results:
        if isinstance(result, Exception):
            raise result
    rows = arena.all("SELECT id, status FROM inventory_uploads WHERE pharmacy_id = :p", p=pharmacy)
    assert sorted(row.status for row in rows) == ["DISCARDED", "VALIDATED"]
    waiting = next(row.id for row in rows if row.status == "VALIDATED")
    assert waiting in results
    staged = arena.all(
        "SELECT upload_id FROM inventory_upload_rows WHERE upload_id = ANY(:ids)",
        ids=[row.id for row in rows],
    )
    assert [row.upload_id for row in staged] == [waiting]
