"""Watches, matching and offers (docs/04 SM-7, R-PRI, R-W, O7, O9 to O11; ADR-003)."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import ClaimSource
from dawalink.services import claims, counter, matching, orders
from dawalink.services.errors import Code, ServiceError
from dawalink.services.travel import shared_location
from tests.db.factories import NOW, TODAY
from tests.services.conftest import World

DAY = timedelta(days=1)
HAMRA = shared_location(33.896, 35.483)
KEY = "paracetamol=500mg | tablet | N02BE01"


@dataclass
class Market:
    """One medicine (with another brand of it), and a pharmacy next to the clients."""

    world: World
    product: uuid.UUID
    other_brand: uuid.UUID
    pharmacy: uuid.UUID

    def watch(self, client: uuid.UUID | None = None, **values: Any) -> uuid.UUID:
        """A client starts watching; matching runs as it would after the commit."""
        tx = self.world.tx()
        asked: dict[str, Any] = {
            "client_id": client or self.world.make.client(),
            "product_id": self.product,
            "location": HAMRA,
            "source": ClaimSource.SEARCH,
        }
        claim = claims.create_watch(tx, **(asked | values))
        self.world.settle(tx)
        return claim.id

    def stock(self, units: int = 1, **values: Any) -> uuid.UUID:
        """A box appears on a shelf. The clock check's sweep will find it."""
        defaults = {"pharmacy_id": self.pharmacy, "product_id": self.product, "days_left": 60}
        return self.world.make.item(**(defaults | {"qty_on_hand": units} | values))  # type: ignore[no-any-return]

    def sweep(self) -> int:
        return self.world.clock_tasks().matching_sweep()

    def claim(self, claim_id: uuid.UUID) -> Any:
        return self.world.one("SELECT * FROM claims WHERE id = :id", id=claim_id)

    def offers(self, claim_id: uuid.UUID, state: str = "OFFERED") -> list[Any]:
        return self.world.all(
            "SELECT * FROM orders WHERE claim_id = :c AND state = :s ORDER BY created_at, id",
            c=claim_id,
            s=state,
        )

    def accept(self, claim_id: uuid.UUID, pickup_day: Any = TODAY) -> Any:
        (offer,) = self.offers(claim_id)
        tx = self.world.tx()
        orders.accept_offer(tx, offer.client_id, offer.id, pickup_day)
        self.world.settle(tx)
        return self.world.one("SELECT * FROM orders WHERE id = :id", id=offer.id)


@pytest.fixture
def market(world: World) -> Market:
    return Market(
        world,
        product=world.make.product(equivalence_key=KEY, public_price_lbp=1_000_000),
        other_brand=world.make.product(equivalence_key=KEY, public_price_lbp=1_000_000),
        pharmacy=world.make.pharmacy(lat=33.897, lon=35.484),
    )


def refusal(action: Any) -> ServiceError:
    with pytest.raises(ServiceError) as refused:
        action()
    return refused.value


class TestCreatingAWatch:
    def test_a_watch_waits_for_six_hours_from_the_app_clocks_time(
        self, market: Market, world: World
    ) -> None:
        """R-W1, N-11."""
        client = world.make.client()

        claim = market.claim(market.watch(client, qty=2, days_of_use=7))

        assert (claim.kind, claim.state, claim.source) == ("WATCH", "ACTIVE", "search")
        assert (claim.qty, claim.qty_missing, claim.days_of_use) == (2, 2, 7)
        assert claim.created_at == NOW
        assert claim.ends_at == NOW + timedelta(hours=6)
        assert claim.equivalence_key == KEY
        # The location is stored rounded (N-43).
        assert (str(claim.loc_lat), str(claim.loc_lon)) == ("33.896", "35.483")
        assert world.audit_actions(claim.id) == ["claim.create"]

    def test_stock_that_is_already_visible_is_offered_at_once(self, market: Market) -> None:
        """R-PRI1: matching runs when a claim is created."""
        market.stock()

        claim = market.watch()

        assert len(market.offers(claim)) == 1
        assert market.claim(claim).state == "OFFER_PENDING"

    def test_watches_start_only_during_the_day(self, market: Market, world: World) -> None:
        """R-T3, INV-22: 08:00 to 20:00 in Beirut."""
        world.later(hours=10)  # 20:00

        error = refusal(market.watch)

        assert error.code is Code.OUTSIDE_REQUEST_HOURS
        assert error.details["opens_at"] == NOW + timedelta(hours=22)  # tomorrow 08:00

    def test_one_watch_per_medicine_and_five_at_most(self, market: Market, world: World) -> None:
        """R-W2."""
        client = world.make.client()
        first = market.watch(client)

        again = refusal(lambda: market.watch(client))
        for _ in range(4):
            market.watch(client, product_id=world.make.product())
        sixth = refusal(lambda: market.watch(client, product_id=world.make.product()))

        assert (again.code, again.details) == (Code.WATCH_EXISTS, {"watch_id": first})
        assert sixth.code is Code.LIMIT_WATCHES

    def test_guards(self, market: Market, world: World) -> None:
        controlled = world.make.product(controlled=True)
        paused = world.make.client("PAUSED", paused_until=NOW + DAY)

        assert refusal(lambda: market.watch(product_id=controlled)).code is Code.PRODUCT_NOT_ALLOWED
        assert refusal(lambda: market.watch(paused)).code is Code.CLIENT_PAUSED
        assert refusal(lambda: market.watch(qty=4)).code is Code.VALIDATION_ERROR


