"""Early release: asking pharmacies to release private stock (docs/04 SM-6, R-E, O8)."""

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest

from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import ClaimSource
from dawalink.services import claims, early_release, orders
from dawalink.services.early_release import Asked
from dawalink.services.errors import Code, ServiceError
from dawalink.services.travel import shared_location
from tests.db.factories import NOW, TODAY
from tests.services.conftest import World

HAMRA = shared_location(33.896, 35.483)
KEY = "paracetamol=500mg | tablet | N02BE01"
EVERY_DAY_ALL_DAY = {weekday: [("00:00", "24:00")] for weekday in range(7)}


@dataclass
class Town:
    """A client watching a medicine that no pharmacy lists, but some hold privately."""

    world: World
    client: uuid.UUID
    product: uuid.UUID
    claim: uuid.UUID
    chat: uuid.UUID
    owners: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)

    def pharmacy_holding(
        self, *, metres_away: int = 100, days_left: int = 200, **values: Any
    ) -> uuid.UUID:
        """A pharmacy with one private box of the medicine, some way north of the client."""
        owner = self.world.make.user("pharmacist")
        pharmacy = self.world.make.pharmacy(
            owner_user_id=owner, lat=33.896 + metres_away / 111_000, lon=35.483, **values
        )
        self.world.make.item(
            pharmacy_id=pharmacy, product_id=self.product, days_left=days_left, qty_on_hand=4
        )
        self.owners[pharmacy] = owner
        return pharmacy  # type: ignore[no-any-return]

    def ask(self, key: str = "turn-1") -> Asked:
        tx = self.world.tx()
        asked = early_release.request_early_release(tx, claim_id=self.claim, idempotency_key=key)
        self.world.settle(tx)
        return asked

    def asks(self) -> dict[uuid.UUID, Any]:
        rows = self.world.all(
            "SELECT a.* FROM early_release_asks a JOIN early_release_requests r "
            "ON r.id = a.er_request_id WHERE r.claim_id = :c",
            c=self.claim,
        )
        return {row.pharmacy_id: row for row in rows}

    def request(self) -> Any:
        return self.world.one(
            "SELECT * FROM early_release_requests WHERE claim_id = :c "
            "ORDER BY created_at DESC LIMIT 1",
            c=self.claim,
        )

    def accept(self, pharmacy: uuid.UUID, qty: int = 1, price_lbp: int = 750_000) -> Any:
        tx = self.world.tx()
        ask = early_release.accept_ask(
            tx, pharmacy, self.asks()[pharmacy].id, qty=qty, price_lbp=price_lbp
        )
        self.world.settle(tx)
        return ask

    def decline(self, pharmacy: uuid.UUID) -> None:
        tx = self.world.tx()
        early_release.decline_ask(tx, pharmacy, self.asks()[pharmacy].id, "keeping_it")
        self.world.settle(tx)

    def offers(self, state: str = "OFFERED") -> list[Any]:
        return self.world.all(
            "SELECT * FROM orders WHERE claim_id = :c AND state = :s", c=self.claim, s=state
        )

    def claim_row(self) -> Any:
        return self.world.one("SELECT * FROM claims WHERE id = :c", c=self.claim)


@pytest.fixture
def town(world: World) -> Town:
    client = world.make.client()
    product = world.make.product(equivalence_key=KEY, public_price_lbp=1_000_000)
    chat = world.make.conversation(client_id=client)
    tx = world.tx()
    claim = claims.create_watch(
        tx,
        client_id=client,
        product_id=product,
        location=HAMRA,
        source=ClaimSource.ASSISTANT,
        actor=Actor.AGENT,
        qty=2,
    )
    world.settle(tx)
    return Town(world, client, product, claim.id, chat)


def refusal(action: Any) -> ServiceError:
    with pytest.raises(ServiceError) as refused:
        action()
    return refused.value


