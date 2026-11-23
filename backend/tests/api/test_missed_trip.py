"""A plan card missed whole is one missed pickup, through the API (R-N1, R-N3; A#10).

The boxes one tap reserved together are one trip: one [I picked it up] covers every box
of it, the case says which order numbers it covers, and [Clear] on any of them clears
the trip and lifts the pause it caused.
"""

import uuid
from typing import Any

from dawalink.domain.clock import beirut_date
from dawalink.domain.orders import OrderSource
from dawalink.services import orders
from dawalink.services.orders import ReserveLine
from tests.api.conftest import Api, code_of

ADMIN = "/api/v1/admin"


def price_of(api: Api, box: uuid.UUID) -> int:
    today = beirut_date(api.world.clock.now())
    return api.world.one(  # type: ignore[no-any-return]
        "SELECT price_lbp FROM visible_listings(:today) WHERE inventory_item_id = :id",
        today=today,
        id=box,
    )[0]


def reserve_and_miss(api: Api, client: uuid.UUID, boxes: list[uuid.UUID]) -> list[Any]:
    """One tap on these boxes (a plan card when there are several), then the deadline
    passes and the clock check expires them."""
    tx = api.world.tx()
    made = orders.reserve(
        tx,
        client_id=client,
        lines=[ReserveLine(box, 1, price_of(api, box)) for box in boxes],
        pickup_day=beirut_date(api.world.clock.now()),
        source=OrderSource.ASSISTANT,
        idempotency_key=f"tap-{uuid.uuid4()}",
    )
    api.world.settle(tx)
    api.world.later(days=1)
    api.world.clock_tasks().expire_reservations()
    return made


def test_one_contest_covers_the_trip_and_one_clear_lifts_the_pause(api: Api) -> None:
    make = api.world.make
    pharmacy = make.pharmacy()
    boxes = [make.item(pharmacy_id=pharmacy, product_id=make.product()) for _ in range(3)]
    client = api.client()
    login = api.token(client)
    admin = api.token(make.user("admin", totp_secret=b"not-a-real-secret"))
    http = api.http()
    reserve_and_miss(api, client, boxes[:1])
    first, second = reserve_and_miss(api, client, boxes[1:])
    paused = api.world.one("SELECT status FROM client_profiles WHERE user_id = :id", id=client)[0]

    contested = http.post(f"/api/v1/reservations/{second.id}/contest", headers=login)
    sibling = http.get(f"/api/v1/reservations/{first.id}", headers=login)
    again = http.post(f"/api/v1/reservations/{first.id}/contest", headers=login)
    (escalation,) = http.get(f"{ADMIN}/escalations", headers=admin).json()["items"]
    case = f"{ADMIN}/escalations/{escalation['id']}"
    waiting = http.get(case, headers=admin).json()["contested"]
    listed = http.get(f"{ADMIN}/clients/{client}", headers=admin).json()["client"]
    overview = http.get(f"{ADMIN}/overview", headers=admin).json()
    cleared = http.post(
        f"{ADMIN}/reservations/{first.id}/clear-no-show",
        json={"reason": "The pharmacy confirmed the pickup."},
        headers=admin,
    )

    # Two missed trips (one alone, one card of two): paused once, as for two misses.
    assert paused == "PAUSED"
    assert (contested.status_code, contested.json()["contestable"]) == (200, False)
    assert sibling.json()["contestable"] is False
    assert (again.status_code, code_of(again)) == (409, "NOT_CONTESTABLE")
    assert second.ref in escalation["summary"]
    assert f"One trip with {first.ref}" in escalation["summary"]
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["client"]["status"] == "ACTIVE"
    counted = {
        row.ref: row.counts_as_no_show
        for row in api.world.all(
            "SELECT ref, counts_as_no_show FROM orders WHERE client_id = :c", c=client
        )
    }
    assert (counted[first.ref], counted[second.ref]) == (False, False)
    # The case shows the whole trip, and after [Clear] that it no longer counts (B#61).
    trip = {(first.ref, True), (second.ref, True)}
    assert {(row["ref"], row["counts_as_no_show"]) for row in waiting} == trip
    after = http.get(case, headers=admin).json()["contested"]
    assert {(row["ref"], row["counts_as_no_show"]) for row in after} == {
        (first.ref, False),
        (second.ref, False),
    }
    # The admin counts trips, as the pause does: two missed pickups, one contest waiting.
    assert (listed["no_shows"], listed["contested"]) == (2, 1)
    assert overview["contests_waiting"] == 1


def test_the_client_reads_one_missed_pickup_for_a_plan_card_of_two(api: Api) -> None:
    """R-N1: the profile counts trips, as the pause does. A card of two boxes missed once
    is "1 of 2", never "2 of 2" with no pause."""
    make = api.world.make
    pharmacy = make.pharmacy()
    boxes = [make.item(pharmacy_id=pharmacy, product_id=make.product()) for _ in range(2)]
    client = api.client()
    http = api.http(assistant=False)
    reserve_and_miss(api, client, boxes)

    me = http.get("/api/v1/auth/me", headers=api.token(client)).json()["client"]

    assert me["status"] == "ACTIVE"
    assert (me["missed_pickups_30d"], me["missed_pickups_before_pause"]) == (1, 2)


def test_a_pause_leaves_one_open_flag_that_the_admin_reads(api: Api) -> None:
    """R-AB: one no-show flag per client while it is open. Three missed trips pause the
    client twice; the one flag shows the last count, and the admin reads it."""
    make = api.world.make
    pharmacy = make.pharmacy()
    boxes = [make.item(pharmacy_id=pharmacy, product_id=make.product()) for _ in range(4)]
    client = api.client()
    admin = api.token(make.user("admin", totp_secret=b"not-a-real-secret"))
    http = api.http(assistant=False)
    tx = api.world.tx()
    for trip in (boxes[:1], boxes[1:3], boxes[3:]):
        orders.reserve(
            tx,
            client_id=client,
            lines=[ReserveLine(box, 1, price_of(api, box)) for box in trip],
            pickup_day=beirut_date(api.world.clock.now()),
            source=OrderSource.ASSISTANT,
            idempotency_key=f"tap-{uuid.uuid4()}",
        )
    api.world.settle(tx)
    api.world.later(days=1)
    api.world.clock_tasks().expire_reservations()

    shown = http.get(f"{ADMIN}/clients/{client}", headers=admin).json()["flags"]
    stored = api.world.all(
        "SELECT rule, state, evidence FROM abuse_flags WHERE subject_id = :c", c=client
    )

    assert [(flag["rule"], flag["evidence"]) for flag in shown] == [
        ("no_show_pause", {"counted_no_shows": 3})
    ]
    assert [(row.rule, row.state, row.evidence) for row in stored] == [
        ("no_show_pause", "OPEN", {"counted_no_shows": 3})
    ]
