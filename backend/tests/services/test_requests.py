"""Sourcing requests: from [Start sourcing] to closing (docs/04 SM-8, R-RQ, ADR-002)."""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from dawalink.domain.orders import OrderSource
from dawalink.domain.vocabulary import ClaimSource
from dawalink.services import claims, counter, orders, requests
from dawalink.services.errors import Code, ServiceError
from dawalink.services.orders import ReserveLine
from dawalink.services.requests import RequestLine
from dawalink.services.travel import shared_location
from tests.db.factories import NOW, TODAY
from tests.services.conftest import World

HAMRA = shared_location(33.8961, 35.4832)
DAY = timedelta(days=1)


@dataclass
class Case:
    """A client asking for two medicines, with one pharmacy nearby."""

    world: World
    client: uuid.UUID
    concor: uuid.UUID
    aspirin: uuid.UUID
    pharmacy: uuid.UUID

    def start(self, *lines: RequestLine, key: str = "start-1", **values: Any) -> uuid.UUID:
        tx = self.world.tx()
        asked: dict[str, Any] = {
            "client_id": self.client,
            "lines": lines or (RequestLine(self.concor, qty=2), RequestLine(self.aspirin)),
            "location": HAMRA,
            "alternatives_ok": False,
            "idempotency_key": key,
        }
        request = requests.create_request(tx, **(asked | values))
        self.world.settle(tx)
        return request.id

    def request(self, request_id: uuid.UUID) -> Any:
        return self.world.one("SELECT * FROM sourcing_requests WHERE id = :id", id=request_id)

    def items(self, request_id: uuid.UUID) -> list[Any]:
        return self.world.all(
            "SELECT * FROM request_items WHERE request_id = :id ORDER BY position", id=request_id
        )

    def thread(self, request_id: uuid.UUID) -> list[tuple[str, Any]]:
        """The request's own conversation: `(kind, what it says)` per message."""
        rows = self.world.all(
            "SELECT m.kind, m.text_redacted, m.cards FROM chat_messages m "
            "JOIN conversations c ON c.id = m.conversation_id "
            "WHERE c.request_id = :id ORDER BY m.seq",
            id=request_id,
        )
        return [
            (
                row.kind,
                json.loads(row.text_redacted)["type"]
                if row.kind == "event"
                else row.cards[0]["template"],
            )
            for row in rows
        ]

    def stock(self, product: uuid.UUID, units: int = 5, **values: Any) -> uuid.UUID:
        defaults = {"pharmacy_id": self.pharmacy, "product_id": product, "days_left": 60}
        return self.world.make.item(**(defaults | {"qty_on_hand": units} | values))  # type: ignore[no-any-return]

    def reserve_card(
        self, request_id: uuid.UUID, *boxes: tuple[int, uuid.UUID, int], key: str = "card-1"
    ) -> list[Any]:
        """The client taps [Reserve these] on a plan card: `(position, box, units)` per line."""
        items = self.items(request_id)
        tx = self.world.tx()
        requests.items_proposed(
            tx, request_id, [items[position - 1].id for position, _, _ in boxes]
        )
        made = orders.reserve(
            tx,
            client_id=self.client,
            lines=[
                ReserveLine(
                    box, units, expected_price_lbp=600_000, request_item_id=items[position - 1].id
                )
                for position, box, units in boxes
            ],
            pickup_day=tx.today,
            source=OrderSource.REQUEST,
            idempotency_key=key,
        )
        self.world.settle(tx)
        return made


@pytest.fixture
def case(world: World) -> Case:
    return Case(
        world,
        client=world.make.client(),
        concor=world.make.product(moph_name="CONCOR", public_price_lbp=1_000_000),
        aspirin=world.make.product(moph_name="ASPIRIN", public_price_lbp=1_000_000),
        pharmacy=world.make.pharmacy(lat=33.897, lon=35.484),
    )


