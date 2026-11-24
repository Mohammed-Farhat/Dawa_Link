"""Playing a simulated day (docs/08 §2.4, E2).

The engine holds a simulated clock and a queue of things that happen at given times: a
client's need arrives, a new box reaches a shelf, the worker's clock check runs. Each is
played through the **real services**, the same code the app runs, on a database of its
own. After each one the day "settles": deadlines are acted on, the contender takes its
turns, and pharmacies and clients decide how to react, which puts new things in the queue.

Three rules keep the comparison between contenders honest:
- the scenario (who needs what, when; new boxes) never depends on the contender;
- every chance outcome is drawn from the seed and the thing it belongs to (this box for
  this client), never from a shared stream that one contender's actions would shift;
- pharmacies behave the same for everyone: this module plays them, not the contender.
"""

import heapq
import itertools
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dawalink.db.models import (
    Claim,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    InventoryItem,
    Order,
    Product,
)
from dawalink.domain.clock import ManualClock, at_beirut, beirut_date
from dawalink.domain.numbers import SEARCH_WINDOW
from dawalink.domain.pricing import early_release_suggested_price_lbp
from dawalink.services import catalog, counter, early_release, inventory, search, travel
from dawalink.services.clock_check import ClockTasks
from dawalink.services.context import Tx, unit_of_work
from dawalink.services.errors import ServiceError
from dawalink.services.travel import Location, shared_location
from dawalink.sim import situation
from dawalink.sim.params import Params
from dawalink.sim.scenario import Arrival, Line, Need, Scenario
from dawalink.sim.situation import Trip
from dawalink.sim.world import SimClient, World, numbers_for

# A pharmacy notices that a reserved box is gone within the hour.
NOTICES_AFTER_MIN = (10, 60)
# A pharmacy that answers an early-release ask does it within its two hours.
ANSWERS_AFTER_MIN = (10, 110)
MAX_SETTLE_ROUNDS = 6
OPTIONS_FOR_THE_ORACLE = 50


class NoEmails:
    """A simulated day sends thousands of emails to nobody."""

    def send(self, to: str, subject: str, body: str) -> None:
        return None


@dataclass(frozen=True)
class Decision:
    """A reservation, judged against the client's real situation when it was made."""

    order_id: uuid.UUID
    need_n: int
    pharmacy_n: int
    product_id: uuid.UUID
    units: int
    at: datetime
    # Can this client really pick up there on that day: open while they are free, and reachable?
    works: bool
    minutes: int  # the trip by the client's own means
    # The shortest such trip among the options that work for them, when there was one.
    best_minutes: int | None
    other_brand: bool


class Contender(Protocol):
    name: str

    def arrive(self, sim: "Sim", need: Need) -> None:
        """A client's need arrives: do what this contender does about it."""

    def take_turns(self, sim: "Sim") -> int:
        """Whatever runs without the client (agent turns). Returns how much it did."""

    def react(self, sim: "Sim") -> None:
        """Look at what changed and schedule what the client does about it."""