class TestAsking:
    def test_the_three_nearest_open_pharmacies_are_asked_at_once(
        self, town: Town, world: World
    ) -> None:
        """R-E2, R-E4, N-13."""
        nearest = [town.pharmacy_holding(metres_away=m) for m in (300, 600, 900)]
        far = town.pharmacy_holding(metres_away=1200)

        asked = town.ask()

        assert asked.pharmacies_asked == 3
        assert set(town.asks()) == set(nearest)
        assert far not in town.asks()
        ask = town.asks()[nearest[0]]
        assert (ask.state, ask.respond_by) == ("ASKED", NOW + timedelta(hours=2))
        request = town.request()
        assert (request.state, request.qty) == ("OPEN", 2)
        for pharmacy in nearest:
            assert world.notifications(town.owners[pharmacy]) == ["PN-7"]

    def test_the_client_and_the_agent_only_learn_how_many_were_asked(
        self, town: Town, world: World
    ) -> None:
        """R-E8, INV-8: not which pharmacies, and nothing reaches the chat."""
        town.pharmacy_holding()

        asked = town.ask()

        assert set(vars(asked)) == {"request_id", "pharmacies_asked"}
        assert (
            world.all("SELECT 1 FROM chat_messages WHERE conversation_id = :c", c=town.chat) == []
        )
        assert world.notifications(town.client) == []

    def test_a_pharmacy_never_learns_who_the_client_is(self, town: Town, world: World) -> None:
        """INV-9."""
        pharmacy = town.pharmacy_holding()
        town.ask()

        note = world.one(
            "SELECT payload FROM notifications WHERE user_id = :u", u=town.owners[pharmacy]
        )

        assert set(note.payload) == {
            "ask_id",
            "product",
            "units",
            "suggested_price_lbp",
            "respond_by",
        }
        assert note.payload["suggested_price_lbp"] == 750_000  # the public price minus 25% (R-PR3)
        assert str(town.client) not in str(note.payload)

    def test_only_private_boxes_in_the_early_release_zone_are_asked_about(self, town: Town) -> None:
        """N-3: 181 to 270 days left. A visible box is matched; a later one stays private."""
        town.pharmacy_holding(days_left=180)
        town.pharmacy_holding(days_left=271)
        in_zone = [town.pharmacy_holding(days_left=181), town.pharmacy_holding(days_left=270)]

        town.ask()

        assert set(town.asks()) == set(in_zone)

    def test_closed_far_or_unapproved_pharmacies_are_not_asked(
        self, town: Town, world: World
    ) -> None:
        town.pharmacy_holding(hours={0: [("08:00", "09:00")]})  # closed now (Tuesday 10:00)
        town.pharmacy_holding(metres_away=60_000)  # far beyond 30 minutes by car
        town.pharmacy_holding(status="PENDING")

        assert town.ask() == Asked(None, 0)
        assert world.all("SELECT 1 FROM early_release_requests") == []

    @pytest.mark.parametrize(("days_ago", "asked"), [(6, 0), (8, 1)])
    def test_a_pharmacy_that_declined_this_medicine_is_left_alone_for_a_week(
        self, town: Town, world: World, days_ago: int, asked: int
    ) -> None:
        """R-E3."""
        pharmacy = town.pharmacy_holding()
        world.make.early_release_ask(
            pharmacy_id=pharmacy,
            product_id=town.product,
            state="DECLINED",
            answered_at=NOW - timedelta(days=days_ago),
            created_at=NOW - timedelta(days=days_ago),
        )

        assert town.ask().pharmacies_asked == asked

    def test_a_pharmacy_gets_ten_asks_a_day_at_most(self, town: Town, world: World) -> None:
        """R-E3."""
        pharmacy = town.pharmacy_holding()
        for _ in range(10):
            world.make.early_release_ask(pharmacy_id=pharmacy, created_at=NOW, state="EXPIRED")

        assert town.ask() == Asked(None, 0)

    def test_asking_again_in_the_same_turn_returns_the_same_request(self, town: Town) -> None:
        """R-AG6: a retried turn finds its own work."""
        town.pharmacy_holding()

        first, retried, other_key = town.ask("turn-1"), town.ask("turn-1"), town.ask("turn-2")

        assert first == retried == other_key
        assert len(town.asks()) == 1

    def test_a_client_has_five_open_requests_at_most(self, town: Town, world: World) -> None:
        """R-E5."""
        town.pharmacy_holding()
        for _ in range(5):
            other = world.make.claim(client_id=town.client)
            world.make.early_release_request(client_id=town.client, claim_id=other)

        assert refusal(town.ask).code is Code.LIMIT_EARLY_RELEASE

    def test_only_a_waiting_need_can_be_asked_for(self, town: Town, world: World) -> None:
        town.pharmacy_holding()
        tx = world.tx()
        claims.cancel_watch(tx, town.client, town.claim)
        world.settle(tx)

        assert refusal(town.ask).code is Code.CLAIM_NOT_ACTIVE


