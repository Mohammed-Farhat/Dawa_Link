"""The two laptop commands around the Ministry's files, with invented data and no network."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from dawalink.catalog.moph import PriceList, PriceRow, read_catalog
from dawalink.ops import build_catalog, fetch_moph
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