@dataclass
class Sim:
    """One run's state: the clock, the queue, and what was counted on the way."""

    seed: int
    params: Params
    world: World
    scenario: Scenario
    sessions: sessionmaker[Session]
    clock: ManualClock
    prices: dict[uuid.UUID, int]  # public prices, to turn a budget share into LBP
    medicine_of: dict[uuid.UUID, str]
    # The Ministry's code of each product: the same after every catalog import.
    code_of: dict[uuid.UUID, int] = field(default_factory=dict)
    queue: list[tuple[datetime, int, Callable[[], None]]] = field(default_factory=list)
    _order: Iterator[int] = field(default_factory=itertools.count)
    taps: Counter[int] = field(default_factory=Counter)  # by need
    messages: Counter[int] = field(default_factory=Counter)
    decisions: dict[uuid.UUID, Decision] = field(default_factory=dict)
    seen_orders: set[uuid.UUID] = field(default_factory=set)
    refusals: Counter[str] = field(default_factory=Counter)  # service errors, by code
    swept_at: datetime | None = None  # the last matching sweep
    tries: Counter[tuple[object, ...]] = field(default_factory=Counter)
    seen_asks: set[uuid.UUID] = field(default_factory=set)
    # Cards the client couldn't use (closed when they are free, too far on foot, the
    # wrong day), by need; and those shown after the client had written the reason.
    unusable_cards: Counter[int] = field(default_factory=Counter)
    unusable_after_told: Counter[int] = field(default_factory=Counter)
    # Trips the oracle saw with a straight-line estimate: the road table missed them.
    straight_trips: int = 0

    def __post_init__(self) -> None:
        self.pharmacy_of = {pharmacy.id: pharmacy for pharmacy in self.world.pharmacies}
        self.need_of = {need.client.id: need for need in self.scenario.needs}
        self.tasks = ClockTasks(self.sessions, self.clock, mailer=NoEmails(), batch=500)

    # --- time ---------------------------------------------------------------------------

    @property
    def now(self) -> datetime:
        return self.clock.now()

    @property
    def today(self) -> date:
        return beirut_date(self.now)

    def at(self, when: datetime, action: Callable[[], None]) -> None:
        """Schedules something. A time already past happens next."""
        heapq.heappush(self.queue, (max(when, self.now), next(self._order), action))

    def after(self, minutes: float, action: Callable[[], None]) -> None:
        self.at(self.now + timedelta(minutes=minutes), action)

    # --- chance: always from the seed and the thing it belongs to -------------------------

    def chance(self, *what: object) -> float:
        return numbers_for(self.seed, *what).random()

    def box(self, order: Order) -> tuple[object, ...]:
        """What a reservation is of, in words that are the same in every run: a row's id is
        new each time, and a draw keyed on it could never be compared between two contenders."""
        return self.box_of(order.pharmacy_id, order.product_id)

    def box_of(self, pharmacy_id: uuid.UUID, product_id: uuid.UUID) -> tuple[object, ...]:
        return (
            self.pharmacy_of[pharmacy_id].n,
            self.code_of.get(product_id, str(product_id)),
        )

    def minutes_between(self, low: int, high: int, *what: object) -> int:
        return numbers_for(self.seed, "wait", *what).randrange(low, high + 1)

    def client_waits(self, *what: object) -> int:
        """How long this client takes to react to this thing."""
        return self.minutes_between(*self.params.react_after_min, *what)

    def client_answers(self, *what: object) -> int:
        """How long this client takes to answer this question of the agent."""
        return self.minutes_between(*self.params.answers_after_min, *what)

    # --- the services ---------------------------------------------------------------------

    @contextmanager
    def tx(self) -> Iterator[Tx]:
        with unit_of_work(self.sessions, self.clock) as tx:
            yield tx

    def attempt(self, action: Callable[[Tx], object]) -> bool:
        """Runs one action. A refusal by a rule is a normal outcome, and is counted."""
        try:
            with self.tx() as tx:
                action(tx)
        except ServiceError as error:
            self.refusals[error.code.value] += 1
            return False
        return True

    # --- what everyone needs to know about a client and a need ---------------------------

    def location_of(self, client: SimClient) -> Location:
        return shared_location(client.lat, client.lon)

    def pickup_day(self, need: Need) -> date:
        return beirut_date(need.at) + timedelta(days=need.pickup_in_days)

    def budget_lbp(self, line: Line) -> int | None:
        if line.budget_share is None:
            return None
        return int(self.prices[line.product_id] * line.budget_share)

    def window_ends(self, need: Need) -> datetime:
        return need.at + SEARCH_WINDOW

    def works_for(self, need: Need, pharmacy_id: uuid.UUID, trip: Trip, day: date) -> bool:
        """Can this client really pick up there on that day? Never before the day they can go."""
        return day >= self.pickup_day(need) and situation.works(
            need.client, self.pharmacy_of[pharmacy_id], trip, day, self.now
        )


def _stock_arrives(sim: Sim, arrival: Arrival) -> None:
    pharmacy = next(p for p in sim.world.pharmacies if p.n == arrival.pharmacy_n)
    sim.attempt(
        lambda tx: inventory.add_item(
            tx,
            pharmacy.id,
            product_id=arrival.product_id,
            batch=f"N{sim.seed}-{arrival.pharmacy_n}-{int(arrival.at.timestamp())}",
            expiry_date=sim.today + timedelta(days=arrival.days_left),
            quantity=arrival.units,
        )
    )