class TestFirstComeFirstServed:
    """R-PRI, INV-17, ADR-003."""

    def test_the_claim_that_waited_longest_gets_the_only_box(
        self, market: Market, world: World
    ) -> None:
        first = market.watch()
        world.later(minutes=5)
        second = market.watch()
        market.stock(1)

        assert market.sweep() == 1

        (offer,) = market.offers(first)
        assert market.offers(second) == []
        assert (offer.state, offer.source, offer.qty_locked) == ("OFFERED", "watch", 1)
        assert offer.offer_expires_at == NOW + timedelta(minutes=5, hours=2)
        assert offer.price_snapshot_lbp == 600_000
        assert market.claim(first).state == "OFFER_PENDING"
        assert market.claim(second).state == "ACTIVE"
        reason = world.one(
            "SELECT reason, actor_type FROM audit_events WHERE entity_id = :o", o=offer.id
        )
        assert reason.actor_type == "SYSTEM"
        assert reason.reason == "first come, first served: waiting since 10:00"

    def test_each_claim_gets_its_missing_units_while_stock_remains(
        self, market: Market, world: World
    ) -> None:
        first = market.watch(qty=2)
        world.later(minutes=1)
        second = market.watch(qty=2)
        market.stock(3)

        market.sweep()

        assert [o.qty_locked for o in market.offers(first)] == [2]
        assert [o.qty_locked for o in market.offers(second)] == [1]

    def test_a_tie_on_time_is_broken_by_the_claims_id(self, market: Market, world: World) -> None:
        one, other = market.watch(), market.watch()
        market.stock(1)

        market.sweep()

        winner = min(one, other, key=str)
        assert len(market.offers(winner)) == 1

    def test_running_matching_again_changes_nothing(self, market: Market, world: World) -> None:
        """INV-20: a claim holds at most one matching offer at a time."""
        claim = market.watch(qty=2)
        market.stock(1)
        market.stock(1)

        assert (market.sweep(), market.sweep()) == (1, 0)
        assert len(market.offers(claim)) == 1

    def test_a_paused_client_is_skipped_and_the_next_one_gets_it(
        self, market: Market, world: World
    ) -> None:
        """R-PRI3, FR-14."""
        early = world.make.client()
        first = market.watch(early)
        world.later(minutes=1)
        second = market.watch()
        with world.as_owner():
            world.connection.exec_driver_sql(
                "UPDATE client_profiles SET status = 'PAUSED', paused_until = now() "
                "WHERE user_id = %s",
                (early,),
            )
        market.stock(1)

        market.sweep()

        assert market.offers(first) == []
        assert len(market.offers(second)) == 1

    @pytest.mark.rows_by_hand
    def test_a_client_at_the_limit_is_skipped(self, market: Market, world: World) -> None:
        full = world.make.client()
        for number in range(5):
            world.make.order(client_id=full, idempotency_key=f"k{number}")
        first = market.watch(full)
        world.later(minutes=1)
        second = market.watch()
        market.stock(1)

        market.sweep()

        assert market.offers(first) == []
        assert len(market.offers(second)) == 1

    def test_no_table_or_argument_lets_anyone_change_the_order(self) -> None:
        """R-PRI4: the functions that decide take no priority, urgency or rank."""
        import inspect

        for function in (matching.run_for_group, claims.create_watch, orders.create_offer):
            names = set(inspect.signature(function).parameters)
            assert not names & {"priority", "urgent", "urgency", "rank", "emergency", "position"}


