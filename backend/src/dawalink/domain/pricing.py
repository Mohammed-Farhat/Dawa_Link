"""Prices (docs/04 SM-3, R-PR, INV-5). Never stored: computed from the public price and days left.

All amounts are whole LBP per pack.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from dawalink.domain.numbers import (
    DISCOUNT_TIERS,
    EARLY_RELEASE_SUGGESTED_DISCOUNT_PCT,
    PRICE_STEP_LBP,
)


@dataclass(frozen=True)
class DiscountTier:
    min_days: int
    max_days: int
    discount_pct: int


DEFAULT_TIERS: tuple[DiscountTier, ...] = tuple(DiscountTier(*tier) for tier in DISCOUNT_TIERS)


def _discounted(public_price_lbp: int, discount_pct: int) -> int:
    """The price after the discount, rounded down to the price step. Integer maths only."""
    exact = public_price_lbp * (100 - discount_pct) // 100
    return exact // PRICE_STEP_LBP * PRICE_STEP_LBP


def tier_discount_pct(days_left: int, tiers: Sequence[DiscountTier] = DEFAULT_TIERS) -> int | None:
    """The system discount for this many days left, or None outside the published window."""
    for tier in tiers:
        if tier.min_days <= days_left <= tier.max_days:
            return tier.discount_pct
    return None


def policy_price_lbp(
    public_price_lbp: int, days_left: int, tiers: Sequence[DiscountTier] = DEFAULT_TIERS
) -> int | None:
    discount_pct = tier_discount_pct(days_left, tiers)
    if discount_pct is None:
        return None
    return _discounted(public_price_lbp, discount_pct)


def is_valid_override(override_lbp: int, public_price_lbp: int) -> bool:
    """A pharmacy's own price: from 0 (a donation) up to the public price (R-PR1)."""
    return 0 <= override_lbp <= public_price_lbp


def effective_price_lbp(
    public_price_lbp: int,
    override_lbp: int | None,
    days_left: int,
    tiers: Sequence[DiscountTier] = DEFAULT_TIERS,
) -> int | None:
    """What the client pays: the pharmacy's override if set, otherwise the policy price.

    Never above the public price, even if an old override is higher than a new public price (R-C8).
    """
    if override_lbp is not None:
        return min(max(override_lbp, 0), public_price_lbp)
    return policy_price_lbp(public_price_lbp, days_left, tiers)


def early_release_suggested_price_lbp(public_price_lbp: int) -> int:
    """What we suggest a pharmacy charges when it releases private stock (R-PR3)."""
    return _discounted(public_price_lbp, EARLY_RELEASE_SUGGESTED_DISCOUNT_PCT)


def discount_shown_pct(public_price_lbp: int, price_lbp: int) -> int:
    """The saving to show next to a price, as a whole percentage."""
    if public_price_lbp <= 0:
        return 0
    return round((public_price_lbp - price_lbp) * 100 / public_price_lbp)
