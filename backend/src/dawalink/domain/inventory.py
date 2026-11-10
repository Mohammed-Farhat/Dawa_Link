"""Stock quantities and listing visibility (docs/04 SM-3, INV-1, INV-16)."""

from dataclasses import dataclass
from enum import StrEnum

from dawalink.domain.accounts import PharmacyStatus
from dawalink.domain.expiry import Zone


class ListingControl(StrEnum):
    LIVE = "LIVE"
    PAUSED = "PAUSED"


class NotEnoughStock(Exception):
    def __init__(self, asked: int, available: int) -> None:
        super().__init__(f"Asked for {asked} units, {available} available.")
        self.asked = asked
        self.available = available


def is_visible(
    *,
    zone: Zone,
    control: ListingControl,
    pharmacy_status: PharmacyStatus,
    qty_available: int,
    controlled: bool,
) -> bool:
    """The only definition of "visible to clients" (INV-16)."""
    return (
        zone is Zone.NEAR_EXPIRY
        and control is ListingControl.LIVE
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
