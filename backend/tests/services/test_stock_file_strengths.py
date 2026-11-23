"""How a stock file's strength is compared with the catalog's (docs/04 R-C9, R-U5).

A strength keeps its decimal point: 2.5 mg is never 25 mg. Capitals, spaces and the other
signs still don't matter, a comma written as the decimal point is read as one, and a
comma that groups thousands is ignored, as the Ministry writes them. Invented products
only; no database.
"""

import uuid

import pytest

from dawalink.db.models import Product
from dawalink.services.inventory import _choice, _match_product, _strength_key


def _product(strength: str, code: int) -> Product:
    return Product(
        id=uuid.uuid4(),
        moph_name="EXAMPLE DROPS",
        search_name="example drops",
        dosage_text=strength,
        moph_code=code,
        controlled=False,
        form_text="Solution",
        presentation_text="10ml",
        manufacturer="Example Labs",
    )


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("2.5mg", "2.5 mg"),
        ("2,5 mg", "2.5mg"),  # a spreadsheet set to French
        ("2.5 MG", "2.5mg"),
        ("2.50mg", "2.5mg"),
        (".5mg", "0.5mg"),
        ("5mg/5ml", "5 mg / 5 ml"),
        ("5 mg/ml", "5mg/ml"),
        ("100000IU", "100,000IU"),  # the Ministry groups thousands with a comma
        ("1,000 mg", "1000mg"),
        ("0.45%", "0.45 %"),
    ],
)
def test_the_same_strength_written_another_way(typed: str, stored: str) -> None:
    assert _strength_key(typed) == _strength_key(stored)


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("2.5mg", "25mg"),
        ("2,5mg", "25mg"),
        ("0.5mg", "5mg"),
        (".5mg", "5mg"),
        ("1/25", "12/5"),  # two numbers stay two numbers
        ("2.5mg", "2.5mcg"),
    ],
)
def test_another_strength(typed: str, stored: str) -> None:
    assert _strength_key(typed) != _strength_key(stored)


def test_a_row_for_two_and_a_half_mg_takes_the_two_and_a_half_mg_product() -> None:
    """Before, both strengths lost their point and compared as "25mg": the row was
    refused with "add the strength", although it had one."""
    small, large = _product("2.5mg", 1001), _product("25mg", 1002)

    for typed in ("2.5mg", "2,5 mg", "2.5 MG"):
        assert _match_product([small, large], typed) == (small, {})
    assert _match_product([small, large], "25 mg") == (large, {})


def test_a_choice_says_a_bare_pack_number_as_a_pack() -> None:
    """The upload screen and the errors file list the choices of a name listed several
    times: "Tablet 30" read as a form; "Tablet Pack: 30" is a pack."""
    counted, measured = _product("2.5mg", 1001), _product("2.5mg", 1002)
    counted.form_text, counted.presentation_text = "Tablet", "30"

    assert _choice(counted) == "Tablet Pack: 30, Example Labs: code 1001"
    assert _choice(measured) == "Solution 10ml, Example Labs: code 1002"


def test_a_strength_no_product_has_is_still_a_slip_when_the_name_is_enough() -> None:
    """Unchanged: with one product of that name, a wrong strength is taken as a slip of
    the pen; with a code it contradicts the code, and the row is refused."""
    only = _product("2.5mg", 1001)

    assert _match_product([only], "25mg") == (only, {})
    found, problem = _match_product([only], "25mg", "1001")
    assert found is None
    assert "check both" in problem["problem"]
