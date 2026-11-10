"""The multi-medicine planner (docs/04 R-RQ5, R-RT2)."""

import random
from itertools import permutations, product

from dawalink.domain.planning import (
    CLIENT,
    BasketItem,
    Box,
    Leg,
    Plan,
    best_route,
    plan_basket,
)


def legs_from(
    minutes: dict[tuple[str, str], int], walk_factor: int = 6
) -> dict[tuple[str, str], Leg]:
    """Legs both ways from one table of car minutes; walking takes `walk_factor` times longer."""
    legs: dict[tuple[str, str], Leg] = {}
    for (start, end), car_min in minutes.items():
        legs[(start, end)] = Leg(car_min, car_min * walk_factor)
        if start != CLIENT:
            legs[(end, start)] = Leg(car_min, car_min * walk_factor)
    return legs


# Three pharmacies: A is near, B is a little further, C is far.
LEGS = legs_from(
    {
        (CLIENT, "A"): 5,
        (CLIENT, "B"): 8,
        (CLIENT, "C"): 20,
        ("A", "B"): 4,
        ("A", "C"): 18,
        ("B", "C"): 15,
    }
)
CONCOR = BasketItem("concor", 2)
ASPIRIN = BasketItem("aspirin", 1)
GLUCOPHAGE = BasketItem("glucophage", 1)


def summary(plan: Plan) -> list[tuple[str, list[tuple[str, int]]]]:
    return [
        (stop.pharmacy_id, [(pick.item_key, pick.qty) for pick in stop.picks])
        for stop in plan.stops
    ]


def test_one_pharmacy_that_has_everything_is_the_first_plan() -> None:
    boxes = [
        Box("a-concor", "concor", "A", 600_000, 5),
        Box("a-aspirin", "aspirin", "A", 100_000, 5),
        Box("c-concor", "concor", "C", 400_000, 5),
        Box("c-aspirin", "aspirin", "C", 80_000, 5),
    ]

    plans = plan_basket([CONCOR, ASPIRIN], boxes, LEGS)

    assert summary(plans[0]) == [("A", [("concor", 2), ("aspirin", 1)])]
    assert plans[0].total_car_min == 5
    assert plans[0].total_lbp == 2 * 600_000 + 100_000
    assert plans[0].missing == ()


def test_a_quantity_is_split_across_pharmacies_when_no_one_has_enough() -> None:
    """R-RQ5: Concor x2 = 1 at A + 1 at B."""
    boxes = [Box("a-concor", "concor", "A", 600_000, 1), Box("b-concor", "concor", "B", 650_000, 1)]

    plan = plan_basket([CONCOR], boxes, LEGS)[0]

    assert summary(plan) == [("A", [("concor", 1)]), ("B", [("concor", 1)])]
    assert plan.total_car_min == 5 + 4  # client -> A -> B
    assert plan.missing == ()


def test_plans_are_listed_by_travel_time_then_pharmacies_then_price() -> None:
    boxes = [
        Box("a-concor", "concor", "A", 600_000, 5),
        Box("b-concor", "concor", "B", 500_000, 5),
        Box("c-concor", "concor", "C", 300_000, 5),
    ]

    plans = plan_basket([CONCOR], boxes, LEGS)

    assert [plan.stops[0].pharmacy_id for plan in plans] == ["A", "B", "C"]


def test_the_cheapest_preference_puts_price_first() -> None:
    boxes = [
        Box("a-concor", "concor", "A", 600_000, 5),
        Box("c-concor", "concor", "C", 300_000, 5),
    ]

    assert plan_basket([CONCOR], boxes, LEGS)[0].stops[0].pharmacy_id == "A"
    assert plan_basket([CONCOR], boxes, LEGS, preference="cheapest")[0].stops[0].pharmacy_id == "C"


def test_fewest_trips_prefers_one_stop_over_a_quicker_two_stop_plan() -> None:
    legs = legs_from(
        {
            (CLIENT, "A"): 2,
            (CLIENT, "B"): 3,
            (CLIENT, "C"): 9,
            ("A", "B"): 1,
            ("A", "C"): 9,
            ("B", "C"): 9,
        }
    )
    boxes = [
        Box("a-concor", "concor", "A", 600_000, 5),
        Box("b-aspirin", "aspirin", "B", 100_000, 5),
        Box("c-concor", "concor", "C", 600_000, 5),
        Box("c-aspirin", "aspirin", "C", 100_000, 5),
    ]

    quickest = plan_basket([CONCOR, ASPIRIN], boxes, legs)[0]
    fewest = plan_basket([CONCOR, ASPIRIN], boxes, legs, preference="fewest_trips")[0]

    assert [stop.pharmacy_id for stop in quickest.stops] == ["A", "B"]  # 3 minutes in all
    assert [stop.pharmacy_id for stop in fewest.stops] == ["C"]  # 9 minutes, one stop


