"""Reading and joining the Ministry's two sources. All data here is invented."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from dawalink.catalog.moph import (
    PRICE_LIST_COLUMNS,
    CatalogRow,
    DatabaseRow,
    PriceRow,
    database_rows_from_html,
    join,
    price_list_from_rows,
    read_catalog,
    write_catalog,
)
from dawalink.ops.fetch_moph import download, last_page

HEADER = [*PRICE_LIST_COLUMNS, "Pharmacist Margin", "Stratum", "public price Decision 119/1"]
HEADER += ["Responsible Party Name", "Responsible Party Country", "Exch_Dates"]
EXCEL_DAY = 46337.0  # 11 November 2026, as Excel stores a date


def sheet_row(code: float, name: str, price: object, usd: object = 2.0) -> list[object]:
    product = [code, "1/1", name, "500mg", "20", "Tablet", "Agent", "Maker", "Lebanon", price]
    return [*product, 23.08, "A1", usd, "", "", EXCEL_DAY]


def cell(view: int, text: str) -> str:
    link = f'<a href="/en/Drugs/view/{view}" onclick="x();return false;" class="drugLink">'
    return f"<td>{link}{text}</a></td>"


def page_row(view: int, *cells: str) -> str:
    return "<tr>" + "".join(cell(view, c) for c in cells) + "</tr>"


class TestPriceList:
    def test_it_reads_products_the_date_and_the_exchange_rate(self) -> None:
        price_list = price_list_from_rows(
            HEADER,
            [
                sheet_row(101.0, "TESTAMOL", 179000.0),
                sheet_row(102.0, " TESTAPRIL\n PLUS ", 895000.0, 10.0),
            ],
        )

        assert price_list.rows[0] == PriceRow(
            101, "1/1", "TESTAMOL", "500mg", "20", "Tablet", "Maker", 179000
        )
        assert price_list.rows[1].name == "TESTAPRIL PLUS"
        assert price_list.source_date == date(2026, 11, 11)
        assert price_list.lbp_per_usd == Decimal("89500.00")
        assert price_list.rows_total == 2

    def test_rows_without_a_price_are_counted_but_left_out(self) -> None:
        price_list = price_list_from_rows(
            HEADER, [sheet_row(101.0, "TESTAMOL", 179000.0), sheet_row(102.0, "NO PRICE", "", "")]
        )

        assert [row.code for row in price_list.rows] == [101]
        assert price_list.rows_total == 2

    def test_a_changed_layout_is_refused_instead_of_misread(self) -> None:
        with pytest.raises(ValueError, match="columns have changed"):
            price_list_from_rows(["Code", "Name", "Price"], [])


class TestDatabasePages:
    def test_it_reads_the_rows_of_a_page(self) -> None:
        page = (
            "<table><thead><tr><th>ATC</th></tr></thead>"
            + page_row(
                7,
                "N02BE01",
                "TESTAMOL",
                "G",
                "Paracetamol - 500mg",
                "500mg",
                "Tablet",
                "\n 179,000 L.L<!-- <br/> -->\n",
            )
            + page_row(
                8,
                "C09AA02",
                "TESTAPRIL &amp; CO",
                "B",
                "Enalapril - 5mg",
                "5mg",
                "Tablet",
                "895,000 L.L",
            )
            + "<tr><td>navigation</td></tr></table>"
        )

        rows = database_rows_from_html(page)

        assert rows[0] == DatabaseRow(
            "N02BE01", "TESTAMOL", "G", "Paracetamol - 500mg", "500mg", "Tablet", 179000
        )
        assert rows[1].name == "TESTAPRIL & CO"
        assert len(rows) == 2

    def test_the_number_of_pages_is_read_from_the_first_page(self) -> None:
        assert (
            last_page(b'<a href="/x/page:2/sort">2</a> <a href="/x/page:200/sort">200</a>') == 200
        )
        with pytest.raises(RuntimeError, match="layout has changed"):
            last_page(b"<html>no links</html>")

    def test_a_file_already_there_is_not_fetched_again(self, tmp_path: Path) -> None:
        target = tmp_path / "page_001.html"
        target.write_text("already here", encoding="utf-8")

        assert download("http://127.0.0.1:1/never-called", target) is False
        assert target.read_text(encoding="utf-8") == "already here"


def product(
    code: int, name: str, price: int, strength: str = "500mg", form: str = "Tablet"
) -> PriceRow:
    return PriceRow(code, "1/1", name, strength, "20", form, "Maker", price)


def entry(
    name: str, ingredients: str, price: int | None, dosage: str = "500mg", form: str = "Tablet"
) -> DatabaseRow:
    return DatabaseRow("N02BE01", name, "G", ingredients, dosage, form, price)


class TestJoin:
    def test_a_product_gets_its_details_by_name_and_price(self) -> None:
        rows, report = join(
            [product(101, "TESTAMOL", 179000)],
            [
                entry("Testamol", "Paracetamol - 500mg", 179000),
                entry("OTHER", "Other - 1mg", 179000),
            ],
        )

        assert rows == [
            CatalogRow(
                101,
                "1/1",
                "TESTAMOL",
                "500mg",
                "20",
                "Tablet",
                "Maker",
                179000,
                "N02BE01",
                "G",
                "Paracetamol - 500mg",
            )
        ]
        assert (report.matched, report.not_found, report.unclear) == (1, 0, 0)

    def test_the_two_sources_may_round_a_price_differently(self) -> None:
        rows, _ = join(
            [product(101, "TESTAMOL", 371156)], [entry("TESTAMOL", "Paracetamol - 500mg", 371157)]
        )

        assert len(rows) == 1

    def test_the_same_name_and_price_is_settled_by_the_strength(self) -> None:
        database = [
            entry("TESTAMOL", "Paracetamol - 500mg", 179000, dosage="500mg"),
            entry("TESTAMOL", "Paracetamol - 1g", 179000, dosage="1g"),
        ]

        rows, _ = join([product(102, "TESTAMOL", 179000, strength="1 g")], database)

        assert rows[0].ingredients == "Paracetamol - 1g"

    def test_a_combination_is_matched_by_its_ingredients_strengths(self) -> None:
        database = [
            entry("TESTACOMBO", "Amlodipine - 5mg, Valsartan - 160mg", 923220, dosage=""),
            entry("TESTACOMBO", "Amlodipine - 10mg, Valsartan - 160mg", 923220, dosage=""),
        ]

        rows, _ = join([product(103, "TESTACOMBO", 923220, strength="10mg/160mg")], database)

        assert rows[0].ingredients == "Amlodipine - 10mg, Valsartan - 160mg"

    def test_several_packs_of_one_medicine_all_get_the_same_details(self) -> None:
        database = [entry("TESTAMOL", "Paracetamol - 500mg", 179000)] * 2

        rows, report = join([product(101, "TESTAMOL", 179000)], database)

        assert report.matched == 1
        assert rows[0].ingredients == "Paracetamol - 500mg"

    def test_when_it_is_not_clear_which_row_it_is_the_product_is_left_out(self) -> None:
        """Better no product than a product with another one's ingredients."""
        database = [
            entry("TESTAMOL", "Paracetamol - 500mg", 179000, dosage=""),
            entry("TESTAMOL", "Paracetamol - 500mg, Codeine - 30mg", 179000, dosage=""),
        ]

        rows, report = join([product(101, "TESTAMOL", 179000, strength="")], database)

        assert rows == []
        assert report.unclear == 1

    def test_a_name_alone_is_not_enough_when_several_rows_carry_it(self) -> None:
        database = [
            entry("TESTAMOL", "Paracetamol - 250mg", 100000, dosage="250mg"),
            entry("TESTAMOL", "Paracetamol - 125mg", 90000, dosage="125mg"),
        ]

        _, report = join([product(101, "TESTAMOL", 555555, strength="")], database)

        assert report.unclear == 1

    def test_a_product_the_database_does_not_list_is_counted(self) -> None:
        rows, report = join(
            [product(101, "TESTAMOL", 179000)], [entry("OTHER", "Other - 1mg", 179000)]
        )

        assert rows == []
        assert report.not_found == 1

    def test_the_databases_form_is_used_because_it_is_the_consistent_one(self) -> None:
        database = [entry("TESTAMOL", "Paracetamol - 500mg", 179000, form="Tablet, film coated")]

        rows, _ = join([product(101, "TESTAMOL", 179000, form="Comprimés pelliculés")], database)

        assert rows[0].form == "Tablet, film coated"


def test_the_catalog_file_is_read_back_exactly(tmp_path: Path) -> None:
    rows = [
        CatalogRow(
            102,
            "2/2",
            "B, WITH A COMMA",
            "1g",
            "10",
            "Tablet",
            "Maker",
            5,
            "A01",
            "B",
            "X - 1g, Y - 2mg",
        ),
        CatalogRow(
            101,
            "1/1",
            "TESTAMOL",
            "500mg",
            "20",
            "Tablet",
            "Maker",
            179000,
            "N02BE01",
            "G",
            "Paracetamol - 500mg",
        ),
    ]

    write_catalog(tmp_path / "catalog.csv", rows)

    assert read_catalog(tmp_path / "catalog.csv") == sorted(rows, key=lambda row: row.code)