class TestWhichBoxIsOffered:
    def test_only_a_pharmacy_within_reach(self, market: Market, world: World) -> None:
        """R-RT3, N-23: Tripoli is far more than 30 minutes from Hamra."""
        claim = market.watch()
        market.stock(1, pharmacy_id=world.make.pharmacy(lat=34.437, lon=35.850))

        market.sweep()

        assert market.offers(claim) == []

    def test_only_a_box_that_lasts_the_days_of_use(self, market: Market) -> None:
        """R-F1, INV-25."""
        claim = market.watch(days_of_use=12)
        market.stock(1, days_left=5)
        long_enough = market.stock(1, days_left=40)

        market.sweep()

        assert [o.inventory_item_id for o in market.offers(claim)] == [long_enough]

    def test_only_within_the_budget(self, market: Market) -> None:
        claim = market.watch(max_price_lbp=500_000)
        market.stock(1, days_left=60)  # 600,000
        cheap = market.stock(1, days_left=10)  # 400,000

        market.sweep()

        assert [o.inventory_item_id for o in market.offers(claim)] == [cheap]

    def test_another_brand_only_if_the_client_allowed_alternatives(self, market: Market) -> None:
        """G4: alternatives need the client's consent."""
        strict = market.watch()
        market.stock(1, product_id=market.other_brand)

        market.sweep()
        open_to_it = market.watch(include_equivalents=True)

        assert market.offers(strict) == []
        assert len(market.offers(open_to_it)) == 1

    def test_private_stock_is_never_offered_by_matching(self, market: Market) -> None:
        """INV-8: early-release stock is reached only by asking the pharmacy."""
        claim = market.watch()
        market.stock(1, days_left=200)

        market.sweep()

        assert market.offers(claim) == []


class TestAcceptingAnOffer:
    def test_it_becomes_a_reservation_and_the_watch_is_fulfilled(
        self, market: Market, world: World
    ) -> None:
        """O9."""
        client = world.make.client()
        market.stock(1)
        claim = market.watch(client, days_of_use=7)

        order = market.accept(claim, TODAY + DAY)

        assert (order.state, order.pickup_day, order.days_of_use) == ("RESERVED", TODAY + DAY, 7)
        assert order.deadline is not None
        assert order.reserved_at == NOW
        watch = market.claim(claim)
        assert (watch.state, watch.qty_missing) == ("FULFILLED", 0)
        assert world.notifications(client) == ["CN-10", "CN-3"]
        assert world.audit_actions(order.id) == ["order.offer", "order.accept_offer"]

    def test_a_partial_offer_leaves_the_watch_waiting_for_the_rest(self, market: Market) -> None:
        """R-W4."""
        market.stock(1)
        claim = market.watch(qty=2)

        market.accept(claim)
        market.stock(1)
        market.sweep()

        watch = market.claim(claim)
        assert (watch.state, watch.qty_missing) == ("OFFER_PENDING", 1)
        assert len(market.offers(claim)) == 1

    def test_an_expired_offer_cannot_be_accepted(self, market: Market, world: World) -> None:
        """FR-7."""
        market.stock(1)
        claim = market.watch()
        world.later(hours=2)

        error = refusal(lambda: market.accept(claim))

        assert error.code is Code.OFFER_NOT_OPEN
        assert error.details == {"reason": "OFFER_EXPIRED"}

    def test_the_pickup_day_and_the_fit_are_checked_at_the_tap(self, market: Market) -> None:
        """R-F3, R-F5: 7 days left, 7 days of use, a pharmacy that holds one day."""
        market.stock(1, days_left=7)
        claim = market.watch(days_of_use=7)

        too_far = refusal(lambda: market.accept(claim, TODAY + 2 * DAY))

        assert too_far.code is Code.PICKUP_DAY_INVALID
        assert market.accept(claim, TODAY + DAY).state == "RESERVED"

    def test_someone_elses_offer_does_not_exist(self, market: Market, world: World) -> None:
        market.stock(1)
        (offer,) = market.offers(market.watch())

        error = refusal(
            lambda: orders.accept_offer(world.tx(), world.make.client(), offer.id, TODAY)
        )

        assert error.code is Code.NOT_FOUND

    @pytest.mark.rows_by_hand
    def test_an_offer_counts_towards_the_limits_when_it_is_accepted(
        self, market: Market, world: World
    ) -> None:
        """R-L2: 3 units of the same medicine at most."""
        client = world.make.client()
        market.stock(1)
        claim = market.watch(client)
        world.make.order(client_id=client, equivalence_key=KEY, qty_requested=3, qty_locked=3)

        assert refusal(lambda: market.accept(claim)).code is Code.LIMIT_GROUP_UNITS