def refusal(action: Any) -> ServiceError:
    with pytest.raises(ServiceError) as refused:
        action()
    return refused.value


def secured_matches_orders(world: World) -> None:
    """INV-18, for open requests: an item's secured units are its reserved or picked-up units."""
    broken = world.all(
        "SELECT ri.id FROM request_items ri "
        "JOIN sourcing_requests r ON r.id = ri.request_id AND r.state = 'OPEN' "
        "LEFT JOIN orders o ON o.request_item_id = ri.id AND o.state IN ('RESERVED', 'PICKED_UP') "
        "GROUP BY ri.id, ri.qty, ri.qty_secured, ri.state "
        "HAVING ri.qty_secured <> COALESCE(SUM(CASE WHEN o.state = 'RESERVED' THEN o.qty_locked "
        "                                         ELSE o.qty_picked_up END), 0) "
        "    OR (ri.state = 'SECURED') <> (ri.qty_secured >= ri.qty)"
    )
    assert broken == []


class TestStartingARequest:
    def test_a_tap_creates_the_request_its_items_and_its_thread(
        self, case: Case, world: World
    ) -> None:
        """R-RQ1, R-RQ8."""
        request_id = case.start()

        request = case.request(request_id)
        assert (request.state, request.outcome) == ("OPEN", None)
        assert re.fullmatch(r"Q-[2-9A-HJ-NP-Z]{6}", request.ref)
        assert request.ends_at == NOW + timedelta(hours=6)
        # The location is stored rounded to about 100 m (N-43).
        assert (str(request.loc_lat), str(request.loc_lon), request.loc_source) == (
            "33.896",
            "35.483",
            "shared",
        )
        assert [(i.position, i.qty, i.qty_secured, i.state) for i in case.items(request_id)] == [
            (1, 2, 0, "SEARCHING"),
            (2, 1, 0, "SEARCHING"),
        ]
        assert world.audit_actions(request_id) == ["request.create"]

    def test_the_agents_first_turn_is_asked_for_at_once(self, case: Case, world: World) -> None:
        """R-T8, R-RQ3: the first search runs within seconds."""
        request_id = case.start()

        conversation = world.one("SELECT * FROM conversations WHERE request_id = :r", r=request_id)
        assert (conversation.kind, conversation.pending_turn_at) == ("request", NOW)
        assert case.thread(request_id) == [("event", "request_submitted")]
        # The location lives beside the case state, never in it (INV-24).
        assert conversation.case_state == {}
        assert str(conversation.loc_lat) == "33.896"

    def test_the_same_tap_twice_starts_one_request(self, case: Case) -> None:
        assert case.start(key="tap") == case.start(key="tap")

    @pytest.mark.parametrize(
        ("what", "code"),
        [
            ("nothing", Code.VALIDATION_ERROR),
            ("six medicines", Code.VALIDATION_ERROR),
            ("one medicine twice", Code.VALIDATION_ERROR),
            ("four units", Code.VALIDATION_ERROR),
            ("a controlled medicine", Code.PRODUCT_NOT_ALLOWED),
        ],
    )
    def test_what_a_request_may_contain(
        self, case: Case, world: World, what: str, code: Code
    ) -> None:
        """1 to 5 medicines, each once, 1 to 3 units, never a controlled one."""
        lines: dict[str, list[RequestLine]] = {
            "nothing": [],
            "six medicines": [RequestLine(world.make.product()) for _ in range(6)],
            "one medicine twice": [RequestLine(case.concor), RequestLine(case.concor)],
            "four units": [RequestLine(case.concor, qty=4)],
            "a controlled medicine": [RequestLine(world.make.product(controlled=True))],
        }
        tx = world.tx()

        error = refusal(
            lambda: requests.create_request(
                tx,
                client_id=case.client,
                lines=lines[what],
                location=HAMRA,
                alternatives_ok=False,
                idempotency_key="k",
            )
        )

        assert error.code is code

    def test_requests_start_only_during_the_day(self, case: Case, world: World) -> None:
        """R-T3, FR-17: at 22:00, "come back tomorrow from 08:00"."""
        world.later(hours=12)

        error = refusal(case.start)

        assert error.code is Code.OUTSIDE_REQUEST_HOURS
        assert error.details["opens_at"] == NOW + timedelta(hours=22)

    def test_two_open_requests_at_most(self, case: Case, world: World) -> None:
        """R-RQ2."""
        case.start(RequestLine(case.concor), key="a")
        case.start(RequestLine(case.aspirin), key="b")

        third = refusal(lambda: case.start(RequestLine(world.make.product()), key="c"))

        assert third.code is Code.LIMIT_OPEN_REQUESTS

    def test_only_an_active_client_starts_one(self, case: Case, world: World) -> None:
        paused = world.make.client("PAUSED", paused_until=NOW + DAY)

        assert refusal(lambda: case.start(client_id=paused)).code is Code.CLIENT_PAUSED