class TestThePharmacysAnswer:
    def test_accepting_holds_the_box_and_offers_it_to_the_client_for_two_hours(
        self, town: Town, world: World
    ) -> None:
        """R-E6, O8."""
        pharmacy = town.pharmacy_holding()
        town.ask()

        ask = town.accept(pharmacy, qty=2, price_lbp=700_000)

        assert (ask.state, ask.accepted_qty, ask.accepted_price_lbp) == ("ACCEPTED", 2, 700_000)
        (offer,) = town.offers()
        assert (offer.source, offer.qty_locked, offer.price_snapshot_lbp) == (
            "early_release",
            2,
            700_000,
        )
        assert offer.offer_expires_at == NOW + timedelta(hours=2)
        assert offer.early_release_ask_id == ask.id
        assert town.claim_row().state == "OFFER_PENDING"
        assert world.notifications(town.client) == ["CN-9"]
        stock = world.one(
            "SELECT qty_on_hand, qty_reserved FROM inventory_items WHERE pharmacy_id = :p",
            p=pharmacy,
        )
        assert tuple(stock) == (4, 2)
        card = world.one("SELECT cards FROM chat_messages WHERE conversation_id = :c", c=town.chat)
        assert card.cards[0]["template"] == "offer"

    def test_the_price_and_the_quantity_have_limits(self, town: Town) -> None:
        """R-PR1: never above the public price. Never more than the client still needs."""
        pharmacy = town.pharmacy_holding()
        town.ask()

        too_dear = refusal(lambda: town.accept(pharmacy, price_lbp=1_000_001))
        too_many = refusal(lambda: town.accept(pharmacy, qty=3))

        assert too_dear.code is Code.PRICE_ABOVE_PUBLIC
        assert too_many.code is Code.UNITS_INVALID
        assert town.offers() == []
        assert town.accept(pharmacy, price_lbp=0).accepted_price_lbp == 0  # a donation

    def test_only_the_asked_pharmacy_can_answer_and_only_in_time(
        self, town: Town, world: World
    ) -> None:
        pharmacy = town.pharmacy_holding()
        town.ask()
        ask_id = town.asks()[pharmacy].id
        stranger = world.make.pharmacy()

        not_theirs = refusal(
            lambda: early_release.accept_ask(world.tx(), stranger, ask_id, qty=1, price_lbp=1)
        )
        world.later(hours=2)
        too_late = refusal(lambda: town.accept(pharmacy))

        assert (not_theirs.code, too_late.code) == (Code.NOT_FOUND, Code.ASK_NOT_OPEN)

    def test_a_second_pharmacy_that_accepts_finds_the_need_already_being_met(
        self, town: Town
    ) -> None:
        """R-W3: the early-release path holds one offer at a time. Nothing is locked."""
        first, second = town.pharmacy_holding(), town.pharmacy_holding(metres_away=400)
        town.ask()
        town.accept(first, qty=2)

        late = town.accept(second, qty=2)

        assert late.state == "WITHDRAWN"
        assert len(town.offers()) == 1

    def test_a_pharmacy_that_answers_after_the_need_was_met_is_thanked(
        self, town: Town, world: World
    ) -> None:
        """R-E6, FR-15: "Thank you, this need was just met"."""
        pharmacy = town.pharmacy_holding()
        town.ask()
        with world.as_owner():
            world.connection.exec_driver_sql(
                "UPDATE claims SET state = 'FULFILLED', qty_missing = 0 WHERE id = %s",
                (town.claim,),
            )

        answer = town.accept(pharmacy)

        assert answer.state == "WITHDRAWN"
        assert town.offers() == []


