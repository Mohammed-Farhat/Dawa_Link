"""Client limits, no-shows and order numbers (docs/04 R-L, R-N1, INV-3; docs/05 §1)."""

import random
from datetime import datetime, timedelta

import pytest

from dawalink.domain.limits import (
    LimitReached,
    OpenOrder,
    limit_reached_by,
    open_order_load,
    pause_after_no_show,
)
from dawalink.domain.refs import ALPHABET, new_ref, normalize_ref
from tests.unit.domain.helpers import TODAY, beirut_at

NOW = beirut_at(TODAY, "21:00")
DAY = timedelta(days=1)


class TestOpenOrderLoad:
    def test_each_order_counts_with_its_units_per_medicine_group(self) -> None:
        load = open_order_load(
            [OpenOrder("bisoprolol-5", 2), OpenOrder("bisoprolol-5", 1), OpenOrder("metformin", 1)]
        )

        assert load.orders == 3
        assert load.units_by_group == {"bisoprolol-5": 3, "metformin": 1}

    def test_two_offers_for_the_same_need_count_once(self) -> None:
        """R-W3: matching and early release may both offer; only one can be accepted."""
        load = open_order_load(
            [
                OpenOrder("metformin", 1, offer_for_claim="claim-1"),
                OpenOrder("metformin", 2, offer_for_claim="claim-1"),
                OpenOrder("metformin", 1, offer_for_claim="claim-2"),
            ]
        )

        assert load.orders == 2
        assert load.units_by_group == {"metformin": 3}

    def test_no_open_orders_is_an_empty_load(self) -> None:
        assert open_order_load([]).orders == 0


class TestLimits:
    def test_the_fifth_open_order_is_allowed_and_the_sixth_is_not(self) -> None:
        four = open_order_load([OpenOrder(f"group-{n}", 1) for n in range(4)])
        five = open_order_load([OpenOrder(f"group-{n}", 1) for n in range(5)])

        assert limit_reached_by(four, [("new", 1)]) is None
        assert limit_reached_by(five, [("new", 1)]) is LimitReached.OPEN_ORDERS

    def test_three_units_of_one_medicine_group_are_allowed_and_four_are_not(self) -> None:
        load = open_order_load([OpenOrder("bisoprolol-5", 2)])

        assert limit_reached_by(load, [("bisoprolol-5", 1)]) is None
        assert limit_reached_by(load, [("bisoprolol-5", 2)]) is LimitReached.GROUP_UNITS

    def test_a_group_reserve_is_checked_as_a_whole(self) -> None:
        """R-RQ6: several orders at once, all or none."""
        load = open_order_load([OpenOrder("a", 1), OpenOrder("b", 1), OpenOrder("c", 1)])

        assert limit_reached_by(load, [("d", 1), ("e", 1)]) is None
        assert limit_reached_by(load, [("d", 1), ("e", 1), ("f", 1)]) is LimitReached.OPEN_ORDERS
        assert limit_reached_by(load, [("a", 1), ("a", 2)]) is LimitReached.GROUP_UNITS

    def test_another_brand_of_the_same_medicine_counts_in_the_same_group(self) -> None:
        """R-L2 counts per equivalence group, so brands can't be used to hoard."""
        load = open_order_load([OpenOrder("bisoprolol-5", 3)])

        assert limit_reached_by(load, [("bisoprolol-5", 1)]) is LimitReached.GROUP_UNITS
        assert limit_reached_by(load, [("bisoprolol-10", 1)]) is None


class TestNoShows:
    def test_the_first_no_show_does_not_pause(self) -> None:
        assert pause_after_no_show([NOW], NOW, None) is None

    def test_the_second_in_thirty_days_pauses_for_seven_days(self) -> None:
        assert pause_after_no_show([NOW - 10 * DAY, NOW], NOW, None) == NOW + 7 * DAY

    def test_a_no_show_older_than_thirty_days_no_longer_counts(self) -> None:
        assert pause_after_no_show([NOW - 30 * DAY, NOW], NOW, None) is None
        just_inside = NOW - 30 * DAY + timedelta(minutes=1)
        assert pause_after_no_show([just_inside, NOW], NOW, None) == NOW + 7 * DAY

    def test_a_later_no_show_while_paused_adds_seven_more_days(self) -> None:
        paused_until = NOW + 3 * DAY

        new_end = pause_after_no_show([NOW - 5 * DAY, NOW - 4 * DAY, NOW], NOW, paused_until)

        assert new_end == paused_until + 7 * DAY

    def test_a_later_no_show_after_the_pause_ended_starts_a_new_one(self) -> None:
        ended = NOW - DAY

        assert pause_after_no_show([NOW - 9 * DAY, NOW - 8 * DAY, NOW], NOW, ended) == NOW + 7 * DAY

    def test_an_unrelated_pause_is_kept(self) -> None:
        paused_until = NOW + 2 * DAY

        assert pause_after_no_show([NOW], NOW, paused_until) == paused_until


class TestRefs:
    def test_a_number_is_a_prefix_and_six_characters_without_look_alikes(self) -> None:
        for _ in range(200):
            prefix, _, body = new_ref("R").partition("-")
            assert prefix == "R"
            assert len(body) == 6
            assert set(body) <= set(ALPHABET)
        assert not set("01OI") & set(ALPHABET)

    def test_numbers_are_random(self) -> None:
        assert len({new_ref("Q") for _ in range(500)}) > 495

    def test_the_source_of_randomness_can_be_replaced(self) -> None:
        numbers = random.Random(7)

        assert new_ref("R", numbers.choice) == new_ref("R", random.Random(7).choice)

    @pytest.mark.parametrize("typed", ["R-7K3Q2F", "r7k3q2f", " r-7k3q2f ", "R 7K3 Q2F"])
    def test_case_dashes_and_spaces_do_not_matter(self, typed: str) -> None:
        assert normalize_ref(typed, "R") == "R-7K3Q2F"

    @pytest.mark.parametrize(
        "typed", ["", "7K3Q2F", "Q-7K3Q2F", "R-7K3Q2", "R-7K3Q2FF", "R-7K3Q20", "R-7K3Q2I", "R-R"]
    )
    def test_what_cannot_be_one_of_our_numbers_is_refused(self, typed: str) -> None:
        assert normalize_ref(typed, "R") is None


def test_pause_times_stay_timezone_aware() -> None:
    result = pause_after_no_show([NOW - DAY, NOW], NOW, None)

    assert isinstance(result, datetime)
    assert result.tzinfo is not None
