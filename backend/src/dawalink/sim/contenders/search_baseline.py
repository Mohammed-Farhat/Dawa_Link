"""B0, the search baseline: a careful person using the search page alone (docs/08 E2).

For each medicine they search, look at the options, and reserve the one that suits them
best. They know their own situation, so they only reserve where they can really go: the
pharmacy is open while they are free and they can get there. If nothing suits, they press
[Notify me] and accept an offer that suits them. If a pharmacy marks their box "not
available", they search once more.

No assistant, no request: nothing plans across medicines, and nobody asks a pharmacy to
release a box it hasn't listed.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

from dawalink.db.models import Order
from dawalink.domain.orders import OrderSource
from dawalink.domain.vocabulary import ClaimSource
from dawalink.services import claims, orders, search
from dawalink.services.context import Tx
from dawalink.services.orders import ReserveLine
from dawalink.sim import client
from dawalink.sim.engine import Sim
from dawalink.sim.scenario import Line, Need
from dawalink.sim.situation import Trip

OPTIONS_READ = 10  # how far down the results a person looks


@dataclass
class SearchBaseline:
    name: str = "search"
    seen_offers: set[uuid.UUID] = field(default_factory=set)
    seen_gone: set[uuid.UUID] = field(default_factory=set)

    def arrive(self, sim: Sim, need: Need) -> None:
        for line in need.lines:
            self._seek(sim, need, line, line.qty, watch_if_missing=True)

    def take_turns(self, sim: Sim) -> int:
        return 0

    def _seek(
        self, sim: Sim, need: Need, line: Line, units: int, *, watch_if_missing: bool
    ) -> None:
        """Search, reserve what suits, and press [Notify me] for what is still missing."""
        who = need.client
        day = max(sim.pickup_day(need), sim.today)
        with sim.tx() as tx:
            found = search.search_listings(
                tx,
                client_id=who.id,
                product_ids=[line.product_id],
                location=sim.location_of(who),
                days_of_use=line.days_of_use,
                pickup_day=day,
                max_price_lbp=sim.budget_lbp(line),
                on_foot=not who.has_car,
                limit=OPTIONS_READ,
            )
        suits = sorted(
            (
                (
                    Trip(listing.travel.car_min, listing.travel.walk_min).minutes_for(who),
                    listing.price_lbp,
                    listing,
                )
                for listing in found.listings
                if sim.works_for(
                    need,
                    listing.pharmacy.id,
                    Trip(listing.travel.car_min, listing.travel.walk_min),
                    day,
                )
            ),
            key=lambda option: option[:2],
        )
        missing = units
        for _, _, listing in suits:
            if missing == 0:
                break
            take = min(missing, listing.available)
            key = f"sim-b0-{need.n}-{listing.id}-{sim.taps[need.n]}"

            def reserve(tx: Tx, listing=listing, take=take, key=key) -> None:  # type: ignore[no-untyped-def]
                orders.reserve(
                    tx,
                    client_id=who.id,
                    lines=[ReserveLine(listing.id, take, listing.price_lbp, line.days_of_use)],
                    pickup_day=day,
                    source=OrderSource.SEARCH,
                    idempotency_key=key,
                )

            sim.taps[need.n] += 1
            if sim.attempt(reserve):
                missing -= take
        if missing and watch_if_missing:

            def notify_me(tx: Tx) -> None:
                claims.create_watch(
                    tx,
                    client_id=who.id,
                    product_id=line.product_id,
                    location=sim.location_of(who),
                    source=ClaimSource.SEARCH,
                    qty=missing,
                    days_of_use=line.days_of_use,
                    max_price_lbp=sim.budget_lbp(line),
                )

            sim.taps[need.n] += 1
            sim.attempt(notify_me)

    def react(self, sim: Sim) -> None:
        """New offers and boxes marked "not available": the client deals with them later."""
        client.answer_offers_later(sim, self.seen_offers)
        with sim.tx() as tx:
            rows = tx.session.execute(select(Order).where(Order.state == "NOT_AVAILABLE")).scalars()
            changed = [order for order in rows if order.client_id in sim.need_of]
        for order in changed:
            need = sim.need_of[order.client_id]
            if order.id not in self.seen_gone:
                self.seen_gone.add(order.id)
                sim.after(
                    sim.client_waits("gone", need.n, *sim.box(order)),
                    lambda order=order, need=need: self._search_once_more(sim, need, order),  # type: ignore[misc]
                )

    def _search_once_more(self, sim: Sim, need: Need, gone: Order) -> None:
        if sim.now > sim.window_ends(need):
            return
        line = next(
            (line for line in need.lines if line.product_id == gone.product_id),
            None,
        )
        if line is not None:
            self._seek(sim, need, line, gone.qty_requested, watch_if_missing=False)