def test_walkable_ranks_by_walking_time() -> None:
    legs = {
        (CLIENT, "A"): Leg(car_min=3, walk_min=50),  # quick by car, across a highway on foot
        (CLIENT, "B"): Leg(car_min=6, walk_min=9),
        ("A", "B"): Leg(4, 30),
        ("B", "A"): Leg(4, 30),
    }
    boxes = [Box("a-concor", "concor", "A", 1, 5), Box("b-concor", "concor", "B", 1, 5)]

    assert plan_basket([CONCOR], boxes, legs)[0].stops[0].pharmacy_id == "A"
    assert plan_basket([CONCOR], boxes, legs, preference="walkable")[0].stops[0].pharmacy_id == "B"


def test_the_route_is_the_shortest_visiting_order_from_the_client() -> None:
    """R-RT2. The legs here differ by direction, as one-way streets do."""
    legs = {
        (CLIENT, "A"): Leg(10, 60),
        (CLIENT, "B"): Leg(4, 24),
        ("A", "B"): Leg(20, 120),
        ("B", "A"): Leg(3, 18),
    }

    order, car_min, walk_min, source = best_route(["A", "B"], legs)

    assert order == ("B", "A")
    assert (car_min, walk_min, source) == (7, 42, "road")


def test_an_estimated_leg_marks_the_whole_route_as_an_estimate() -> None:
    legs = {(CLIENT, "A"): Leg(10, 60, "straight")}

    assert best_route(["A"], legs)[3] == "straight"


def test_missing_items_say_why() -> None:
    boxes = [Box("a-concor", "concor", "A", 600_000, 1)]
    basket = [
        CONCOR,  # 2 wanted, 1 exists
        ASPIRIN,  # nothing listed
        BasketItem("glucophage", 1, reason_if_none="expires_too_early"),
    ]

    plan = plan_basket(basket, boxes, LEGS)[0]

    assert [(m.item_key, m.qty_missing, m.reason) for m in plan.missing] == [
        ("concor", 1, "not_enough"),
        ("aspirin", 1, "none_listed"),
        ("glucophage", 1, "expires_too_early"),
    ]


def test_nothing_usable_gives_no_plan() -> None:
    assert plan_basket([CONCOR], [], LEGS) == []
    assert plan_basket([CONCOR], [Box("a-concor", "concor", "A", 1, 0)], LEGS) == []


def test_every_plan_covers_as_much_as_the_best_one() -> None:
    """A plan that leaves out a medicine another plan can get is not offered."""
    boxes = [
        Box("a-concor", "concor", "A", 600_000, 5),
        Box("c-aspirin", "aspirin", "C", 100_000, 5),
    ]

    plans = plan_basket([CONCOR, ASPIRIN], boxes, LEGS)

    assert len(plans) == 1
    assert plans[0].units == 3
    assert [stop.pharmacy_id for stop in plans[0].stops] == ["A", "C"]


def test_at_most_max_plans_are_returned_and_the_result_is_repeatable() -> None:
    boxes = [Box(f"{p}-concor", "concor", p, 500_000, 5) for p in ("A", "B", "C")]

    assert len(plan_basket([CONCOR], boxes, LEGS, max_plans=2)) == 2
    assert plan_basket([CONCOR], boxes, LEGS) == plan_basket([CONCOR], list(reversed(boxes)), LEGS)


def test_a_far_but_cheapest_pharmacy_is_still_weighed_when_there_are_very_many() -> None:
    pharmacies = [f"P{n:02d}" for n in range(30)]
    legs = {(CLIENT, p): Leg(n + 1, 6 * (n + 1)) for n, p in enumerate(pharmacies)}
    legs.update({(a, b): Leg(5, 30) for a in pharmacies for b in pharmacies if a != b})
    boxes = [Box(f"{p}-concor", "concor", p, 500_000, 5) for p in pharmacies[:-1]]
    boxes.append(Box("P29-concor", "concor", "P29", 100_000, 5))  # the furthest, and the cheapest

    nearest = plan_basket([CONCOR], boxes, legs)[0]
    cheapest = plan_basket([CONCOR], boxes, legs, preference="cheapest")[0]

    assert nearest.stops[0].pharmacy_id == "P00"
    assert cheapest.stops[0].pharmacy_id == "P29"


