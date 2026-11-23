"""The Ministry's no-prescription list (docs/04 R-C7). Every product and row here is invented."""

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from dawalink.catalog.moph import CatalogRow, read_catalog, write_catalog
from dawalink.catalog.otc_list import (
    OtcEntry,
    mark_otc,
    pairs_from_text,
    read_otc_list,
    write_otc_list,
)

HEADER = (
    "Brand name Strength Presentation Form Code Registration number B/G Ingredient ATC "
    "Agent Manufacturer Country Responsible Party Name Responsible Party\nCountry"
)

# Two pages of an invented list, wrapped the way a PDF's text comes out: a brand, a form, an
# ingredient or an agent over several lines, and the header again at the top of page 2.
EXTRACT = f"""Invented OTC list
Foreword: a 2018 decision, 1234 words long. Vitamin B is mentioned here, and so is 1500 G.

{HEADER}
TESTAMOL 500mg 20 Tablet 1101 54321/09 G Paracetamol - 500mg N02BE01 Some Agent
S.A.R.L. Maker Country
TESTAMOL SYRUP 120mg/5ml 100ml Suspension,
alcohol free 1102 765432/1 G Paracetamol - 120mg/5ml N02BE01
Some Agent
FIZZTEST 10 Tablet,
effervescent 1103 9876 B Vitamin C - 1g, Vitamin
B - 5mg A11GA01 Other Agent Maker Country
01/01/2018 1/2 Quality Assurance

{HEADER}
NOREG 100 Tablet 1104 B Charcoal - 200mg A07BA01 Agent
SPACED 20g Gel 1105 33333/ 07 G Something - 1% D01AC01 Agent
Ointment 1106
444444/10 B Something else - 0.1% D03AX Agent
NOFORM 30 1107 55555/12 G Something - 5mg A01AB Agent
WRAPPEDTEST
DROPS 15ml
Solution for
nasal use
1108 66666/15 B Wrapped brand and form above - 10mg R05CB Agent
01/01/2018 2/2 Quality Assurance
"""


def test_it_reads_the_code_and_registration_of_each_row() -> None:
    found = pairs_from_text(EXTRACT)

    assert found.pairs == {
        (1101, "54321/09"),
        (1102, "765432/1"),
        (1103, "9876"),
        (1108, "66666/15"),
    }


def test_each_row_keeps_its_words_before_the_code_even_when_they_wrapped() -> None:
    texts = {e.code: e.row_text for e in pairs_from_text(EXTRACT).entries}

    # The header's own wrapped last word comes along: the window is loose, never short.
    assert texts[1101] == "Country TESTAMOL 500mg 20 Tablet"
    assert texts[1103].endswith("FIZZTEST 10 Tablet, effervescent")
    assert texts[1108] == "WRAPPEDTEST DROPS 15ml Solution for nasal use"


def test_a_row_that_cant_be_read_with_certainty_is_skipped_and_counted() -> None:
    """No registration number, a space inside it, the code on the line above, or a bare
    number where the form should be: each is skipped, never repaired."""
    assert pairs_from_text(EXTRACT).skipped == 4


def test_a_code_wrapped_above_a_spaced_registration_is_not_glued_into_a_pair() -> None:
    """The row's code ends the line above; this line's "555 0000/99" is its registration number
    with a space inside. Read alone it looks like a code and a registration number."""
    text = f"{HEADER}\nLONGNAME 15ml Drops 7001\n555 0000/99 B Something - 1mg R05CB Agent\n"

    found = pairs_from_text(text)

    assert (found.pairs, found.skipped) == (frozenset(), 1)


def test_a_pair_with_no_words_before_it_is_read_but_never_marked() -> None:
    """The same two numbers right under the header: nothing says which product they are, so
    whatever the catalog holds under that pair keeps its notice."""
    found = pairs_from_text(f"{HEADER.replace(chr(10), ' ')}\n555 0000/99 B Something - 1mg\n")
    catalog_product = replace(product(555, "0000/99"), name="ANYNAME 5mg")

    marked, _ = mark_otc([catalog_product], found.entries)

    assert found.entries == (OtcEntry(555, "0000/99", ""),)
    assert marked[0].otc_listed is False


def test_a_pack_number_before_a_code_with_no_registration_is_never_marked() -> None:
    """ "999" is the pack, "9990" the code, and the registration number is missing: the text
    reads as the pair (999, "9990"). If the catalog has that pair, it belongs to another
    product, whose name this row doesn't hold, so it keeps its notice."""
    found = pairs_from_text(f"{HEADER}\nSOMEBRAND 999 9990 B Something - 1mg A01AB Agent\n")
    other_product = replace(product(999, "9990"), name="UNRELATED 5mg")

    marked, report = mark_otc([other_product], found.entries)

    assert found.pairs == {(999, "9990")}
    assert marked[0].otc_listed is False
    assert (report.marked, report.name_differs) == (0, 1)


def test_text_before_the_table_and_a_lone_letter_in_an_ingredient_are_not_rows() -> None:
    only_prose = f"Vitamin B, 1500 G, 22 B.\n{HEADER}\nIngredient - Vitamin B - 5mg\n"

    found = pairs_from_text(only_prose)

    assert (found.pairs, found.skipped) == (frozenset(), 0)


def test_a_changed_layout_is_refused_instead_of_misread() -> None:
    with pytest.raises(ValueError, match="header"):
        pairs_from_text("TESTAMOL 500mg 20 Tablet 1101 54321/09 G Paracetamol - 500mg")


def test_the_list_file_is_read_back_exactly(tmp_path: Path) -> None:
    entries = pairs_from_text(EXTRACT).entries

    write_otc_list(tmp_path / "otc_list.csv", entries)

    assert set(read_otc_list(tmp_path / "otc_list.csv")) == set(entries)


