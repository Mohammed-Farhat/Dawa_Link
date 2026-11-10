"""Client limits and the no-show rule (docs/04 R-L, R-N1, INV-3)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dawalink.domain.numbers import (
    MAX_OPEN_ORDERS,
    MAX_UNITS_PER_GROUP,
    NO_SHOW_PAUSE,
    NO_SHOW_WINDOW,
    NO_SHOWS_BEFORE_PAUSE,
)


class LimitReached(StrEnum):
    OPEN_ORDERS = "LIMIT_OPEN_ORDERS"
    GROUP_UNITS = "LIMIT_GROUP_UNITS"


@dataclass(frozen=True)
class OpenOrder:
    """One of a client's open orders, as the limits see it."""

    equivalence_group: str
    units: int
    # Set for an offer made to a claim. A claim's simultaneous offers count once (R-W3).
    offer_for_claim: str | None = None


@dataclass(frozen=True)
class OpenOrderLoad:
    orders: int
    units_by_group: dict[str, int]


def open_order_load(open_orders: Sequence[OpenOrder]) -> OpenOrderLoad:
    """How much of the limits a client's open orders use.

    Two offers for the same claim are one need: only one can be accepted, so together they
    count as one order, with the larger of their unit counts.
    """
    orders = 0
    units_by_group: dict[str, int] = {}
    offers: dict[str, OpenOrder] = {}
    for order in open_orders:
        if order.offer_for_claim is None:
            orders += 1
            _add(units_by_group, order.equivalence_group, order.units)
            continue
        seen = offers.get(order.offer_for_claim)
        if seen is None or order.units > seen.units:
            offers[order.offer_for_claim] = order
    for offer in offers.values():
        orders += 1
        _add(units_by_group, offer.equivalence_group, offer.units)
    return OpenOrderLoad(orders, units_by_group)


def _add(units_by_group: dict[str, int], group: str, units: int) -> None:
    units_by_group[group] = units_by_group.get(group, 0) + units


def limit_reached_by(
    load: OpenOrderLoad, new_orders: Sequence[tuple[str, int]]
) -> LimitReached | None:
    """Would adding these `(equivalence group, units)` orders break a limit (R-L1, R-L2)?"""
    if load.orders + len(new_orders) > MAX_OPEN_ORDERS:
        return LimitReached.OPEN_ORDERS
    units = dict(load.units_by_group)
    for group, new_units in new_orders:
        _add(units, group, new_units)
        if units[group] > MAX_UNITS_PER_GROUP:
            return LimitReached.GROUP_UNITS
    return None


def pause_after_no_show(
    counted_no_shows: Sequence[datetime], now: datetime, paused_until: datetime | None
) -> datetime | None:
    """The new `paused_until` after a no-show at `now`, or None if the client isn't paused (R-N1).

    `counted_no_shows` are the times of the client's counted no-shows, this one included.
    Two in a rolling 30 days pause the client for 7 days; each later one adds 7 more.
    """
    recent = [moment for moment in counted_no_shows if now - moment < NO_SHOW_WINDOW]
    if len(recent) < NO_SHOWS_BEFORE_PAUSE:
        return paused_until if paused_until and paused_until > now else None
    already_paused_until = paused_until if paused_until and paused_until > now else now
    return already_paused_until + NO_SHOW_PAUSE
