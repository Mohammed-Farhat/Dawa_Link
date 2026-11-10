"""First come, first served, and search ordering (docs/04 R-PRI, R-S3, R-S5, INV-17)."""

import random
from datetime import date, timedelta

import pytest

from dawalink.domain.allocation import WaitingClaim, allocate
from dawalink.domain.search import Ranked, availability_shown, sort_options
from tests.unit.domain.helpers import TODAY, beirut_at

TEN = beirut_at(TODAY, "10:00")
MINUTE = timedelta(minutes=1)


def claim(
    claim_id: str, minutes_after_ten: int, qty: int = 1, skip: str | None = None
) -> WaitingClaim:
    return WaitingClaim(claim_id, TEN + minutes_after_ten * MINUTE, qty, skip)


class TestFirstComeFirstServed:
    def test_the_claim_that_waited_longest_gets_the_only_unit(self) -> None:
        result = allocate(1, [claim("late", 30), claim("early", 2), claim("middle", 10)])

        assert [(hold.claim_id, hold.units) for hold in result.holds] == [("early", 1)]
        assert result.holds[0].reason == "first come, first served: waiting since 10:02"
        assert result.units_left == 0

    def test_each_claim_gets_its_missing_units_while_stock_remains(self) -> None:
        result = allocate(4, [claim("a", 1, qty=2), claim("b", 2, qty=3), claim("c", 3, qty=1)])

        assert [(hold.claim_id, hold.units) for hold in result.holds] == [("a", 2), ("b", 2)]

    def test_leftover_stock_is_reported(self) -> None:
        result = allocate(5, [claim("a", 1, qty=2)])

        assert result.units_left == 3

    def test_a_tie_on_time_is_broken_by_the_claim_id(self) -> None:
        result = allocate(1, [claim("claim-b", 5), claim("claim-a", 5)])

        assert result.holds[0].claim_id == "claim-a"

    def test_a_paused_client_or_one_at_a_limit_is_skipped_and_the_next_gets_it(self) -> None:
        """R-PRI3."""
        result = allocate(1, [claim("paused", 1, skip="client paused"), claim("next", 2)])

        assert [hold.claim_id for hold in result.holds] == ["next"]
        assert [(skip.claim_id, skip.reason) for skip in result.skipped] == [
            ("paused", "client paused")
        ]

    def test_nothing_is_allocated_without_stock(self) -> None:
        result = allocate(0, [claim("a", 1)])

        assert result.holds == ()
        assert result.skipped == ()

    def test_no_claims_leaves_the_stock_untouched(self) -> None:
        assert allocate(3, []).units_left == 3

    def test_negative_stock_is_refused(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            allocate(-1, [])

    def test_the_same_claims_always_give_the_same_allocation(self) -> None:
        """INV-17: the order the claims arrive in, and repeating the run, change nothing."""
        numbers = random.Random(11)
        claims = [
            claim(f"claim-{n:02d}", numbers.randrange(0, 20), qty=numbers.randrange(1, 4))
            for n in range(30)
        ]
        expected = allocate(17, claims)

        for _ in range(50):
            shuffled = claims[:]
            numbers.shuffle(shuffled)
            assert allocate(17, shuffled) == expected

    def test_no_claim_is_ever_served_before_one_that_waited_longer(self) -> None:
        numbers = random.Random(3)
        claims = [claim(f"claim-{n:02d}", numbers.randrange(0, 60)) for n in range(40)]

        result = allocate(10, claims)

        served = {hold.claim_id for hold in result.holds}
        last_served = max(c.created_at for c in claims if c.claim_id in served)
        first_unserved = min(c.created_at for c in claims if c.claim_id not in served)
        assert last_served <= first_unserved


def option(listing_id: str, car: int, walk: int, km: float, price: int, expiry: date) -> Ranked:
    return Ranked(listing_id, car, walk, km, price, expiry)


NEAR_CHEAP = option("near-cheap", 5, 20, 1.5, 300_000, date(2026, 11, 30))
NEAR_DEAR = option("near-dear", 5, 22, 1.4, 500_000, date(2026, 12, 31))
FAR_CHEAPEST = option("far-cheapest", 25, 90, 9.0, 100_000, date(2027, 1, 31))
OPTIONS = [FAR_CHEAPEST, NEAR_DEAR, NEAR_CHEAP]


def ids(options: list[Ranked]) -> list[str]:
    return [o.listing_id for o in options]


class TestSearchOrder:
    def test_best_match_is_the_shortest_trip_then_the_price(self) -> None:
        assert ids(sort_options(OPTIONS)) == ["near-cheap", "near-dear", "far-cheapest"]

    def test_a_client_on_foot_is_ranked_by_walking_time(self) -> None:
        by_car = option("quick-by-car", 4, 60, 3.0, 300_000, date(2026, 11, 30))
        on_foot = option("quick-on-foot", 9, 12, 0.9, 300_000, date(2026, 11, 30))

        assert ids(sort_options([by_car, on_foot]))[0] == "quick-by-car"
        assert ids(sort_options([by_car, on_foot], on_foot=True))[0] == "quick-on-foot"

    def test_the_other_sorts(self) -> None:
        assert ids(sort_options(OPTIONS, "nearest"))[0] == "near-dear"
        assert ids(sort_options(OPTIONS, "cheapest"))[0] == "far-cheapest"
        assert ids(sort_options(OPTIONS, "latest_expiry"))[0] == "far-cheapest"

    def test_equal_options_keep_a_fixed_order(self) -> None:
        twins = [option("b", 5, 20, 1.0, 1, TODAY), option("a", 5, 20, 1.0, 1, TODAY)]

        assert ids(sort_options(twins)) == ["a", "b"]
        assert ids(sort_options(list(reversed(twins)))) == ["a", "b"]


@pytest.mark.parametrize(
    ("qty", "shown"), [(1, (1, False)), (5, (5, False)), (6, (5, True)), (40, (5, True))]
)
def test_availability_is_exact_up_to_five_then_five_plus(qty: int, shown: tuple[int, bool]) -> None:
    assert availability_shown(qty) == shown


def test_a_claim_that_misses_nothing_takes_nothing() -> None:
    result = allocate(1, [claim("covered", 1, qty=0), claim("waiting", 2)])

    assert [hold.claim_id for hold in result.holds] == ["waiting"]
