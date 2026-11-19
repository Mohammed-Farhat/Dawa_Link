"""Stock quantities and listing visibility (docs/04 SM-3, INV-1, INV-16)."""

from dataclasses import dataclass
from enum import StrEnum

from dawalink.domain.accounts import PharmacyStatus
from dawalink.domain.expiry import Zone


class ListingControl(StrEnum):
    """What the pharmacy decided for one box (SM-3).

    - `LIVE`: it follows the pharmacy's own rule: listed by itself once it has the
      pharmacy's number of days left, or fewer (N-54).
    - `LISTED`: the pharmacy listed this box by hand, whatever its rule says.
    - `PAUSED`: the pharmacy took it off the listings.
    """

    LIVE = "LIVE"
    LISTED = "LISTED"
    PAUSED = "PAUSED"


class NotEnoughStock(Exception):
    def __init__(self, asked: int, available: int) -> None:
        super().__init__(f"Asked for {asked} units, {available} available.")
        self.asked = asked
        self.available = available


def is_listed(*, control: ListingControl, days_left: int, auto_list_days: int) -> bool:
    """Whether the pharmacy has this box on its listings: by its own rule, or by hand.

    `auto_list_days` is the pharmacy's choice (N-54): 0 means it lists nothing by itself.
    """
    if control is ListingControl.LISTED:
        return True
    return control is ListingControl.LIVE and auto_list_days > 0 and days_left <= auto_list_days


def is_held_back(
    *, zone: Zone, control: ListingControl, days_left: int, auto_list_days: int
) -> bool:
    """A box that could be listed today and isn't, because the pharmacy's own rule waits
    for it to be nearer its expiry. [List now] lists it; the agent may ask for it (R-E2).
    A paused box is not held back: the pharmacy took it off on purpose."""
    return (
        zone is Zone.NEAR_EXPIRY
        and control is ListingControl.LIVE
        and not is_listed(control=control, days_left=days_left, auto_list_days=auto_list_days)
    )


def is_visible(
    *,
    zone: Zone,
    control: ListingControl,
    days_left: int,
    auto_list_days: int,
    pharmacy_status: PharmacyStatus,
    qty_available: int,
    controlled: bool,
) -> bool:
    """The only definition of "visible to clients" (INV-16).

    A box is never visible with more than 180 days left (N-1), whatever the pharmacy
    chose: inside that, the pharmacy decides (the owner, 2026-11-19, BLD-D44).
    """
    return (
        zone is Zone.NEAR_EXPIRY
        and is_listed(control=control, days_left=days_left, auto_list_days=auto_list_days)
        and pharmacy_status is PharmacyStatus.APPROVED
        and qty_available >= 1
        and not controlled
    )


@dataclass(frozen=True)
class Stock:
    """One inventory item's quantities, in units. Always `0 <= reserved <= on_hand` (INV-1)."""

    on_hand: int
    reserved: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.reserved <= self.on_hand:
            raise ValueError("Stock must keep 0 <= reserved <= on hand.")

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved

    def reserve(self, units: int) -> "Stock":
        """Hold units for an order or an offer."""
        _at_least_one(units)
        if units > self.available:
            raise NotEnoughStock(units, self.available)
        return Stock(self.on_hand, self.reserved + units)

    def release(self, units: int) -> "Stock":
        """Give held units back: a cancel, a no-show, an offer that ended."""
        _at_least_one(units)
        return Stock(self.on_hand, self.reserved - units)

    def remove_reserved(self, units: int) -> "Stock":
        """Held units leave the shelf: handed to the client, or found not to be there."""
        _at_least_one(units)
        return Stock(self.on_hand - units, self.reserved - units)

    def set_on_hand(self, new_value: int) -> tuple["Stock", bool]:
        """An upload or a manual edit. Reserved units are protected (R-U3).

        Returns the new stock, and whether the value had to be raised to protect reservations.
        """
        if new_value < 0:
            raise ValueError("A quantity can't be negative.")
        protected = new_value < self.reserved
        return Stock(max(new_value, self.reserved), self.reserved), protected


def _at_least_one(units: int) -> None:
    if units < 1:
        raise ValueError("Units start at 1.")