class TestThePlanCard:
    """R-RQ6: the client taps [Reserve these]."""

    def test_reserving_every_unit_secures_the_items_and_closes_the_request(
        self, case: Case, world: World
    ) -> None:
        """R-RQ7, R-RQ9, INV-18."""
        request_id = case.start()
        concor, aspirin = case.stock(case.concor), case.stock(case.aspirin)

        made = case.reserve_card(request_id, (1, concor, 2), (2, aspirin, 1))

        assert [(i.state, i.qty_secured) for i in case.items(request_id)] == [
            ("SECURED", 2),
            ("SECURED", 1),
        ]
        request = case.request(request_id)
        assert (request.state, request.outcome, request.closed_at) == ("CLOSED", "FULFILLED", NOW)
        assert {o.source for o in made} == {"request"}
        assert len({o.group_id for o in made}) == 1
        assert world.notifications(case.client) == ["CN-15", "CN-3", "CN-3", "CN-17"]
        assert case.thread(request_id) == [
            ("event", "request_submitted"),
            ("card", "reserved"),
            ("card", "reserved"),
            ("card", "request_closed"),
        ]

    def test_a_card_with_only_some_items_leaves_the_others_being_searched(
        self, case: Case, world: World
    ) -> None:
        request_id = case.start()

        case.reserve_card(request_id, (2, case.stock(case.aspirin), 1))

        assert [i.state for i in case.items(request_id)] == ["SEARCHING", "SECURED"]
        assert case.request(request_id).state == "OPEN"
        secured_matches_orders(world)

    def test_part_of_a_quantity_keeps_the_item_searching_for_the_rest(
        self, case: Case, world: World
    ) -> None:
        """R-W4: "1 of 2 secured"."""
        request_id = case.start()

        case.reserve_card(request_id, (1, case.stock(case.concor, 1), 1))

        concor = case.items(request_id)[0]
        assert (concor.state, concor.qty_secured) == ("SEARCHING", 1)
        secured_matches_orders(world)

    def test_one_quantity_can_come_from_two_pharmacies(self, case: Case, world: World) -> None:
        """R-RQ5: Concor x2 = 1 at A + 1 at B."""
        request_id = case.start(RequestLine(case.concor, qty=2))
        other = world.make.pharmacy(lat=33.898, lon=35.485)

        case.reserve_card(request_id, (1, case.stock(case.concor, 1), 1), key="a")
        case.reserve_card(
            request_id, (1, case.stock(case.concor, 1, pharmacy_id=other), 1), key="b"
        )

        assert case.items(request_id)[0].state == "SECURED"
        assert case.request(request_id).outcome == "FULFILLED"

    def test_a_box_of_another_medicine_or_too_many_units_is_refused(
        self, case: Case, world: World
    ) -> None:
        request_id = case.start()
        wrong = case.stock(world.make.product())

        assert (
            refusal(lambda: case.reserve_card(request_id, (1, wrong, 1))).code
            is Code.VALIDATION_ERROR
        )
        assert (
            refusal(lambda: case.reserve_card(request_id, (2, case.stock(case.aspirin), 2))).code
            is Code.VALIDATION_ERROR
        )

    def test_another_brand_serves_an_item_only_if_the_client_agreed_to_other_brands(
        self, case: Case, world: World
    ) -> None:
        """G4. Since BLD-D17 the agent makes this card only when the client asks for the brand."""
        key = "bisoprolol=5mg | tablet | C07AB07"
        brand = world.make.product(equivalence_key=key)
        generic = world.make.product(equivalence_key=key)
        box = case.stock(generic)
        strict = case.start(RequestLine(brand), key="strict")
        open_to_it = case.start(RequestLine(brand), key="open", alternatives_ok=True)

        assert (
            refusal(lambda: case.reserve_card(strict, (1, box, 1), key="a")).code
            is Code.VALIDATION_ERROR
        )
        case.reserve_card(open_to_it, (1, box, 1), key="b")
        assert case.items(open_to_it)[0].state == "SECURED"

    def test_unticked_items_go_back_to_the_agent(self, case: Case, world: World) -> None:
        request_id = case.start()
        items = case.items(request_id)
        tx = world.tx()
        requests.items_proposed(tx, request_id, [i.id for i in items])

        requests.items_unticked(tx, case.client, request_id, [items[1].id])

        assert [i.state for i in case.items(request_id)] == ["PROPOSED", "SEARCHING"]
        assert case.thread(request_id)[-1] == ("event", "items_unticked")

    def test_a_card_that_fails_tells_the_agent_which_item(self, case: Case, world: World) -> None:
        request_id = case.start()
        items = case.items(request_id)
        tx = world.tx()
        requests.items_proposed(tx, request_id, [i.id for i in items])

        requests.group_item_failed(
            tx,
            case.client,
            request_id,
            [{"request_item_id": items[0].id, "code": "NOT_ENOUGH_STOCK"}],
        )

        assert [i.state for i in case.items(request_id)] == ["SEARCHING", "SEARCHING"]
        assert case.thread(request_id)[-1] == ("event", "group_item_failed")