class TestAnOfferThatEnds:
    def test_declining_passes_the_box_to_the_next_claim(self, market: Market, world: World) -> None:
        """O10."""
        client = world.make.client()
        first = market.watch(client)
        world.later(minutes=1)
        second = market.watch()
        box = market.stock(1)
        market.sweep()
        (offer,) = market.offers(first)

        tx = world.tx()
        orders.end_offer(tx, offer.id, declined_by=client)
        world.settle(tx)

        assert market.offers(first, "OFFER_DECLINED")[0].close_reason == "declined"
        assert market.claim(first).state == "ACTIVE"
        assert [o.inventory_item_id for o in market.offers(second)] == [box]

    def test_a_declined_box_is_not_offered_to_the_same_claim_for_a_day(
        self, market: Market, world: World
    ) -> None:
        client = world.make.client()
        market.stock(1)
        claim = market.watch(client)
        (offer,) = market.offers(claim)
        tx = world.tx()
        orders.end_offer(tx, offer.id, declined_by=client)
        world.settle(tx)

        assert market.sweep() == 0
        assert market.offers(claim) == []

    def test_after_two_hours_the_clock_check_expires_it(self, market: Market, world: World) -> None:
        first = market.watch()
        world.later(minutes=1)
        second = market.watch()
        market.stock(1)
        market.sweep()
        world.later(hours=2)

        assert world.clock_tasks().expire_offers() == 1
        market.sweep()

        assert market.offers(first, "OFFER_EXPIRED")[0].close_reason == "expired"
        assert len(market.offers(second)) == 1
        stock = world.one(
            "SELECT qty_reserved FROM inventory_items WHERE pharmacy_id = :p", p=market.pharmacy
        )
        assert stock.qty_reserved == 1

    def test_cancelling_a_watch_withdraws_its_offer(self, market: Market, world: World) -> None:
        """O11."""
        client = world.make.client()
        market.stock(1)
        claim = market.watch(client)
        world.later(minutes=1)
        waiting = market.watch()

        tx = world.tx()
        claims.cancel_watch(tx, client, claim)
        world.settle(tx)

        assert market.claim(claim).state == "CANCELLED"
        assert market.offers(claim, "OFFER_WITHDRAWN")[0].close_reason == "withdrawn"
        assert len(market.offers(waiting)) == 1


class TestTheEndOfAWatch:
    def test_a_watch_that_found_nothing_ends_after_six_hours(
        self, market: Market, world: World
    ) -> None:
        """R-W5."""
        client = world.make.client()
        claim = market.watch(client)
        tasks = world.clock_tasks()

        world.later(hours=5, minutes=59)
        too_early = tasks.expire_watches()
        world.later(minutes=1)
        ended = tasks.expire_watches()

        assert (too_early, ended) == (0, 1)
        assert market.claim(claim).state == "EXPIRED"
        assert world.notifications(client) == ["CN-11"]

    def test_an_offer_made_before_the_end_stays_valid_for_its_two_hours(
        self, market: Market, world: World
    ) -> None:
        """R-RQ9, FR-16."""
        claim = market.watch()
        world.later(hours=5)
        market.stock(1)
        market.sweep()
        world.later(hours=1, minutes=30)

        assert world.clock_tasks().expire_watches() == 0
        assert market.accept(claim, world.tx().today).state == "RESERVED"

    def test_a_watch_opens_again_when_its_reservation_is_marked_not_available(
        self, market: Market, world: World
    ) -> None:
        """SM-7: FULFILLED back to ACTIVE, while the window is open."""
        market.stock(1)
        claim = market.watch()
        order = market.accept(claim)

        counter.mark_not_available(world.tx(), market.pharmacy, order.id)

        watch = market.claim(claim)
        assert (watch.state, watch.qty_missing, watch.closed_at) == ("ACTIVE", 1, None)


class TestWhereOffersAreAnnounced:
    def test_a_watch_from_the_search_page_never_reaches_the_chat(
        self, market: Market, world: World
    ) -> None:
        """R-AG5."""
        client = world.make.client()
        chat = world.make.conversation(client_id=client)
        market.stock(1)

        market.watch(client, source=ClaimSource.SEARCH)

        assert world.all("SELECT 1 FROM chat_messages WHERE conversation_id = :c", c=chat) == []
        assert world.notifications(client) == ["CN-10"]

    def test_the_agents_watch_posts_the_offer_card_in_the_chat(
        self, market: Market, world: World
    ) -> None:
        client = world.make.client()
        chat = world.make.conversation(client_id=client)
        market.stock(1)

        market.watch(client, source=ClaimSource.ASSISTANT, actor=Actor.AGENT)

        message = world.one("SELECT * FROM chat_messages WHERE conversation_id = :c", c=chat)
        assert (message.kind, message.cards[0]["template"]) == ("card", "offer")
        pending = world.one("SELECT pending_turn_at FROM conversations WHERE id = :c", c=chat)
        assert pending.pending_turn_at is None
