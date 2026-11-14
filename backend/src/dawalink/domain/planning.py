"""The multi-medicine planner behind the `plan_basket` tool (docs/04 R-RQ5, R-RT2).

Given a basket and the boxes that could serve it, it returns candidate plans: which pharmacies
to visit, what to take from each, in which order, and what stays missing. It's deterministic:
the same input always gives the same plans. The agent chooses among them; it never computes
them (R-AG9).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations, pairwise, permutations
from typing import Literal

from dawalink.domain.numbers import PLAN_MAX_CANDIDATE_PHARMACIES, PLAN_MAX_PHARMACIES

Preference = Literal["fewest_trips", "cheapest", "nearest", "walkable"]
MissingReason = Literal[
    "none_listed", "over_budget", "not_enough", "expires_too_early", "not_on_that_day"
]
TravelSource = Literal["road", "straight"]

CLIENT = "client"  # the starting point of every route


@dataclass(frozen=True)
class BasketItem:
    key: str
    qty: int
    # Why nothing can be offered, when the service found no usable box for this item.
    reason_if_none: MissingReason = "none_listed"


@dataclass(frozen=True)
class Box:
    """A visible listing that fits this item's days of use and price limit."""

    listing_id: str
    item_key: str
    pharmacy_id: str
    price_lbp: int
    available: int


@dataclass(frozen=True)
class Leg:
    car_min: int
    walk_min: int
    source: TravelSource = "road"


@dataclass(frozen=True)
class Pick:
    item_key: str
    listing_id: str
    qty: int
    price_lbp: int


@dataclass(frozen=True)
class Stop:
    pharmacy_id: str
    picks: tuple[Pick, ...]


@dataclass(frozen=True)
class Missing:
    item_key: str
    qty_missing: int
    reason: MissingReason


@dataclass(frozen=True)
class Plan:
    stops: tuple[Stop, ...]  # in visiting order
    total_car_min: int
    total_walk_min: int
    source: TravelSource
    total_lbp: int
    missing: tuple[Missing, ...]

    @property
    def pharmacies_count(self) -> int:
        return len(self.stops)

    @property
    def units(self) -> int:
        return sum(pick.qty for stop in self.stops for pick in stop.picks)


def plan_basket(
    items: Sequence[BasketItem],
    boxes: Sequence[Box],
    legs: Mapping[tuple[str, str], Leg],
    *,
    preference: Preference | None = None,
    max_plans: int = 3,
) -> list[Plan]:
    """Candidate plans for a basket, best first.

    `legs[(a, b)]` is the trip from `a` to `b`, where a place is a pharmacy ID or `CLIENT`.

    Every plan covers as many units as any plan could. Among those, the order is: total
    travel time, then the number of pharmacies, then the total price (R-RQ5). A preference
    moves one of these to the front. One medicine's quantity may be split across pharmacies.

    Each item takes its cheapest boxes among the pharmacies visited. That gives the best plan
    as long as an extra stop never shortens a trip, which holds on real roads.
    """
    on_foot = preference == "walkable"
    # Each item's usable boxes, cheapest first.
    by_item = {
        item.key: sorted(
            (box for box in boxes if box.item_key == item.key and box.available > 0),
            key=lambda box: (box.price_lbp, box.listing_id),
        )
        for item in items
    }
    pharmacies = _candidate_pharmacies(by_item, legs, on_foot)
    plans: list[Plan] = []
    for size in range(1, min(PLAN_MAX_PHARMACIES, len(pharmacies)) + 1):
        for chosen in combinations(pharmacies, size):
            picks = _cheapest_picks(items, by_item, frozenset(chosen))
            if {pick_pharmacy for pick_pharmacy, _ in picks} != set(chosen):
                continue  # a pharmacy with nothing to take: a smaller plan says the same
            plans.append(_build_plan(items, by_item, picks, legs, on_foot))
    if not plans:
        return []
    most_units = max(plan.units for plan in plans)
    best = [plan for plan in plans if plan.units == most_units]
    best.sort(key=lambda plan: _order(plan, preference))
    return best[:max_plans]