class TestWaitingForStock:
    def waiting(self, case: Case, request_id: uuid.UUID, position: int = 1) -> uuid.UUID:
        tx = case.world.tx()
        claim = requests.open_claim(tx, case.items(request_id)[position - 1].id)
        case.world.settle(tx)
        return claim.id

    def test_the_agent_opens_a_claim_and_the_item_waits(self, case: Case, world: World) -> None:
        """R-W1: the claim takes the request's location, window and constraints."""
        request_id = case.start(
            RequestLine(case.concor, qty=2, days_of_use=7, max_price_lbp=700_000)
        )

        claim_id = self.waiting(case, request_id)

        claim = world.one("SELECT * FROM claims WHERE id = :c", c=claim_id)
        assert (claim.kind, claim.source, claim.state) == ("REQUEST_ITEM", "request", "ACTIVE")
        assert (claim.qty, claim.qty_missing, claim.days_of_use, claim.max_price_lbp) == (
            2,
            2,
            7,
            700_000,
        )
        assert claim.ends_at == case.request(request_id).ends_at
        assert claim.created_at == NOW
        assert case.items(request_id)[0].state == "WAITING"
        assert self.waiting(case, request_id) == claim_id

    def test_the_agent_can_start_waiting_after_20h_while_the_request_is_open(
        self, case: Case, world: World
    ) -> None:
        """R-W1, BLD-D6: a request started at 19:00 searches until 01:00. At 21:00 the
        agent may still start waiting for one of its medicines; a new watch may not start.
        """
        world.later(hours=9)
        request_id = case.start(RequestLine(case.concor))
        world.later(hours=2)

        claim_id = self.waiting(case, request_id)

        claim = world.one("SELECT * FROM claims WHERE id = :c", c=claim_id)
        assert claim.created_at == NOW + timedelta(hours=11)
        assert claim.ends_at == case.request(request_id).ends_at == NOW + timedelta(hours=15)
        assert case.items(request_id)[0].state == "WAITING"
        watch = refusal(
            lambda: claims.create_watch(
                world.tx(),
                client_id=case.client,
                product_id=case.aspirin,
                location=HAMRA,
                source=ClaimSource.SEARCH,
            )
        )
        assert watch.code is Code.OUTSIDE_REQUEST_HOURS

    def test_new_stock_is_offered_in_the_thread_and_accepting_it_secures_the_item(
        self, case: Case, world: World
    ) -> None:
        request_id = case.start(RequestLine(case.concor))
        claim = self.waiting(case, request_id)
        case.stock(case.concor)
        world.clock_tasks().matching_sweep()
        offer = world.one("SELECT * FROM orders WHERE claim_id = :c", c=claim)

        tx = world.tx()
        orders.accept_offer(tx, case.client, offer.id, TODAY)
        world.settle(tx)

        assert offer.source == "request"
        assert case.thread(request_id)[1] == ("card", "offer")
        assert case.items(request_id)[0].state == "SECURED"
        assert world.one("SELECT state FROM claims WHERE id = :c", c=claim).state == "FULFILLED"
        assert case.request(request_id).outcome == "FULFILLED"

    def test_a_plan_card_for_a_waiting_item_covers_its_claim_and_withdraws_its_offer(
        self, case: Case, world: World
    ) -> None:
        """R-RQ7, R-W3."""
        request_id = case.start(RequestLine(case.concor))
        claim = self.waiting(case, request_id)
        case.stock(case.concor, 1)
        world.clock_tasks().matching_sweep()
        other = world.make.pharmacy(lat=33.898, lon=35.485)

        case.reserve_card(request_id, (1, case.stock(case.concor, 1, pharmacy_id=other), 1))

        states = world.all("SELECT state FROM orders WHERE claim_id = :c", c=claim)
        assert [s.state for s in states] == ["OFFER_WITHDRAWN"]
        assert world.one("SELECT state FROM claims WHERE id = :c", c=claim).state == "FULFILLED"

    def test_not_available_reopens_the_item_and_wakes_the_agent(
        self, case: Case, world: World
    ) -> None:
        """O3, R-RQ3, while another item keeps the request open."""
        request_id = case.start()
        self.waiting(case, request_id, position=2)
        (order,) = case.reserve_card(request_id, (1, case.stock(case.concor), 2))

        counter.mark_not_available(world.tx(), case.pharmacy, order.id, 1)

        concor = case.items(request_id)[0]
        assert (concor.state, concor.qty_secured) == ("SEARCHING", 1)
        assert case.thread(request_id)[-2:] == [
            ("card", "not_available"),
            ("event", "not_available"),
        ]
        secured_matches_orders(world)

    def test_once_a_request_is_closed_nothing_reopens_it(self, case: Case, world: World) -> None:
        """R-RQ9: later events are recorded on the orders only."""
        request_id = case.start(RequestLine(case.concor))
        (order,) = case.reserve_card(request_id, (1, case.stock(case.concor), 1))

        counter.mark_not_available(world.tx(), case.pharmacy, order.id)

        assert case.request(request_id).outcome == "FULFILLED"
        assert case.items(request_id)[0].state == "SECURED"
        assert case.thread(request_id)[-1] == ("card", "not_available")


