"""How search results are ordered and how availability is shown (docs/04 R-S3, R-S5)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from dawalink.domain.numbers import MAX_AVAILABILITY_SHOWN

Sort = Literal["best", "nearest", "cheapest", "latest_expiry"]


@dataclass(frozen=True)
class Ranked:
    """What ordering needs to know about one option. The boxes here already fit (R-F1)."""

    listing_id: str
    car_min: int
    walk_min: int
    km: float
    price_lbp: int
    expiry_date: date


def sort_options(
    options: Sequence[Ranked], sort: Sort = "best", *, on_foot: bool = False
) -> list[Ranked]:
    """Order options for a client. Every sort ends with the listing ID, so it's repeatable.

    - best: shortest trip (by car, or on foot when the client walks), then price, then
      the soonest expiry;
    - nearest: distance; cheapest: price; latest_expiry: the box that lasts longest.
    """

    def key(option: Ranked) -> tuple[float, float, float, str]:
        trip = option.walk_min if on_foot else option.car_min
        expiry = option.expiry_date.toordinal()
        if sort == "nearest":
            return (option.km, trip, option.price_lbp, option.listing_id)
        if sort == "cheapest":
            return (option.price_lbp, trip, expiry, option.listing_id)
        if sort == "latest_expiry":
            return (-expiry, trip, option.price_lbp, option.listing_id)
        return (trip, option.price_lbp, expiry, option.listing_id)

    return sorted(options, key=key)


def availability_shown(qty_available: int) -> tuple[int, bool]:
    """Exact up to 5, then "5+": `(number to show, whether there's more)`.

    Exact stock levels beyond that would let anyone map a pharmacy's stock.
    """
    return min(qty_available, MAX_AVAILABILITY_SHOWN), qty_available > MAX_AVAILABILITY_SHOWN
