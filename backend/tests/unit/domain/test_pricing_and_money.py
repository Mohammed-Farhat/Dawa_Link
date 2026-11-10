"""Prices and currency (docs/04 SM-3, R-PR, R-C3, INV-5)."""

import random
from decimal import Decimal

import pytest

from dawalink.domain.money import to_lbp, usd_approx
from dawalink.domain.pricing import (
    discount_shown_pct,
    early_release_suggested_price_lbp,
    effective_price_lbp,
    is_valid_override,
    policy_price_lbp,
    tier_discount_pct,
)

PUBLIC = 895_500


@pytest.mark.parametrize(
    ("days", "discount"),
    [(0, 60), (30, 60), (31, 40), (90, 40), (91, 25), (180, 25), (181, None), (-1, None)],
)
def test_discount_tier_boundaries(days: int, discount: int | None) -> None:
    assert tier_discount_pct(days) == discount


def test_the_policy_price_is_rounded_down_to_a_thousand() -> None:
    # 895,500 less 25% is 671,625.
    assert policy_price_lbp(PUBLIC, 120) == 671_000
    # less 40% is 537,300; less 60% is 358,200.
    assert policy_price_lbp(PUBLIC, 60) == 537_000
    assert policy_price_lbp(PUBLIC, 10) == 358_000


def test_there_is_no_policy_price_outside_the_published_window() -> None:
    assert policy_price_lbp(PUBLIC, 181) is None
    assert policy_price_lbp(PUBLIC, -1) is None


def test_a_tiny_price_never_goes_below_zero() -> None:
    assert policy_price_lbp(900, 10) == 0


def test_an_override_replaces_the_policy_price() -> None:
    assert effective_price_lbp(PUBLIC, 500_000, 120) == 500_000
    assert effective_price_lbp(PUBLIC, 0, 120) == 0  # a donation
    assert effective_price_lbp(PUBLIC, None, 120) == 671_000


def test_an_old_override_never_exceeds_a_lower_new_public_price() -> None:
    assert effective_price_lbp(400_000, 500_000, 120) == 400_000


@pytest.mark.parametrize(
    ("override", "valid"), [(0, True), (PUBLIC, True), (PUBLIC + 1, False), (-1, False)]
)
def test_an_override_must_be_between_zero_and_the_public_price(override: int, valid: bool) -> None:
    assert is_valid_override(override, PUBLIC) is valid


def test_the_early_release_suggestion_is_the_mildest_tier() -> None:
    assert early_release_suggested_price_lbp(PUBLIC) == 671_000


def test_the_saving_shown_is_a_whole_percentage() -> None:
    assert discount_shown_pct(1_000_000, 750_000) == 25
    assert discount_shown_pct(PUBLIC, 671_000) == 25
    assert discount_shown_pct(PUBLIC, 0) == 100
    assert discount_shown_pct(0, 0) == 0


def test_the_price_is_always_between_zero_and_the_public_price() -> None:
    """INV-5, over many random prices, overrides and days."""
    numbers = random.Random(5)
    for _ in range(2_000):
        public = numbers.randrange(0, 5_000_000)
        override = numbers.choice([None, numbers.randrange(0, 6_000_000)])
        price = effective_price_lbp(public, override, numbers.randrange(0, 181))

        assert price is not None
        assert 0 <= price <= public


def test_usd_is_shown_to_two_decimals() -> None:
    assert usd_approx(716_000, 89_500) == 8.0
    assert usd_approx(671_000, 89_500) == 7.5
    assert usd_approx(0, 89_500) == 0.0


def test_a_budget_in_either_currency_becomes_whole_lbp() -> None:
    assert to_lbp(10, "USD", 89_500) == 895_000
    assert to_lbp(Decimal("7.5"), "USD", 89_500) == 671_250
    assert to_lbp("900000", "LBP", 89_500) == 900_000


def test_negative_amounts_and_bad_rates_are_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        to_lbp(-1, "USD", 89_500)
    with pytest.raises(ValueError, match="rate"):
        usd_approx(1_000, 0)