def test_a_list_file_of_an_earlier_layout_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "otc_list.csv"
    path.write_text("code,registration_number\n1101,54321/09\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fetch_otc_list"):
        read_otc_list(path)


def product(code: int, registration: str, ingredients: str = "Paracetamol - 500mg") -> CatalogRow:
    return CatalogRow(
        code=code,
        registration_number=registration,
        name=f"PRODUCT {code}",
        strength="500mg",
        presentation="20",
        form="Tablet",
        manufacturer="Maker",
        price_lbp=100_000,
        atc="N02BE01",
        brand_generic="G",
        ingredients=ingredients,
    )


class TestMarking:
    """Only the very product the list names is marked: the same code AND registration, and
    a name the list's row holds."""

    LISTED = (
        OtcEntry(1101, "54321/09", "PRODUCT 500mg 20 Tablet"),
        OtcEntry(1102, "765432/1", "Product 120mg/5ml 100ml Suspension"),
        OtcEntry(9999, "11111/11", "GONE 5mg 10 Tablet"),
    )

    def marks(self, *rows: CatalogRow) -> dict[int, bool]:
        marked, _ = mark_otc(rows, self.LISTED)
        return {row.code: row.otc_listed for row in marked}

    def test_the_same_code_and_registration_number_is_marked(self) -> None:
        assert self.marks(product(1101, "54321/09"), product(1102, "765432/1")) == {
            1101: True,
            1102: True,
        }

    def test_the_same_code_with_another_registration_number_is_not(self) -> None:
        assert self.marks(product(1101, "54321/10")) == {1101: False}

    def test_the_same_registration_number_with_another_code_is_not(self) -> None:
        assert self.marks(product(2101, "54321/09")) == {2101: False}

    def test_the_same_ingredients_as_a_listed_product_are_not_enough(self) -> None:
        listed = product(1101, "54321/09", "Paracetamol - 500mg")
        same_medicine = product(3101, "70000/20", "Paracetamol - 500mg")

        assert self.marks(listed, same_medicine) == {1101: True, 3101: False}

    def test_a_registration_number_is_compared_as_written(self) -> None:
        assert self.marks(product(1102, "765432/01"), product(1101, "54321/9")) == {
            1102: False,
            1101: False,
        }

    def test_the_same_pair_under_a_name_the_row_does_not_hold_is_not(self) -> None:
        """A listed code reused by another product (an injectable, say) keeps its notice."""
        reused = replace(product(1101, "54321/09"), name="OTHERNAME 10mg/ml", form="Injectable")

        marked, report = mark_otc([reused], self.LISTED)

        assert marked[0].otc_listed is False
        assert report.name_differs == 1

    def test_the_brand_is_found_among_wrapped_words(self) -> None:
        wrapped = (OtcEntry(1108, "66666/15", "WRAPPEDTEST DROPS 15ml Solution for nasal use"),)
        row = replace(product(1108, "66666/15"), name="WRAPPEDTEST DROPS")

        marked, _ = mark_otc([row], wrapped)

        assert marked[0].otc_listed is True

    def test_it_counts_what_the_list_names_and_the_catalog_lacks(self) -> None:
        _, report = mark_otc([product(1101, "54321/09"), product(1102, "765432/2")], self.LISTED)

        assert (report.listed, report.marked, report.not_in_catalog) == (3, 1, 2)
        # 1102 is in the catalog, under another registration number; 9999 is not at all.
        assert report.code_with_another_registration == 1


class TestTheCatalogFile:
    def test_the_mark_travels_in_the_catalog_file(self, tmp_path: Path) -> None:
        rows = [replace(product(1101, "54321/09"), otc_listed=True), product(1102, "1/1")]

        write_catalog(tmp_path / "catalog.csv", rows)

        assert [row.otc_listed for row in read_catalog(tmp_path / "catalog.csv")] == [True, False]

    def test_a_file_built_before_the_mark_existed_keeps_every_notice(self, tmp_path: Path) -> None:
        write_catalog(tmp_path / "catalog.csv", [product(1101, "54321/09")])
        old = tmp_path / "old.csv"
        lines = (tmp_path / "catalog.csv").read_text(encoding="utf-8").splitlines()
        old.write_text("\n".join(line.rsplit(",", 1)[0] for line in lines) + "\n", encoding="utf-8")

        assert "otc_listed" not in old.read_text(encoding="utf-8")
        assert read_catalog(old)[0].otc_listed is False

    @pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE", " True", ""])
    def test_only_the_exact_mark_counts(self, tmp_path: Path, value: str) -> None:
        write_catalog(tmp_path / "catalog.csv", [replace(product(1101, "1/1"), otc_listed=True)])
        path = tmp_path / "catalog.csv"
        path.write_text(path.read_text(encoding="utf-8").replace(",True", f",{value}"), "utf-8")

        assert read_catalog(path)[0].otc_listed is False


def test_the_ministrys_pdf_and_list_stay_out_of_the_image() -> None:
    """The Dockerfile copies the data folder; only the catalog file, with its mark, ships."""
    ignored = (Path(__file__).parents[3] / ".dockerignore").read_text(encoding="utf-8")

    assert {"data/moph/*.pdf", "data/moph/otc_list.csv"} <= set(ignored.splitlines())


def test_the_running_app_never_loads_the_pdf_library() -> None:
    """pypdf is a laptop tool, in the dev dependencies only: the image has no copy of it."""
    code = (
        "import sys\n"
        "import dawalink.api.main, dawalink.ops.import_catalog, dawalink.ops.build_catalog\n"
        "assert 'pypdf' not in sys.modules, 'pypdf was imported'\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