def brute_force_best(
    items: list[BasketItem], boxes: list[Box], legs: dict[tuple[str, str], Leg]
) -> tuple[int, int, int, int]:
    """The best `(units, car minutes, pharmacies, price)` by trying every way to fill the basket.

    Written independently of the planner: it tries every quantity from every box.
    """
    per_item: list[list[list[tuple[Box, int]]]] = []
    for item in items:
        item_boxes = [box for box in boxes if box.item_key == item.key]
        ways = []
        for amounts in product(*[range(min(box.available, item.qty) + 1) for box in item_boxes]):
            if sum(amounts) <= item.qty:
                ways.append(
                    [(box, qty) for box, qty in zip(item_boxes, amounts, strict=True) if qty]
                )
        per_item.append(ways)

    best: tuple[int, int, int, int] | None = None
    for choice in product(*per_item):
        picks = [pick for way in choice for pick in way]
        if not picks:
            continue
        units = sum(qty for _, qty in picks)
        price = sum(box.price_lbp * qty for box, qty in picks)
        visited = sorted({box.pharmacy_id for box, _ in picks})
        car_min = min(
            sum(
                legs[(start, end)].car_min
                for start, end in zip((CLIENT, *order), order, strict=False)
            )
            for order in permutations(visited)
        )
        # More units first; then the order of R-RQ5.
        rank = (-units, car_min, len(visited), price)
        if best is None or rank < (-best[0], best[1], best[2], best[3]):
            best = (units, car_min, len(visited), price)
    assert best is not None
    return best


def test_the_first_plan_matches_a_brute_force_search_on_random_baskets() -> None:
    """Pharmacies sit on a street grid, so a detour never shortens a trip, as on real roads."""
    numbers = random.Random(2026)
    pharmacies = ["A", "B", "C", "D"]
    compared = 0
    for _ in range(300):
        places = {CLIENT: (0, 0)} | {
            p: (numbers.randrange(-9, 10), numbers.randrange(-9, 10)) for p in pharmacies
        }
        legs = {
            (a, b): Leg(abs(xa - xb) + abs(ya - yb), 0)
            for a, (xa, ya) in places.items()
            for b, (xb, yb) in places.items()
            if a != b and b != CLIENT
        }
        items = [
            BasketItem(f"item-{n}", numbers.randrange(1, 3)) for n in range(numbers.randrange(1, 4))
        ]
        boxes = [
            Box(
                f"{p}-{item.key}",
                item.key,
                p,
                numbers.randrange(1, 9) * 100_000,
                numbers.randrange(1, 3),
            )
            for item in items
            for p in numbers.sample(pharmacies, numbers.randrange(0, 4))
        ]
        if not boxes:
            continue

        plan = plan_basket(items, boxes, legs)[0]

        found = (plan.units, plan.total_car_min, plan.pharmacies_count, plan.total_lbp)
        assert found == brute_force_best(items, boxes, legs)
        compared += 1
    assert compared > 250


def test_with_irregular_travel_times_the_first_plan_still_covers_the_most_units() -> None:
    """Real road times can be irregular (one-way streets, rounding).

    The planner then finds the quickest plan almost always (measured: 98% of baskets with times
    bent by up to 30%, and about 2 minutes longer otherwise). Whatever the times are, it never
    covers fewer units than the best possible plan.
    """
    numbers = random.Random(99)
    pharmacies = ["A", "B", "C", "D"]
    same_trip = compared = 0
    for _ in range(400):
        legs = {(CLIENT, p): Leg(numbers.randrange(1, 30), 0) for p in pharmacies}
        legs.update(
            {
                (a, b): Leg(numbers.randrange(1, 30), 0)
                for a in pharmacies
                for b in pharmacies
                if a != b
            }
        )
        items = [
            BasketItem(f"item-{n}", numbers.randrange(1, 3)) for n in range(numbers.randrange(1, 4))
        ]
        boxes = [
            Box(
                f"{p}-{i.key}", i.key, p, numbers.randrange(1, 9) * 100_000, numbers.randrange(1, 3)
            )
            for i in items
            for p in numbers.sample(pharmacies, numbers.randrange(0, 4))
        ]
        if not boxes:
            continue

        plan = plan_basket(items, boxes, legs)[0]
        best_units, best_car_min, _, _ = brute_force_best(items, boxes, legs)

        assert plan.units == best_units
        compared += 1
        same_trip += plan.total_car_min == best_car_min
    assert same_trip / compared > 0.85
