"""The simulated day and the client's real situation (docs/08 §2.3, §2.4). No database."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from dawalink.domain.clock import BEIRUT, at_beirut
from dawalink.sim import scenario, situation
from dawalink.sim.params import Params
from dawalink.sim.situation import Trip
from dawalink.sim.world import NAMESPACE, SimClient, SimPharmacy, World, load

PARAMS = Params()
DEMAND = tuple(uuid.uuid5(NAMESPACE, f"medicine-{n}") for n in range(120))
# Three brands of each medicine.
MEDICINE_OF = {product: f"m{n // 3}" for n, product in enumerate(DEMAND)}


def day_of(seed: int, world: World | None = None, params: Params = PARAMS) -> scenario.Scenario:
    return scenario.build(seed, world or load(), DEMAND, MEDICINE_OF, params)


class TestTheDay:
    def test_a_seed_gives_one_day_and_another_seed_another(self) -> None:
        """Pairing: the three contenders of a seed face exactly the same needs."""
        assert day_of(4) == day_of(4)
        assert day_of(4).needs != day_of(5).needs

    def test_a_hundred_needs_inside_request_hours_each_from_another_client(self) -> None:
        needs = day_of(1).needs

        opens, closes = at_beirut(PARAMS.day, time(8)), at_beirut(PARAMS.day, time(20))
        assert len(needs) == 100
        assert len({need.client.n for need in needs}) == 100
        assert all(opens <= need.at < closes for need in needs)
        assert [need.at for need in needs] == sorted(need.at for need in needs)

    def test_a_need_has_one_to_five_medicines_and_none_twice(self) -> None:
        for need in day_of(2).needs:
            medicines = [MEDICINE_OF[line.product_id] for line in need.lines]
            assert 1 <= len(need.lines) <= 5
            assert len(set(medicines)) == len(medicines), need.n
            assert all(1 <= line.qty <= 2 and line.days_of_use >= 1 for line in need.lines)

    def test_a_client_only_says_what_is_true_for_them(self) -> None:
        for need in day_of(3).needs:
            true = scenario.what_they_say(need.client, need.pickup_in_days)
            if need.says is not None:
                assert need.says in true, need.n
            if need.later is not None:
                # Written later: another true thing, never a change of situation.
                assert need.later[1] in true, need.n
                assert need.later[1] != need.says, need.n

    def test_the_shares_follow_the_assumptions(self) -> None:
        needs = [need for seed in range(1, 6) for need in day_of(seed).needs]

        wrote_again = sum(need.later is not None for need in needs) / len(needs)
        other_brands = sum(need.hears_other_brands for need in needs) / len(needs)
        assert 0.09 < wrote_again < 0.21  # 15%
        assert 0.42 < other_brands < 0.58  # 50%

    def test_new_boxes_arrive_at_every_pharmacy_during_the_day(self) -> None:
        arrivals = day_of(1).arrivals

        assert {arrival.pharmacy_n for arrival in arrivals} == set(range(1, 31))
        assert len(arrivals) == 30 * 6
        assert all(20 <= arrival.days_left < 180 for arrival in arrivals)

    def test_changing_an_assumption_changes_only_what_it_touches(self) -> None:
        """E6 sweeps one number at a time: the needs must stay the same."""
        base, swept = day_of(1), day_of(1, params=PARAMS.but(not_available=0.3))

        assert base == swept
        assert len(day_of(1, params=PARAMS.but(new_listings_per_pharmacy=3.0)).arrivals) == 90


def client(**situation_of: Any) -> SimClient:
    values: dict[str, Any] = {"has_car": True, "free": "any", "language": "english"}
    return SimClient(
        n=1, district="Beirut", lat=33.9, lon=35.5, preference=None, **(values | situation_of)
    )


def pharmacy(schedule: int) -> SimPharmacy:
    return SimPharmacy(n=1, district="Beirut", lat=33.9, lon=35.5, schedule=schedule, pickup_days=1)


MONDAY, SUNDAY = date(2026, 11, 16), date(2026, 11, 22)
NEAR = Trip(5, 20)


def at(hour: int, day: date = MONDAY) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=BEIRUT)


class TestTheRealSituation:
    def test_a_pharmacy_must_be_open_while_the_client_is_free(self) -> None:
        closes_at_17, open_late = pharmacy(4), pharmacy(2)
        after_work = client(free="after_18")

        assert not situation.can_go(after_work, closes_at_17, NEAR, MONDAY, at(9))
        assert situation.can_go(after_work, open_late, NEAR, MONDAY, at(9))
        assert situation.can_go(client(free="before_14"), closes_at_17, NEAR, MONDAY, at(9))

    def test_today_only_what_is_left_of_the_day_counts(self) -> None:
        morning_person, closes_at_17 = client(free="before_14"), pharmacy(4)

        assert situation.can_go(morning_person, closes_at_17, NEAR, MONDAY, at(10))
        assert not situation.can_go(morning_person, closes_at_17, NEAR, MONDAY, at(15))
        # Tomorrow the whole morning is there again.
        assert situation.can_go(morning_person, closes_at_17, NEAR, date(2026, 11, 17), at(15))

    def test_closed_on_sunday(self) -> None:
        assert not situation.can_go(client(), pharmacy(0), NEAR, SUNDAY, at(9, SUNDAY))
        assert situation.can_go(client(), pharmacy(2), NEAR, SUNDAY, at(9, SUNDAY))

    def test_the_trip_must_leave_time_before_the_pharmacy_closes(self) -> None:
        """Seen on a first run: a client tapped a card at 16:30 for a pharmacy 70 minutes
        away that closes at 17:00, and nobody came."""
        closes_at_17, far = pharmacy(4), Trip(70, 300)

        assert situation.can_go(client(), closes_at_17, far, MONDAY, at(15))
        assert not situation.can_go(client(), closes_at_17, far, MONDAY, at(16))
        assert situation.can_go(client(), closes_at_17, far, date(2026, 11, 17), at(16))

    def test_arriving_on_the_stroke_of_closing_is_arriving_too_late(self) -> None:
        """Seen on the agent's pilot: a client 65 minutes away tapped at 18:54 for a pharmacy
        that closes at 20:00, reached the door at 19:59, and the reservation had ended when
        they were served. A reservation ends at closing time (R-T4)."""
        closes_at_20, away = pharmacy(1), Trip(65, 300)
        tapped_at = datetime.combine(MONDAY, time(18, 54), tzinfo=BEIRUT)

        assert not situation.can_go(client(), closes_at_20, away, MONDAY, tapped_at)
        earlier = tapped_at - timedelta(minutes=1)
        served = situation.pickup_moment(client(), closes_at_20, away, MONDAY, earlier)
        assert served == datetime.combine(MONDAY, time(19, 59), tzinfo=BEIRUT)

    def test_without_a_car_a_long_walk_is_out_of_reach(self) -> None:
        on_foot, near, far = client(has_car=False), Trip(4, 20), Trip(12, 70)

        assert situation.can_reach(on_foot, near)
        assert not situation.can_reach(on_foot, far)
        assert situation.can_reach(client(), far)
        assert (far.minutes_for(on_foot), far.minutes_for(client())) == (70, 12)

    def test_it_works_only_when_both_hold(self) -> None:
        on_foot_after_work = client(has_car=False, free="after_18")

        assert situation.works(on_foot_after_work, pharmacy(2), Trip(4, 20), MONDAY, at(9))
        assert not situation.works(on_foot_after_work, pharmacy(4), Trip(4, 20), MONDAY, at(9))
        assert not situation.works(on_foot_after_work, pharmacy(2), Trip(12, 70), MONDAY, at(9))
