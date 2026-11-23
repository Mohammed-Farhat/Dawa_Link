"""The two laptop commands around the Ministry's files, with invented data and no network."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from dawalink.catalog.moph import PriceList, PriceRow, read_catalog
from dawalink.catalog.otc_list import OtcEntry, OtcList, read_otc_list, write_otc_list
from dawalink.ops import build_catalog, fetch_moph, fetch_otc_list
from tests.unit.catalog.test_moph import page_row


def write_page(folder: Path, number: int, *rows: str) -> None:
    (folder / "pages").mkdir(exist_ok=True)
    page = "<table>" + "".join(rows) + '</table><a href="/x/page:2/sort">2</a>'
    (folder / "pages" / f"page_{number:03d}.html").write_text(page, encoding="utf-8")


def test_building_joins_the_downloads_into_one_catalog_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "WebMarketed20261111-.xls").write_bytes(b"stands in for the real sheet")
    price_list = PriceList(
        rows=[
            PriceRow(101, "1/1", "TESTAMOL", "500mg", "20", "Tablet", "Maker", 179000),
            PriceRow(102, "2/2", "NOWHERE", "1mg", "10", "Tablet", "Maker", 5000),
        ],
        rows_total=3,
        source_date=date(2026, 11, 11),
        lbp_per_usd=Decimal("89500.00"),
    )
    monkeypatch.setattr(build_catalog, "read_price_list", lambda path: price_list)
    write_page(
        tmp_path,
        1,
        page_row(
            7, "N02BE01", "TESTAMOL", "G", "Paracetamol - 500mg", "500mg", "Tablet", "179,000 L.L"
        ),
    )

    details = build_catalog.build(tmp_path)

    assert read_catalog(tmp_path / "catalog.csv")[0].ingredients == "Paracetamol - 500mg"
    assert json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8")) == details
    assert details == {
        "file_name": "WebMarketed20261111-.xls",
        "source_date": "2026-11-11",
        "lbp_per_usd": "89500.00",
        "rows_total": 3,
        "rows_with_a_price": 2,
        "database_rows": 1,
        "matched": 1,
        "not_found": 1,
        "unclear": 0,
    }


def two_products(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A price list and a database page that join into two products."""
    (tmp_path / "WebMarketed20261111-.xls").write_bytes(b"stands in for the real sheet")
    price_list = PriceList(
        rows=[
            PriceRow(101, "11111/09", "TESTAMOL", "500mg", "20", "Tablet", "Maker", 179000),
            PriceRow(102, "22222/1", "TESTAMOL", "500mg", "40", "Tablet", "Maker", 300000),
        ],
        rows_total=2,
        source_date=date(2026, 11, 11),
        lbp_per_usd=Decimal("89500.00"),
    )
    monkeypatch.setattr(build_catalog, "read_price_list", lambda path: price_list)
    write_page(
        tmp_path,
        1,
        page_row(
            7, "N02BE01", "TESTAMOL", "G", "Paracetamol - 500mg", "500mg", "Tablet", "179,000 L.L"
        ),
        page_row(
            8, "N02BE01", "TESTAMOL", "G", "Paracetamol - 500mg", "500mg", "Tablet", "300,000 L.L"
        ),
    )


def test_building_marks_the_products_the_ministrys_otc_list_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_products(tmp_path, monkeypatch)
    # 101 is named exactly; 102's code is listed under another registration; 900 is gone.
    write_otc_list(
        tmp_path / "otc_list.csv",
        [
            OtcEntry(101, "11111/09", "TESTAMOL 500mg 20 Tablet"),
            OtcEntry(102, "22222/2", "TESTAMOL 500mg 40 Tablet"),
            OtcEntry(900, "9/9", "GONE 1mg 10 Tablet"),
        ],
    )

    details = build_catalog.build(tmp_path)

    assert {r.code: r.otc_listed for r in read_catalog(tmp_path / "catalog.csv")} == {
        101: True,
        102: False,
    }
    assert {key: value for key, value in details.items() if key.startswith("otc_")} == {
        "otc_listed": 3,
        "otc_marked": 1,
        "otc_name_differs": 0,
        "otc_not_in_catalog": 2,
        "otc_code_with_another_registration": 1,
    }


def test_a_pairs_file_of_an_earlier_layout_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the row's words, no name could be checked: refused rather than marked by pair."""
    two_products(tmp_path, monkeypatch)
    (tmp_path / "otc_list.csv").write_text(
        "code,registration_number\n101,11111/09\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="fetch_otc_list"):
        build_catalog.build(tmp_path)
    assert not (tmp_path / "catalog.csv").exists()


def test_without_the_otc_list_every_product_keeps_the_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    two_products(tmp_path, monkeypatch)

    details = build_catalog.build(tmp_path)

    assert not any(row.otc_listed for row in read_catalog(tmp_path / "catalog.csv"))
    assert not any(key.startswith("otc_") for key in details)
    assert "every product keeps the prescription notice" in capsys.readouterr().out


def test_fetching_the_otc_list_saves_the_pdf_and_writes_the_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def fake_download(url: str, target: Path, **_: object) -> bool:
        asked.append(url)
        target.write_bytes(b"stands in for the PDF")
        return True

    monkeypatch.setattr(fetch_otc_list, "download", fake_download)
    monkeypatch.setattr(
        fetch_otc_list,
        "read_otc_pdf",
        lambda path: OtcList((OtcEntry(101, "11111/09", "TESTAMOL 500mg"),), skipped=2),
    )

    assert fetch_otc_list.fetch(tmp_path) == (1, 2)
    assert read_otc_list(tmp_path / "otc_list.csv") == (
        OtcEntry(101, "11111/09", "TESTAMOL 500mg"),
    )
    assert asked == [fetch_otc_list.OTC_LIST_URL]
    assert asked[0].startswith("https://www.moph.gov.lb/")


def test_building_needs_the_price_list(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="fetch_moph"):
        build_catalog.build(tmp_path)


def test_fetching_gets_the_price_list_and_every_page_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def fake_download(url: str, target: Path, **_: object) -> bool:
        if target.is_file():
            return False
        asked.append(url)
        target.write_bytes(b'<a href="/en/Drugs/index/3/4848/page:3/sort">3</a>')
        return True

    monkeypatch.setattr(fetch_moph, "download", fake_download)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    fetch_moph.fetch(tmp_path, year=2026, month=11, day=11, delay_s=1.0)
    first_run = list(asked)
    fetch_moph.fetch(tmp_path, year=2026, month=11, day=11, delay_s=1.0)

    assert first_run[0].endswith("/11-11-2026/WebMarketed20261111-.xls")
    assert [url.split("/page:")[1].split("/")[0] for url in first_run[1:]] == ["1", "2", "3"]
    # Nothing is asked for a second time.
    assert asked == first_run
    assert all(url.startswith("https://www.moph.gov.lb/") for url in asked)