class TestTheWindow:
    def test_one_hour_before_the_end_the_agent_gets_a_last_chance_once(
        self, case: Case, world: World
    ) -> None:
        """N-24, R-RQ3."""
        request_id = case.start()
        tasks = world.clock_tasks()

        world.later(hours=4, minutes=59)
        too_early = tasks.run_window_checks()
        world.later(minutes=1)
        checked, again = tasks.run_window_checks(), tasks.run_window_checks()

        assert (too_early, checked, again) == (0, 1, 0)
        assert case.thread(request_id)[-1] == ("event", "window_check")
        assert world.notifications(case.client) == ["CN-16"]
        assert case.request(request_id).window_checked_at == NOW + timedelta(hours=5)

    def test_when_the_window_ends_missing_items_become_unavailable(
        self, case: Case, world: World
    ) -> None:
        """R-RQ9: one unit secured out of three is PARTIAL."""
        request_id = case.start()
        TestWaitingForStock().waiting(case, request_id, position=2)
        case.reserve_card(request_id, (1, case.stock(case.concor, 1), 1))
        world.later(hours=6)

        assert world.clock_tasks().end_windows() == 1

        assert [i.state for i in case.items(request_id)] == ["UNAVAILABLE", "UNAVAILABLE"]
        request = case.request(request_id)
        assert (request.state, request.outcome) == ("CLOSED", "PARTIAL")
        claim = world.one("SELECT c.state FROM claims c WHERE c.client_id = :c", c=case.client)
        assert claim.state == "EXPIRED"
        assert world.notifications(case.client)[-1] == "CN-17"

    def test_nothing_found_is_unfulfilled(self, case: Case, world: World) -> None:
        request_id = case.start()
        world.later(hours=6)

        world.clock_tasks().end_windows()

        assert case.request(request_id).outcome == "UNFULFILLED"

    def test_an_offer_made_before_the_end_keeps_the_request_open_for_it(
        self, case: Case, world: World
    ) -> None:
        """FR-16."""
        request_id = case.start(RequestLine(case.concor))
        claim = TestWaitingForStock().waiting(case, request_id)
        world.later(hours=5, minutes=30)
        case.stock(case.concor)
        tasks = world.clock_tasks()
        tasks.matching_sweep()
        world.later(minutes=30)

        still_open = tasks.end_windows()
        offer = world.one("SELECT * FROM orders WHERE claim_id = :c", c=claim)
        tx = world.tx()
        orders.accept_offer(tx, case.client, offer.id, tx.today)
        world.settle(tx)

        assert still_open == 0
        assert case.request(request_id).outcome == "FULFILLED"

    def test_an_offer_nobody_takes_lets_the_request_close_when_it_expires(
        self, case: Case, world: World
    ) -> None:
        request_id = case.start(RequestLine(case.concor))
        TestWaitingForStock().waiting(case, request_id)
        world.later(hours=5, minutes=30)
        case.stock(case.concor)
        tasks = world.clock_tasks()
        tasks.matching_sweep()
        world.later(hours=2)

        tasks.expire_offers()
        tasks.end_windows()

        assert case.request(request_id).outcome == "UNFULFILLED"