class TestHowItEnds:
    def test_the_client_accepts_and_the_other_asks_are_withdrawn(
        self, town: Town, world: World
    ) -> None:
        """R-E7."""
        first, second = town.pharmacy_holding(), town.pharmacy_holding(metres_away=400)
        town.ask()
        town.accept(first, qty=2)
        (offer,) = town.offers()

        tx = world.tx()
        orders.accept_offer(tx, town.client, offer.id, TODAY)
        world.settle(tx)

        assert town.request().state == "FULFILLED"
        assert town.asks()[second].state == "WITHDRAWN"
        assert town.claim_row().state == "FULFILLED"
        assert world.notifications(town.client) == ["CN-9", "CN-3"]

    def test_when_every_pharmacy_declines_the_agent_is_woken(
        self, town: Town, world: World
    ) -> None:
        """R-E7, R-AG4: UNFULFILLED is a decision event while the window is open."""
        first, second = town.pharmacy_holding(), town.pharmacy_holding(metres_away=400)
        town.ask()

        town.decline(first)
        after_one = town.request().state
        town.decline(second)

        assert (after_one, town.request().state) == ("OPEN", "UNFULFILLED")
        event = world.one(
            "SELECT kind, text_redacted FROM chat_messages WHERE conversation_id = :c", c=town.chat
        )
        assert event.kind == "event"
        assert '"type": "early_release_unfulfilled"' in event.text_redacted
        # The reason is a code. Nothing a pharmacy typed is in the event (R-AG8).
        assert "keeping_it" not in event.text_redacted
        pending = world.one("SELECT pending_turn_at FROM conversations WHERE id = :c", c=town.chat)
        assert pending.pending_turn_at == NOW

    def test_no_answer_in_two_hours_ends_the_ask(self, town: Town, world: World) -> None:
        pharmacy = town.pharmacy_holding()
        town.ask()
        tasks = world.clock_tasks()

        world.later(hours=1, minutes=59)
        too_early = tasks.expire_asks()
        world.later(minutes=1)
        expired = tasks.expire_asks()

        assert (too_early, expired) == (0, 1)
        assert town.asks()[pharmacy].state == "EXPIRED"
        assert town.request().state == "UNFULFILLED"

    def test_an_offer_the_client_lets_expire_ends_the_request_too(
        self, town: Town, world: World
    ) -> None:
        """O10: the box simply goes back to being private."""
        pharmacy = town.pharmacy_holding()
        town.ask()
        town.accept(pharmacy)
        world.later(hours=2)

        world.clock_tasks().expire_offers()

        assert town.offers("OFFER_EXPIRED")[0].close_reason == "expired"
        assert town.request().state == "UNFULFILLED"
        assert town.claim_row().state == "ACTIVE"
        stock = world.one(
            "SELECT qty_reserved FROM inventory_items WHERE pharmacy_id = :p", p=pharmacy
        )
        assert stock.qty_reserved == 0

    def test_the_same_medicine_is_not_asked_for_again_within_a_day(self, town: Town) -> None:
        """R-E5."""
        pharmacy = town.pharmacy_holding()
        town.ask("first")
        town.decline(pharmacy)

        error = refusal(lambda: town.ask("second"))

        assert error.code is Code.LIMIT_EARLY_RELEASE
        assert error.details == {"retry_after": NOW + timedelta(hours=24)}


class TestBothPathsAtOnce:
    """R-W3, INV-20: matching and early release work for the same need."""

    def test_accepting_one_offer_withdraws_the_other(self, town: Town, world: World) -> None:
        private = town.pharmacy_holding()
        town.ask()
        town.accept(private, qty=2)
        listed = world.make.pharmacy(lat=33.897, lon=35.484)
        world.make.item(pharmacy_id=listed, product_id=town.product, days_left=60, qty_on_hand=2)
        world.clock_tasks().matching_sweep()
        offers = {offer.source: offer for offer in town.offers()}

        tx = world.tx()
        orders.accept_offer(tx, town.client, offers["watch"].id, TODAY)
        world.settle(tx)

        assert set(offers) == {"early_release", "watch"}
        assert [o.source for o in town.offers("OFFER_WITHDRAWN")] == ["early_release"]
        assert town.claim_row().state == "FULFILLED"
        assert town.request().state == "CANCELLED"
        reserved = world.one(
            "SELECT sum(qty_reserved) AS units FROM inventory_items WHERE product_id = :p",
            p=town.product,
        )
        assert reserved.units == 2

    def test_two_pending_offers_for_one_need_count_once(self, town: Town, world: World) -> None:
        """R-L1: a claim's simultaneous offers are one need."""
        private = town.pharmacy_holding()
        town.ask()
        town.accept(private, qty=2)
        listed = world.make.pharmacy(lat=33.897, lon=35.484)
        world.make.item(pharmacy_id=listed, product_id=town.product, days_left=60, qty_on_hand=2)
        world.clock_tasks().matching_sweep()

        load = orders.open_load(world.tx(), town.client)

        assert len(town.offers()) == 2
        assert (load.orders, load.units_by_group) == (1, {KEY: 2})
