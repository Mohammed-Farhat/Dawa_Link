"""The P-set: 50 baskets with their best plans (docs/08 §2.5).

Three things are checked: the planner gives the expected plans for every basket; a planner
with a known mistake fails the set; and the answer key itself is right on baskets small
enough to work out by hand.
"""

from collections import Counter
from typing import Any

import pytest

from dawalink.domain import planning
from dawalink.evals import build_plan_set, plan_oracle
from dawalink.evals.plan_set import ORDERS, PLANS_FILE, PBox, PCase, PItem, check, read_cases
from dawalink.sim import travel_table
from dawalink.sim.world import load

CASES = read_cases()


def basket(
    items: dict[str, int], boxes: list[tuple[str, str, int, int]], minutes: dict[str, int]
) -> PCase:
    """A basket on one straight road: every pharmacy is `minutes` from the client by car,
    ten times that on foot, and the pharmacies are as far apart as their difference."""
    places = sorted(minutes)
    legs = [("client", place, minutes[place], 10 * minutes[place]) for place in places]
    legs += [
        (a, b, abs(minutes[a] - minutes[b]), 10 * abs(minutes[a] - minutes[b]))
        for a in places
        for b in places
        if a != b
    ]
    return PCase(
        id="P-9999",
        shape="by hand",
        client=1,
        items=[PItem(key=key, qty=qty) for key, qty in items.items()],
        boxes=[
            PBox(
                id=f"{pharmacy}-{item}", item=item, pharmacy=pharmacy, price_lbp=price, available=n
            )
            for pharmacy, item, price, n in boxes
        ],
        legs=legs,
        expected={},
    )


def ranks(case: PCase, order: Any = "nearest") -> list[tuple[list[str], int, int, int, int]]:
    return [
        (plan.pharmacies, plan.units, plan.minutes, plan.stops, plan.lbp)
        for plan in plan_oracle.best_plans(case, order)
    ]


class TestThePlannerOnTheSet:
    def test_the_set_is_50_baskets_ten_of_each_shape(self) -> None:
        assert len(CASES) == 50
        assert Counter(case.shape for case in CASES) == dict.fromkeys(build_plan_set.SHAPES, 10)

    @pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
    def test_the_planner_gives_the_expected_plans_in_every_order(self, case: PCase) -> None:
        assert check(case) == []

    def test_a_planner_that_ignores_the_preference_fails_the_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The known-bad case: the set must notice a planner that orders everything alike."""
        by_default = planning._order
        monkeypatch.setattr(planning, "_order", lambda plan, preference: by_default(plan, None))

        failed = {line.split()[1].rstrip(":") for case in CASES for line in check(case)}

        assert failed == {"fewest_trips", "cheapest", "walkable"}

    def test_a_planner_that_visits_in_any_order_fails_the_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Another known mistake: the route isn't the shortest one (R-RT2)."""
        shortest = planning.best_route

        def alphabetical(pharmacies: Any, legs: Any, on_foot: bool = False) -> Any:
            order = tuple(sorted(pharmacies))
            route = [legs[leg] for leg in zip(("client", *order), order, strict=False)]
            _, _, _, source = shortest(pharmacies, legs, on_foot)
            car_min = sum(leg.car_min for leg in route)
            return order, car_min, sum(leg.walk_min for leg in route), source

        monkeypatch.setattr(planning, "best_route", alphabetical)

        assert sum(bool(check(case)) for case in CASES) > 5

    def test_a_changed_expectation_is_reported(self) -> None:
        case = CASES[0]
        first = case.expected["nearest"][0]
        wrong = case.model_copy(
            update={
                "expected": case.expected
                | {"nearest": [first.model_copy(update={"lbp": first.lbp + 1})]}
            }
        )

        (line,) = check(wrong)

        assert line.startswith(f"{case.id} nearest: expected")

    def test_the_file_is_what_the_seed_gives(self) -> None:
        """The file is generated: nobody edits a basket or an answer by hand."""
        table = travel_table.read()
        assert table is not None

        rebuilt = build_plan_set.text_of(build_plan_set.build(load(), table))

        assert rebuilt == PLANS_FILE.read_text(encoding="utf-8")