def _judge(sim: Sim, tx: Tx, order: Order, need: Need) -> Decision:
    """How good was this choice of pharmacy for the client's real situation? (E2)"""
    client = need.client
    day = order.pickup_day or sim.pickup_day(need)
    asked = next(
        (
            line
            for line in need.lines
            if sim.medicine_of.get(line.product_id) == _medicine(sim, tx, order)
        ),
        None,
    )
    # The medicine itself is every catalog row of its name, as the services have it (Q38).
    own = catalog.same_brand(tx, asked.product_id) if asked is not None else {order.product_id}
    brands = sorted(own | {order.product_id}, key=str)
    found = search.search_listings(
        tx,
        client_id=client.id,
        product_ids=brands,
        location=sim.location_of(client),
        days_of_use=order.days_of_use,
        pickup_day=day,
        # The best choice is among what the client could afford, like the choice itself.
        max_price_lbp=sim.budget_lbp(asked) if asked is not None else None,
        limit=OPTIONS_FOR_THE_ORACLE,
    )
    trips = {
        listing.pharmacy.id: Trip(listing.travel.car_min, listing.travel.walk_min)
        for listing in found.listings
    }
    sim.straight_trips += sum(listing.travel.source != "road" for listing in found.listings)
    chosen = trips.get(order.pharmacy_id)
    if chosen is None:  # the box it took was the last one: it isn't listed any more
        way = travel.travel_to(tx, sim.location_of(client), [order.pharmacy_id])[order.pharmacy_id]
        chosen = Trip(way.car_min, way.walk_min)
        trips[order.pharmacy_id] = chosen
    working = [
        trip.minutes_for(client)
        for pharmacy_id, trip in trips.items()
        if sim.works_for(need, pharmacy_id, trip, day)
    ]
    return Decision(
        order_id=order.id,
        need_n=need.n,
        pharmacy_n=sim.pharmacy_of[order.pharmacy_id].n,
        product_id=order.product_id,
        units=order.qty_locked,
        at=sim.now,
        works=sim.works_for(need, order.pharmacy_id, chosen, day),
        minutes=chosen.minutes_for(client),
        best_minutes=min(working) if working else None,
        other_brand=asked is not None and order.product_id not in own,
    )


def _medicine(sim: Sim, tx: Tx, order: Order) -> str:
    known = sim.medicine_of.get(order.product_id)
    if known is None:
        known = catalog.medicine_group(tx.session.get_one(Product, order.product_id))
        sim.medicine_of[order.product_id] = known
    return known


def _pharmacies_react(sim: Sim) -> int:
    """Every new reservation is judged, and its box may turn out to be gone already."""
    with sim.tx() as tx:
        new = [
            order
            for order in tx.session.execute(
                select(Order).where(Order.state == "RESERVED")
            ).scalars()
            if order.id not in sim.seen_orders
        ]
        for order in new:
            sim.seen_orders.add(order.id)
            need = sim.need_of.get(order.client_id)
            if need is None:
                continue
            decision = _judge(sim, tx, order, need)
            sim.decisions[order.id] = decision
            arrives = _arrives_at_the_counter(sim, order, need, decision)
            # A second reservation of the same box by the same client is a new draw.
            box = (*sim.box(order), need.client.n)
            sim.tries[box] += 1
            box = (*box, sim.tries[box])
            gone = sim.chance("gone", *box)
            if gone < sim.params.not_available:
                # The box was sold at the counter before the app was updated. The pharmacist
                # notices after a while, or when the client stands at the counter.
                wait = sim.minutes_between(*NOTICES_AFTER_MIN, "gone", *box)
                notices = sim.now + timedelta(minutes=wait)
                sim.at(
                    min(notices, arrives or notices),
                    lambda order=order: _mark_gone(sim, order.pharmacy_id, order.id),  # type: ignore[misc]
                )
            elif arrives is not None:
                sim.at(arrives, lambda order=order: _pick_up(sim, order.pharmacy_id, order.id))  # type: ignore[misc]
    return len(new)


def _arrives_at_the_counter(
    sim: Sim, order: Order, need: Need, decision: Decision
) -> datetime | None:
    """When the client reaches the counter. None when they can't (the pharmacy is closed
    while they are free, or it is too far): nobody comes, and it becomes a no-show."""
    if not decision.works or order.pickup_day is None:
        return None
    pharmacy = sim.pharmacy_of[order.pharmacy_id]
    trip = Trip(decision.minutes, decision.minutes)  # already by the client's own means
    return situation.pickup_moment(need.client, pharmacy, trip, order.pickup_day, sim.now)


def _pick_up(sim: Sim, pharmacy_id: uuid.UUID, order_id: uuid.UUID) -> None:
    sim.attempt(lambda tx: counter.mark_picked_up(tx, pharmacy_id, order_id))


def _mark_gone(sim: Sim, pharmacy_id: uuid.UUID, order_id: uuid.UUID) -> None:
    sim.attempt(lambda tx: counter.mark_not_available(tx, pharmacy_id, order_id))


