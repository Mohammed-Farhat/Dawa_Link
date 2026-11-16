"""The P-set: baskets with their best plans (docs/08 §2.5): python -m dawalink.evals.plan_set

Each case is a basket, the boxes that could serve it, the trips between the places, and
the best plans in each of the four orders a client can ask for. The best plans were found
by trying everything (`plan_oracle.py`) when the file was built, and are stored in it, so
this check runs the planner only: it is one of the checks made before every commit
(docs/08 §7), and it costs nothing.

Nothing here comes from the catalog: medicines are `m1`, `m2`, and prices are invented.
The trips are those of the simulated world's road table (`eval/world/travel.json`).
"""

import sys
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import Field

from dawalink.domain.planning import BasketItem, Box, Leg, MissingReason, Plan, plan_basket
from dawalink.evals.datasets import DATASETS, CaseBase, DatasetError, Strict, read

PLANS_FILE = DATASETS / "plans.jsonl"

# The four orders of docs/04 R-RQ5. "nearest" is also the order when the client said nothing.
Order = Literal["nearest", "fewest_trips", "cheapest", "walkable"]
ORDERS: tuple[Order, ...] = ("nearest", "fewest_trips", "cheapest", "walkable")
CLIENT = "client"


class PItem(Strict):
    key: str
    qty: int = Field(ge=1, le=3)
    reason_if_none: MissingReason = "none_listed"


class PBox(Strict):
    id: str
    item: str
    pharmacy: str
    price_lbp: int = Field(ge=0)
    available: int = Field(ge=1)


class PPlan(Strict):
    """One plan, as it is compared: how good it is, not which boxes it took."""

    units: int
    minutes: int  # the whole trip: on foot for "walkable", by car otherwise
    stops: int
    lbp: int
    pharmacies: list[str]  # in visiting order; for the reader, never compared

    @property
    def rank(self) -> tuple[int, int, int, int]:
        return (self.units, self.minutes, self.stops, self.lbp)


class PCase(CaseBase):
    id: str = Field(pattern=r"^P-\d{4}$")
    shape: str
    client: int  # the client point of the simulated world the trips start from
    items: list[PItem] = Field(min_length=1, max_length=5)
    boxes: list[PBox]
    # (from, to, minutes by car, minutes on foot); a place is "client" or a pharmacy.
    legs: list[tuple[str, str, int, int]]
    expected: dict[Order, list[PPlan]]


def read_cases(path: Path = PLANS_FILE) -> list[PCase]:
    cases = read(path, PCase)
    for case in cases:
        keys = {item.key for item in case.items}
        places = {box.pharmacy for box in case.boxes}
        trips = {(start, end) for start, end, _, _ in case.legs}
        if any(box.item not in keys for box in case.boxes):
            raise DatasetError(f"{path.name}, {case.id}: a box of a medicine nobody asked for")
        wanted = {(start, end) for start in (CLIENT, *places) for end in places if start != end}
        if not wanted <= trips:
            raise DatasetError(f"{path.name}, {case.id}: a trip is missing")
        if set(case.expected) != set(ORDERS):
            raise DatasetError(f"{path.name}, {case.id}: an order has no expected plans")
    return cases


def planned(case: PCase, order: Order) -> list[Plan]:
    """What the planner answers for this basket in this order."""
    return plan_basket(
        [BasketItem(item.key, item.qty, item.reason_if_none) for item in case.items],
        [Box(box.id, box.item, box.pharmacy, box.price_lbp, box.available) for box in case.boxes],
        {(start, end): Leg(car_min, walk_min) for start, end, car_min, walk_min in case.legs},
        preference=None if order == "nearest" else order,
    )


def rank_of(plan: Plan, order: Order) -> tuple[int, int, int, int]:
    minutes = plan.total_walk_min if order == "walkable" else plan.total_car_min
    return (plan.units, minutes, plan.pharmacies_count, plan.total_lbp)


def _inconsistent(case: PCase, plan: Plan) -> str | None:
    """What a plan gets wrong about itself, if anything: its totals, its stock, its trip."""
    boxes = {box.id: box for box in case.boxes}
    asked = {item.key: item.qty for item in case.items}
    minutes = {(start, end): (car, walk) for start, end, car, walk in case.legs}
    taken: dict[str, int] = dict.fromkeys(asked, 0)
    total = 0
    for stop in plan.stops:
        for pick in stop.picks:
            box = boxes[pick.listing_id]
            if box.pharmacy != stop.pharmacy_id or box.item != pick.item_key:
                return "a pick isn't a box of that medicine at that pharmacy"
            if not 1 <= pick.qty <= box.available or pick.price_lbp != box.price_lbp:
                return "a pick takes more than the box holds, or at another price"
            taken[pick.item_key] += pick.qty
            total += pick.qty * pick.price_lbp
    if any(taken[key] > asked[key] for key in asked):
        return "more units than were asked for"
    if total != plan.total_lbp:
        return "the total price isn't the sum of the picks"
    gaps = {gap.item_key: gap.qty_missing for gap in plan.missing}
    if gaps != {key: asked[key] - taken[key] for key in asked if taken[key] < asked[key]}:
        return "the missing units aren't what was asked minus what is taken"
    route = [CLIENT, *(stop.pharmacy_id for stop in plan.stops)]
    car = sum(minutes[leg][0] for leg in pairwise(route))
    walk = sum(minutes[leg][1] for leg in pairwise(route))
    if (car, walk) != (plan.total_car_min, plan.total_walk_min):
        return "the trip's minutes aren't the sum of its legs"
    return None


def check(case: PCase) -> list[str]:
    """Where the planner's answer differs from the expected one. Empty when it is exact."""
    differences = []
    for order in ORDERS:
        found = planned(case, order)
        got = [rank_of(plan, order) for plan in found]
        want = [plan.rank for plan in case.expected[order]]
        if got != want:
            differences.append(f"{case.id} {order}: expected {want}, got {got}")
        for plan in found:
            wrong = _inconsistent(case, plan)
            if wrong:
                differences.append(f"{case.id} {order}: {wrong}")
    return differences


def main() -> None:
    cases = read_cases()
    differences = [line for case in cases for line in check(case)]
    for line in differences:
        print(line)
    rankings = len(cases) * len(ORDERS)
    print(
        f"{len(cases)} baskets, {rankings} rankings: "
        + ("all exact" if not differences else f"{len(differences)} differences")
    )
    sys.exit(1 if differences else 0)


if __name__ == "__main__":
    main()
