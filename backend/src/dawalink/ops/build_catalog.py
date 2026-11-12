"""Joins the Ministry's downloads into one catalog file: python -m dawalink.ops.build_catalog

Run after `fetch_moph`. It writes `catalog.csv` and `catalog.json` next to the downloads,
in backend/data/moph/, which is never committed (decision log O5). `import_catalog` reads
them, and they are small enough to ship inside the backend image.
"""

import argparse
import json
from pathlib import Path

from dawalink.catalog.moph import join, read_database_pages, read_price_list, write_catalog

CATALOG_FILE = "catalog.csv"
DETAILS_FILE = "catalog.json"


def build(folder: Path) -> dict[str, object]:
    price_lists = sorted(folder.glob("WebMarketed*.xls"))
    if not price_lists:
        raise FileNotFoundError(f"No price list in {folder}: run dawalink.ops.fetch_moph first.")
    price_list_file = price_lists[-1]
    price_list = read_price_list(price_list_file)
    if price_list.source_date is None or price_list.lbp_per_usd is None:
        raise ValueError("The price list states no date or no exchange rate.")
    database = read_database_pages(folder / "pages")
    rows, report = join(price_list.rows, database)
    write_catalog(folder / CATALOG_FILE, rows)
    details: dict[str, object] = {
        "file_name": price_list_file.name,
        "source_date": price_list.source_date.isoformat(),
        "lbp_per_usd": str(price_list.lbp_per_usd),
        "rows_total": price_list.rows_total,
        "rows_with_a_price": len(price_list.rows),
        "database_rows": len(database),
        "matched": report.matched,
        "not_found": report.not_found,
        "unclear": report.unclear,
    }
    (folder / DETAILS_FILE).write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8")
    return details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=Path("data/moph"))
    arguments = parser.parse_args()
    for name, value in build(arguments.folder).items():
        print(f"{name}: {value}")


if __name__ == "__main__":
    main()