def _pharmacies_answer_asks(sim: Sim) -> int:
    """Each new early-release ask: the pharmacy answers or not, and releases or keeps the box.

    It depends on the pharmacy, the medicine and the client only: the same ask gets the same
    answer whoever sent it.
    """
    with sim.tx() as tx:
        rows = tx.session.execute(
            select(EarlyReleaseAsk, EarlyReleaseRequest.client_id)
            .join(EarlyReleaseRequest, EarlyReleaseRequest.id == EarlyReleaseAsk.er_request_id)
            .where(EarlyReleaseAsk.state == "ASKED")
        ).all()
    new = [(ask, client_id) for ask, client_id in rows if ask.id not in sim.seen_asks]
    for ask, client_id in new:
        sim.seen_asks.add(ask.id)
        need = sim.need_of.get(client_id)
        if need is None:
            continue
        box = ("ask", *sim.box_of(ask.pharmacy_id, ask.product_id), need.client.n)
        sim.tries[box] += 1
        box = (*box, sim.tries[box])
        if sim.chance("answers", *box) >= sim.params.answers_ask:
            continue  # no answer: the ask ends by itself after its two hours
        releases = sim.chance("releases", *box) < sim.params.accepts_ask
        sim.after(
            sim.minutes_between(*ANSWERS_AFTER_MIN, *box),
            lambda ask=ask, releases=releases: _answer_ask(sim, ask.pharmacy_id, ask.id, releases),  # type: ignore[misc]
        )
    return len(new)


def _answer_ask(sim: Sim, pharmacy_id: uuid.UUID, ask_id: uuid.UUID, releases: bool) -> None:
    with sim.tx() as tx:
        ask = tx.session.get_one(EarlyReleaseAsk, ask_id)
        if ask.state != "ASKED":
            return
        item = tx.session.get_one(InventoryItem, ask.inventory_item_id)
        request = tx.session.get_one(EarlyReleaseRequest, ask.er_request_id)
        missing = tx.session.get_one(Claim, request.claim_id).qty_missing
        units = min(missing, item.qty_on_hand - item.qty_reserved)
        price = early_release_suggested_price_lbp(
            tx.session.get_one(Product, ask.product_id).public_price_lbp
        )
    if not releases:
        sim.attempt(lambda tx: early_release.decline_ask(tx, pharmacy_id, ask_id, "keeping_it"))
    elif units < 1:
        sim.attempt(
            lambda tx: early_release.decline_ask(tx, pharmacy_id, ask_id, "no_longer_in_stock")
        )
    else:
        sim.attempt(
            lambda tx: early_release.accept_ask(tx, pharmacy_id, ask_id, qty=units, price_lbp=price)
        )


def _clock_check(sim: Sim) -> int:
    """Everything the worker's clock check would do now, until nothing is left."""
    tasks = sim.tasks
    steps = (
        tasks.expire_offers,
        tasks.expire_reservations,
        tasks.expire_asks,
        tasks.resolve_early_release,
        tasks.lift_pauses,
        tasks.run_window_checks,
        tasks.end_windows,
        tasks.expire_watches,
    )
    done = 0
    for step in steps:
        while (acted := step()) > 0:
            done += acted
    # New stock, a freed box and a new claim are matched at once by the services themselves.
    # The sweep only catches what time alone changes, so once per tick is enough; it is by
    # far the slowest task, and the real worker's 5 seconds would be simulated for nothing.
    if sim.swept_at is None or sim.now - sim.swept_at >= sim.params.tick:
        sim.swept_at = sim.now
        while (acted := tasks.matching_sweep()) > 0:
            done += acted
    return done


def settle(sim: Sim, contender: Contender) -> None:
    """After something happened: deadlines, the contender's own turns, then reactions."""
    for _ in range(MAX_SETTLE_ROUNDS):
        did = (
            _clock_check(sim)
            + contender.take_turns(sim)
            + _pharmacies_react(sim)
            + _pharmacies_answer_asks(sim)
        )
        contender.react(sim)
        if did == 0:
            return


def play(sim: Sim, contender: Contender) -> None:
    """Plays the whole day: from before the first request until every window has closed."""
    for need in sim.scenario.needs:
        sim.at(need.at, lambda need=need: contender.arrive(sim, need))  # type: ignore[misc]
    for arrival in sim.scenario.arrivals:
        sim.at(arrival.at, lambda arrival=arrival: _stock_arrives(sim, arrival))  # type: ignore[misc]
    last_window = at_beirut(sim.params.day, sim.params.last_request) + SEARCH_WINDOW
    tick = at_beirut(sim.params.day, time(7, 30))
    while tick <= last_window + sim.params.tick:
        sim.at(tick, lambda: None)  # a moment for the clock check to run
        tick += sim.params.tick
    while sim.queue:
        when, _, action = heapq.heappop(sim.queue)
        if when > last_window + 2 * sim.params.tick:
            break
        if when > sim.now:
            sim.clock.set(when)
            # Deadlines that passed in between come first, as with the real worker's 5
            # seconds: a client can't tap a card of a request whose window just ended.
            _clock_check(sim)
        action()
        settle(sim, contender)


def stock_units(sim: Sim) -> int:
    with sim.tx() as tx:
        rows = tx.session.execute(select(InventoryItem.qty_on_hand)).scalars()
        return sum(rows)
