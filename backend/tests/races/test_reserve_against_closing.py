"""A client taps a plan card of their request at the moment its 6 hours end (R-RQ9).

The tap read the request as open without a lock, and the request then closed before the
reservation counted for its medicine: a RESERVED box on a closed request, its medicine
"unavailable" with nothing secured. Now the tap locks the request's medicine first, so
either the request counts the reservation, or the tap is told the request closed.
"""

from datetime import timedelta
from typing import Any

import pytest

from dawalink.domain.orders import OrderSource
from dawalink.services import orders, requests
from dawalink.services.errors import Code, ServiceError
from dawalink.services.orders import ReserveLine
from tests.db.factories import NOW
from tests.races.conftest import Arena

PRICE = 600_000  # a 1,000,000 LBP box with 60 days left: 40% off


@pytest.mark.parametrize("attempt", range(3))
def test_a_tap_and_the_end_of_the_window_never_leave_a_box_that_secures_nothing(
    arena: Arena, attempt: int
) -> None:
    client = arena.make.client()
    product = arena.make.product()
    box = arena.make.item(product_id=product, days_left=60, qty_on_hand=1)
    request = arena.make.request(client_id=client, ends_at=NOW)
    item = arena.make.request_item(request, product_id=product, state="PROPOSED")

    def tap(tx: Any) -> Any:
        return orders.reserve(
            tx,
            client_id=client,
            lines=[ReserveLine(box, 1, expected_price_lbp=PRICE, request_item_id=item)],
            pickup_day=tx.today,
            source=OrderSource.ASSISTANT,
            idempotency_key=f"card-{attempt}",
        )

    close = arena.when(NOW + timedelta(minutes=1), lambda tx: requests.close_if_done(tx, request))

    tapped, _ = arena.together(tap, close, hold="request_items")

    if isinstance(tapped, ServiceError):
        assert tapped.code is Code.REQUEST_CLOSED
        assert arena.all("SELECT 1 FROM orders WHERE request_item_id = :i", i=item) == []
    else:
        assert not isinstance(tapped, Exception), tapped
        secured = arena.one("SELECT state, qty_secured FROM request_items WHERE id = :i", i=item)
        assert (secured.state, secured.qty_secured) == ("SECURED", 1)