class TestGivingUp:
    def test_the_client_cancels_the_request_and_keeps_what_is_reserved(
        self, case: Case, world: World
    ) -> None:
        request_id = case.start()
        claim = TestWaitingForStock().waiting(case, request_id, position=2)
        (order,) = case.reserve_card(request_id, (1, case.stock(case.concor), 2))

        tx = world.tx()
        requests.cancel_request(tx, case.client, request_id)
        world.settle(tx)

        assert [i.state for i in case.items(request_id)] == ["SECURED", "CANCELLED"]
        request = case.request(request_id)
        assert (request.state, request.outcome) == ("CLOSED", "CANCELLED")
        assert world.one("SELECT state FROM claims WHERE id = :c", c=claim).state == "CANCELLED"
        assert world.one("SELECT state FROM orders WHERE id = :o", o=order.id).state == "RESERVED"
        assert (
            refusal(lambda: requests.cancel_request(world.tx(), case.client, request_id)).code
            is Code.REQUEST_CLOSED
        )

    def test_removing_an_item_can_complete_the_request(self, case: Case, world: World) -> None:
        request_id = case.start()
        case.reserve_card(request_id, (1, case.stock(case.concor), 2))

        tx = world.tx()
        requests.remove_item(tx, case.client, case.items(request_id)[1].id)
        world.settle(tx)

        assert [i.state for i in case.items(request_id)] == ["SECURED", "CANCELLED"]
        assert case.request(request_id).outcome == "PARTIAL"

    def test_cancelling_a_reservation_ends_that_item(self, case: Case, world: World) -> None:
        """O5: the item is cancelled while the request is open."""
        request_id = case.start()
        (order,) = case.reserve_card(request_id, (1, case.stock(case.concor), 2))

        tx = world.tx()
        orders.cancel_by_client(tx, case.client, order.id)
        world.settle(tx)

        concor = case.items(request_id)[0]
        assert (concor.state, concor.qty_secured) == ("CANCELLED", 0)
        assert case.request(request_id).state == "OPEN"
        secured_matches_orders(world)

    def test_a_no_show_inside_the_window_ends_that_item_too(self, case: Case, world: World) -> None:
        """O4, as built: DawaLink doesn't search again for a medicine the client didn't collect."""
        request_id = case.start()
        with world.as_owner():
            world.connection.exec_driver_sql(
                "UPDATE pharmacy_hours SET close_minute = 780 WHERE pharmacy_id = %s",
                (case.pharmacy,),
            )  # this pharmacy closes at 13:00
        case.reserve_card(request_id, (1, case.stock(case.concor), 2))
        world.later(hours=3)

        world.clock_tasks().expire_reservations()

        concor = case.items(request_id)[0]
        assert (concor.state, concor.qty_secured) == ("CANCELLED", 0)
        assert case.request(request_id).state == "OPEN"
        assert case.thread(request_id)[-1] == ("card", "expired")
        secured_matches_orders(world)

    def test_someone_else_cannot_touch_the_request(self, case: Case, world: World) -> None:
        request_id = case.start()

        error = refusal(
            lambda: requests.cancel_request(world.tx(), world.make.client(), request_id)
        )

        assert error.code is Code.NOT_FOUND


