"""The best plans of a basket, found by trying everything (docs/08 §2.5).

This is the P-set's answer key. It shares no code with the planner (`domain/planning.py`)
and doesn't work the way it does: it tries every quantity from every box, every set of
pharmacies and every visiting order. It is slow, and only runs when the P-set is built.

**What "the best plans" means** (docs/04 R-RQ5, R-RT2, N-48):
1. A plan visits 1 to 4 pharmacies.
2. At those pharmacies it takes as many units of each medicine as they hold, up to the
   quantity asked, for the lowest total price.
3. **Every stop earns its place:** without any one of its pharmacies, the plan would
   get fewer units or cost more. A set of pharmacies with a stop that buys nothing isn't
   a plan of its own: it is the smaller plan with a detour.
4. Only the plans that cover the most units any plan covers are listed.
5. They are ordered by the client's preference: by default the trip's minutes, then the
   number of stops, then the price; "fewest trips" puts the stops first, "cheapest" the
   price, and "walkable" counts the minutes on foot.
6. The trip is the shortest order of visiting, starting from the client.
"""

from itertools import combinations, pairwise, permutations, product

from dawalink.domain.numbers import PLAN_MAX_PHARMACIES
from dawalink.evals.plan_set import CLIENT, Order, PBox, PCase, PItem, PPlan

Value = tuple[int, int]  # units, price


class _Shelves:
    """What a set of pharmacies can give for the basket, by trying every quantity."""

    def __init__(self, case: PCase) -> None:
        self.case = case
        self._known: dict[tuple[str, frozenset[str]], Value] = {}

    def of_item(self, item: PItem, pharmacies: frozenset[str]) -> Value:
        boxes = [
            box for box in self.case.boxes if box.item == item.key and box.pharmacy in pharmacies
        ]
        key = (item.key, frozenset(box.id for box in boxes))
        if key not in self._known:
            self._known[key] = _most_units_for_least(item.qty, boxes)
        return self._known[key]

    def of(self, pharmacies: frozenset[str]) -> Value:
        values = [self.of_item(item, pharmacies) for item in self.case.items]
        return sum(units for units, _ in values), sum(price for _, price in values)


def _most_units_for_least(qty: int, boxes: list[PBox]) -> Value:
    best: Value = (0, 0)
    for amounts in product(*[range(min(box.available, qty) + 1) for box in boxes]):
        units = sum(amounts)
        if units > qty:
            continue
        price = sum(amount * box.price_lbp for amount, box in zip(amounts, boxes, strict=True))
        if units > best[0] or (units == best[0] and price < best[1]):
            best = (units, price)
    return best


def trip(
    case: PCase, pharmacies: frozenset[str], *, on_foot: bool = False
) -> tuple[int, tuple[str, ...]]:
    """The shortest way to visit all of them from the client: its minutes and its order."""
    minutes = {(start, end): (walk if on_foot else car) for start, end, car, walk in case.legs}
    ways = []
    for order in permutations(sorted(pharmacies)):
        route = (CLIENT, *order)
        ways.append((sum(minutes[leg] for leg in pairwise(route)), order))
    return min(ways)


def _sort_key(plan: PPlan, order: Order) -> tuple[int, int, int, list[str]]:
    if order == "fewest_trips":
        return (plan.stops, plan.minutes, plan.lbp, plan.pharmacies)
    if order == "cheapest":
        return (plan.lbp, plan.minutes, plan.stops, plan.pharmacies)
    return (plan.minutes, plan.stops, plan.lbp, plan.pharmacies)


def every_plan(case: PCase, order: Order) -> list[PPlan]:
    """Every plan of the basket (rules 1 to 3 and 6), in no particular order."""
    shelves = _Shelves(case)
    stocking = sorted({box.pharmacy for box in case.boxes})
    plans = []
    for size in range(1, min(PLAN_MAX_PHARMACIES, len(stocking)) + 1):
        for chosen in combinations(stocking, size):
            here = frozenset(chosen)
            value = shelves.of(here)
            if value[0] == 0:
                continue
            # Rule 3: taking any pharmacy away must cost units or money.
            if any(shelves.of(here - {pharmacy}) == value for pharmacy in chosen):
                continue
            minutes, route = trip(case, here, on_foot=order == "walkable")
            plans.append(
                PPlan(
                    units=value[0], minutes=minutes, stops=size, lbp=value[1], pharmacies=[*route]
                )
            )
    return plans


def best_plans(case: PCase, order: Order, top: int = 3) -> list[PPlan]:
    """The plans a client asking in this order should be shown, best first."""
    plans = every_plan(case, order)
    if not plans:
        return []
    most = max(plan.units for plan in plans)
    best = [plan for plan in plans if plan.units == most]
    best.sort(key=lambda plan: _sort_key(plan, order))
    return best[:top]


def shorter_with_a_detour(case: PCase) -> int:
    """How many minutes the road table "saves" by adding a pharmacy to the best plan's trip.

    Road times are whole minutes, so now and then a route through one more pharmacy adds up
    to less than the direct one. Such a detour buys nothing (rule 3), and neither the
    planner nor this answer key ever takes it. 0 when no detour looks shorter.
    """
    best = best_plans(case, "nearest", top=1)
    if not best:
        return 0
    here = frozenset(best[0].pharmacies)
    others = sorted({box.pharmacy for box in case.boxes} - here)
    saved = 0
    for more in range(1, PLAN_MAX_PHARMACIES - len(here) + 1):
        for extra in combinations(others, more):
            minutes, _ = trip(case, here | set(extra))
            saved = max(saved, best[0].minutes - minutes)
    return saved
