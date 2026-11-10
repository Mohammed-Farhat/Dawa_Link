"""LBP and USD (docs/04 R-C3): amounts are stored in whole LBP, shown in LBP and about USD."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Currency = Literal["LBP", "USD"]


def usd_approx(amount_lbp: int, lbp_per_usd: int) -> float:
    """The "≈ USD" figure shown next to an LBP amount."""
    _check_rate(lbp_per_usd)
    return float((Decimal(amount_lbp) / lbp_per_usd).quantize(Decimal("0.01"), ROUND_HALF_UP))


def to_lbp(amount: Decimal | int | str, currency: Currency, lbp_per_usd: int) -> int:
    """A budget a client gave in either currency, in whole LBP. Every check is done in LBP."""
    _check_rate(lbp_per_usd)
    value = Decimal(amount)
    if value < 0:
        raise ValueError("An amount can't be negative.")
    if currency == "USD":
        value *= lbp_per_usd
    return int(value.to_integral_value(ROUND_HALF_UP))


def _check_rate(lbp_per_usd: int) -> None:
    if lbp_per_usd <= 0:
        raise ValueError("The LBP per USD rate must be positive.")
