"""What happens during a simulated day (docs/08 §2.4): who needs what and when, and which
new boxes reach the shelves.

A scenario depends on the seed and the world only. It never depends on a contender: the
search baseline, the no-AI policy and the agent of one seed face exactly the same needs,
in the same order, at the same times.
"""

import random
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from dawalink.domain.clock import at_beirut
from dawalink.sim.params import Params
from dawalink.sim.world import SimClient, World, numbers_for, popularity

# How many medicines a need has, and how often (docs/08 §2.4: 1 to 5).
SIZES = ((1, 35), (2, 30), (3, 20), (4, 10), (5, 5))
DAYS_OF_USE = ((1, 15), (5, 20), (7, 20), (10, 15), (14, 10), (30, 20))
PICKUP_IN_DAYS = ((0, 70), (1, 30))
# A new listing is a box that entered its last 180 days, or was just received.
NEW_BOX_DAYS_LEFT = (20, 180)

# What a client writes about themselves, from what is true for them.
Says = Literal[
    "no_car", "after_18", "before_14", "only_tomorrow", "cheapest", "nearest", "fewest_trips"
]


@dataclass(frozen=True)
class Line:
    product_id: uuid.UUID
    qty: int
    days_of_use: int
    # A budget, as a share of the medicine's public price. None: no limit.
    budget_share: float | None


@dataclass(frozen=True)
class Need:
    """One client's need for 1 to 5 medicines, the same for every contender."""

    n: int
    at: datetime
    client: SimClient
    lines: tuple[Line, ...]
    hears_other_brands: bool
    # The first day the client can go: 0 is the day of the request, 1 the day after.
    pickup_in_days: int
    says: Says | None  # written with the request
    # Written later, while the request is open: (minutes after the request, what). It is
    # another true thing about them, never a change: the client's situation is the same
    # all day and for every contender.
    later: tuple[int, Says] | None


@dataclass(frozen=True)
class Arrival:
    """A new box on a pharmacy's shelf."""

    at: datetime
    pharmacy_n: int
    product_id: uuid.UUID
    days_left: int
    units: int


@dataclass(frozen=True)
class Scenario:
    needs: tuple[Need, ...]
    arrivals: tuple[Arrival, ...]


def _pick[T](numbers: random.Random, choices: Sequence[tuple[T, int]]) -> T:
    values = [value for value, _ in choices]
    weights = [weight for _, weight in choices]
    return numbers.choices(values, weights)[0]


def what_they_say(client: SimClient, pickup_in_days: int = 0) -> list[Says]:
    """The true things this client could write about themselves."""
    true: list[Says] = []
    if not client.has_car:
        true.append("no_car")
    if client.free != "any":
        true.append(client.free)
    if pickup_in_days:
        true.append("only_tomorrow")
    if client.preference is not None:
        true.append(client.preference)  # type: ignore[arg-type]
    return true


def build(
    seed: int,
    world: World,
    demand: Sequence[uuid.UUID],
    medicine_of: Mapping[uuid.UUID, str],
    params: Params,
) -> Scenario:
    """The day of this seed. `medicine_of` gives a product's medicine (its group of brands):
    a need never asks twice for the same medicine."""
    weights = popularity(len(demand))
    opens = at_beirut(params.day, params.first_request)
    span_min = int((at_beirut(params.day, params.last_request) - opens).total_seconds() // 60)

    who = numbers_for(seed, "who").sample(world.clients, min(params.requests, len(world.clients)))
    needs = []
    for n, client in enumerate(who, start=1):
        numbers = numbers_for(seed, "need", n)
        lines: dict[str, Line] = {}
        wanted = _pick(numbers, SIZES)
        for _ in range(wanted * 6):  # a few extra draws: some repeat a medicine
            product_id = numbers.choices(demand, weights)[0]
            lines.setdefault(
                medicine_of[product_id],
                Line(
                    product_id=product_id,
                    qty=2 if numbers.random() < 0.15 else 1,
                    days_of_use=_pick(numbers, DAYS_OF_USE),
                    budget_share=(
                        round(numbers.uniform(0.6, 0.9), 2)
                        if numbers.random() < params.has_budget
                        else None
                    ),
                ),
            )
            if len(lines) == wanted:
                break
        pickup_in_days = _pick(numbers, PICKUP_IN_DAYS)
        true = what_they_say(client, pickup_in_days)
        says = numbers.choice(true) if true and numbers.random() < params.says_preference else None
        unsaid = [what for what in true if what != says]
        later: tuple[int, Says] | None = None
        if numbers.random() < params.writes_again and unsaid:
            later = (numbers.randrange(20, 91), numbers.choice(unsaid))
        needs.append(
            Need(
                n=n,
                at=opens + timedelta(minutes=numbers.randrange(0, span_min)),
                client=client,
                lines=tuple(lines.values()),
                hears_other_brands=numbers.random() < params.hears_other_brands,
                pickup_in_days=pickup_in_days,
                says=says,
                later=later,
            )
        )
    needs.sort(key=lambda need: (need.at, need.n))

    arrivals = []
    for pharmacy in world.pharmacies:
        numbers = numbers_for(seed, "arrivals", pharmacy.n)
        count = int(params.new_listings_per_pharmacy)
        count += numbers.random() < params.new_listings_per_pharmacy - count
        for _ in range(count):
            arrivals.append(
                Arrival(
                    at=opens + timedelta(minutes=numbers.randrange(0, span_min)),
                    pharmacy_n=pharmacy.n,
                    product_id=numbers.choices(demand, weights)[0],
                    days_left=numbers.randrange(*NEW_BOX_DAYS_LEFT),
                    units=numbers.randrange(1, 4),
                )
            )
    arrivals.sort(key=lambda arrival: (arrival.at, arrival.pharmacy_n))
    return Scenario(tuple(needs), tuple(arrivals))