def _candidate_pharmacies(
    by_item: Mapping[str, Sequence[Box]], legs: Mapping[tuple[str, str], Leg], on_foot: bool
) -> list[str]:
    """The pharmacies worth weighing, in a fixed order.

    Normally every pharmacy with a usable box. When there are very many, the nearest ones,
    plus the cheapest pharmacy for each item, so a far but cheap option isn't lost.
    """
    stocking = sorted({box.pharmacy_id for item_boxes in by_item.values() for box in item_boxes})
    if len(stocking) <= PLAN_MAX_CANDIDATE_PHARMACIES:
        return stocking

    def trip(pharmacy_id: str) -> int:
        leg = legs[(CLIENT, pharmacy_id)]
        return leg.walk_min if on_foot else leg.car_min

    nearest = sorted(stocking, key=lambda pharmacy_id: (trip(pharmacy_id), pharmacy_id))
    keep = set(nearest[:PLAN_MAX_CANDIDATE_PHARMACIES])
    for item_boxes in by_item.values():
        if item_boxes:
            keep.add(item_boxes[0].pharmacy_id)
    return sorted(keep)


def _cheapest_picks(
    items: Sequence[BasketItem], by_item: Mapping[str, Sequence[Box]], chosen: frozenset[str]
) -> list[tuple[str, Pick]]:
    """For each item, take the cheapest boxes at the chosen pharmacies, up to its quantity."""
    picks: list[tuple[str, Pick]] = []
    for item in items:
        left = item.qty
        for box in by_item[item.key]:
            if left == 0:
                break
            if box.pharmacy_id in chosen:
                qty = min(left, box.available)
                picks.append((box.pharmacy_id, Pick(item.key, box.listing_id, qty, box.price_lbp)))
                left -= qty
    return picks


def _build_plan(
    items: Sequence[BasketItem],
    by_item: Mapping[str, Sequence[Box]],
    picks: Sequence[tuple[str, Pick]],
    legs: Mapping[tuple[str, str], Leg],
    on_foot: bool,
) -> Plan:
    order, car_min, walk_min, source = best_route(sorted({p for p, _ in picks}), legs, on_foot)
    stops = tuple(
        Stop(pharmacy_id, tuple(pick for at, pick in picks if at == pharmacy_id))
        for pharmacy_id in order
    )
    taken = {item.key: 0 for item in items}
    for _, pick in picks:
        taken[pick.item_key] += pick.qty
    missing = tuple(
        # Boxes exist but don't cover the quantity, or nothing usable exists at all.
        Missing(
            item.key,
            item.qty - taken[item.key],
            "not_enough" if by_item[item.key] else item.reason_if_none,
        )
        for item in items
        if taken[item.key] < item.qty
    )
    total = sum(pick.qty * pick.price_lbp for _, pick in picks)
    return Plan(stops, car_min, walk_min, source, total, missing)


def best_route(
    pharmacies: Sequence[str], legs: Mapping[tuple[str, str], Leg], on_foot: bool = False
) -> tuple[tuple[str, ...], int, int, TravelSource]:
    """The visiting order with the shortest total trip, starting from the client (R-RT2).

    Every order is tried: a plan has at most a handful of stops. Returns the order, the total
    minutes by car and on foot along it, and "straight" if any leg is only an estimate.
    """
    best: tuple[tuple[int, tuple[str, ...]], int, int, TravelSource] | None = None
    for order in permutations(sorted(pharmacies)):
        route = [legs[leg] for leg in pairwise((CLIENT, *order))]
        car_min = sum(leg.car_min for leg in route)
        walk_min = sum(leg.walk_min for leg in route)
        source: TravelSource = (
            "straight" if any(leg.source == "straight" for leg in route) else "road"
        )
        rank = (walk_min if on_foot else car_min, order)
        if best is None or rank < best[0]:
            best = (rank, car_min, walk_min, source)
    assert best is not None
    return best[0][1], best[1], best[2], best[3]


def _order(plan: Plan, preference: Preference | None) -> tuple[int, int, int, tuple[str, ...]]:
    trip = plan.total_walk_min if preference == "walkable" else plan.total_car_min
    tie_break = tuple(stop.pharmacy_id for stop in plan.stops)
    if preference == "fewest_trips":
        return (plan.pharmacies_count, trip, plan.total_lbp, tie_break)
    if preference == "cheapest":
        return (plan.total_lbp, trip, plan.pharmacies_count, tie_break)
    return (trip, plan.pharmacies_count, plan.total_lbp, tie_break)
