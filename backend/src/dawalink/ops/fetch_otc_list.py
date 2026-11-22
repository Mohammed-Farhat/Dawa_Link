"""Downloads the Ministry's no-prescription list: python -m dawalink.ops.fetch_otc_list

The Ministry of Public Health's "National OTC Medicines List" (first edition, 2018) is a PDF.
This saves it under backend/data/moph/, which is never committed (decision log O5), and
writes the products it names (code, registration number and the row's words before the
code) to `otc_list.csv` beside it. Run `build_catalog` afterwards: it marks the catalog's
products the list names (docs/04 R-C7). A file already there is not fetched again; pass
`--pdf` to read a copy.
"""

import argparse
import shutil
from pathlib import Path

from dawalink.catalog.otc_list import OTC_LIST_FILE, read_otc_pdf, write_otc_list
from dawalink.ops.fetch_moph import SITE, download

OTC_LIST_URL = (
    SITE + "/userfiles/files/HealthCareSystem/Pharmaceuticals/OTCMedicineList"
    "/OTC2018-FirstEdition%20for%20web.pdf"
)
PDF_FILE = "OTC2018-FirstEdition.pdf"


def fetch(folder: Path, copy_from: Path | None = None) -> tuple[int, int]:
    """Saves the PDF and writes the pairs file. Returns how many products were read and skipped."""
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / PDF_FILE
    if copy_from is not None:
        shutil.copyfile(copy_from, pdf)
    else:
        download(OTC_LIST_URL, pdf)
    otc_list = read_otc_pdf(pdf)
    write_otc_list(folder / OTC_LIST_FILE, otc_list.entries)
    return len(otc_list.pairs), otc_list.skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=Path("data/moph"))
    parser.add_argument("--pdf", type=Path, help="read this copy instead of downloading")
    arguments = parser.parse_args()
    read, skipped = fetch(arguments.folder, arguments.pdf)
    print(f"products read from the list: {read}")
    print(f"rows skipped, not readable with certainty: {skipped}")


if __name__ == "__main__":
    main()