class TestChangingConstraints:
    def test_the_budget_follows_into_the_waiting_claim_and_other_brands_never_do(
        self, case: Case, world: World
    ) -> None:
        request_id = case.start(RequestLine(case.concor, max_price_lbp=500_000))
        claim = TestWaitingForStock().waiting(case, request_id)
        item = case.items(request_id)[0]
        case.stock(case.concor)  # 600,000: above the budget
        tasks = world.clock_tasks()
        before = tasks.matching_sweep()

        tx = world.tx()
        requests.change_constraints(
            tx, case.client, request_id, alternatives_ok=True, max_prices={item.id: 700_000}
        )
        world.settle(tx)

        row = world.one("SELECT * FROM claims WHERE id = :c", c=claim)
        assert before == 0
        assert (row.max_price_lbp, row.state) == (700_000, "OFFER_PENDING")
        assert case.request(request_id).alternatives_ok is True

    def test_agreeing_to_other_brands_never_makes_a_request_wait_for_one(
        self, case: Case, world: World
    ) -> None:
        """R-C10 (BLD-D17): the request shows other brands; it holds only the medicine itself."""
        key = "bisoprolol=5mg | tablet | C07AB07"
        with world.as_owner():
            world.connection.exec_driver_sql(
                "UPDATE products SET equivalence_key = %s WHERE id = %s", (key, case.concor)
            )
        generic = world.make.product(equivalence_key=key)
        request_id = case.start(RequestLine(case.concor), alternatives_ok=True)
        claim = TestWaitingForStock().waiting(case, request_id)

        case.stock(generic)
        made = world.clock_tasks().matching_sweep()

        assert made == 0
        assert world.one("SELECT state FROM claims WHERE id = :c", c=claim).state == "ACTIVE"