ROAD = {"A": 5, "B": 8, "C": 20}


class TestTheAnswerKey:
    """`plan_oracle.py` on baskets worked out by hand. A is near, B further, C far."""

    def test_one_pharmacy_with_everything_and_a_cheaper_one_far_away(self) -> None:
        case = basket(
            {"m1": 2, "m2": 1},
            [("A", "m1", 600, 5), ("A", "m2", 100, 5), ("C", "m1", 400, 5), ("C", "m2", 80, 5)],
            ROAD,
        )

        assert ranks(case)[0] == (["A"], 3, 5, 1, 1300)
        assert ranks(case, "cheapest")[0] == (["C"], 3, 20, 1, 880)
        assert ranks(case, "walkable")[0] == (["A"], 3, 50, 1, 1300)

    def test_a_quantity_nobody_holds_alone_is_split(self) -> None:
        case = basket({"m1": 2}, [("A", "m1", 600, 1), ("B", "m1", 650, 1)], ROAD)

        assert ranks(case) == [(["A", "B"], 2, 8, 2, 1250)]

    def test_a_stop_that_buys_nothing_is_not_a_plan(self) -> None:
        """A has both medicines. B has one of them at the same price: going to both is a
        detour, and B alone covers less."""
        case = basket(
            {"m1": 1, "m2": 1},
            [("A", "m1", 500, 1), ("A", "m2", 300, 1), ("B", "m1", 500, 1)],
            ROAD,
        )

        assert ranks(case) == [(["A"], 2, 5, 1, 800)]

    def test_a_second_stop_that_saves_money_is_a_plan(self) -> None:
        case = basket(
            {"m1": 1, "m2": 1},
            [("A", "m1", 500, 1), ("A", "m2", 300, 1), ("B", "m1", 450, 1)],
            ROAD,
        )

        assert ranks(case) == [(["A"], 2, 5, 1, 800), (["A", "B"], 2, 8, 2, 750)]
        assert ranks(case, "cheapest")[0] == (["A", "B"], 2, 8, 2, 750)

    def test_fewest_trips_prefers_one_far_stop_to_two_near_ones(self) -> None:
        case = basket(
            {"m1": 1, "m2": 1},
            [("A", "m1", 500, 1), ("B", "m2", 300, 1), ("C", "m1", 500, 1), ("C", "m2", 300, 1)],
            ROAD,
        )

        assert ranks(case)[0][0] == ["A", "B"]
        assert ranks(case, "fewest_trips")[0][0] == ["C"]

    def test_a_plan_visits_four_pharmacies_at_most(self) -> None:
        road = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
        case = basket(
            dict.fromkeys(("m1", "m2", "m3", "m4", "m5"), 1),
            [(place, f"m{n}", 100, 1) for n, place in enumerate(road, start=1)],
            road,
        )

        best = ranks(case)

        assert best[0] == (["A", "B", "C", "D"], 4, 4, 4, 400)
        assert all(units == 4 and stops == 4 for _, units, _, stops, _ in best)

    def test_only_the_plans_that_cover_the_most_units_are_listed(self) -> None:
        case = basket({"m1": 2}, [("A", "m1", 600, 1), ("C", "m1", 600, 2)], ROAD)

        assert ranks(case) == [(["C"], 2, 20, 1, 1200)]

    def test_the_trip_is_the_shortest_order_from_the_client(self) -> None:
        case = basket({"m1": 1}, [("A", "m1", 1, 1)], {"A": 5, "B": 8, "C": 20})

        assert plan_oracle.trip(case, frozenset({"A", "B", "C"})) == (20, ("A", "B", "C"))

    def test_every_order_is_answered_for_every_basket_of_the_set(self) -> None:
        assert all(set(case.expected) == set(ORDERS) for case in CASES)
        assert all(case.expected[order] for case in CASES for order in ORDERS)
