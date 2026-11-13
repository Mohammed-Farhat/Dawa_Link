"""Locations and the straight-line estimate (docs/04 R-S2, R-RT1, N-43, N-50)."""

from decimal import Decimal

import pytest

from dawalink.domain.geo import Point, cell, estimate, rounded, straight_line_km

HAMRA = Point(Decimal("33.896"), Decimal("35.483"))
TRIPOLI = Point(Decimal("34.437"), Decimal("35.850"))


def test_a_location_is_rounded_to_about_100_metres() -> None:
    """N-43: three decimals, so the exact address never enters the system."""
    point = rounded(33.89612345, "35.48298765")

    assert point == Point(Decimal("33.896"), Decimal("35.483"))
    assert cell(point) == "33.896,35.483"


def test_two_people_in_the_same_block_share_a_cache_key() -> None:
    assert cell(rounded(33.89612, 35.48301)) == cell(rounded(33.89588, 35.48349))


@pytest.mark.parametrize(("lat", "lon"), [(91, 35), (33, 181), (-91, 0)])
def test_a_place_must_be_on_earth(lat: float, lon: float) -> None:
    with pytest.raises(ValueError, match="Earth"):
        rounded(lat, lon)


def test_the_straight_line_between_beirut_and_tripoli_is_about_69_km() -> None:
    assert straight_line_km(HAMRA, TRIPOLI) == pytest.approx(69, abs=2)
    assert straight_line_km(HAMRA, HAMRA) == 0


def test_the_estimate_is_labelled_and_never_zero() -> None:
    """R-RT1: an estimate is shown as "about", and even next door takes a minute."""
    far = estimate(HAMRA, TRIPOLI)
    here = estimate(HAMRA, HAMRA)

    assert far.source == here.source == "straight"
    assert (here.car_min, here.walk_min, here.km) == (1, 1, 0.0)
    # About 97 km by road at 30 km/h, and at walking pace.
    assert far.km == pytest.approx(97, abs=3)
    assert far.car_min == pytest.approx(194, abs=6)
    assert far.walk_min > far.car_min * 6
