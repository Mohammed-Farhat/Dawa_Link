"""Downloads the Ministry of Public Health's medicine data: python -m dawalink.ops.fetch_moph

Two public sources on moph.gov.lb are needed, because neither is complete alone:
- the **price list** (.xls): code, registration number, name, strength, pack, form, price;
- the **Lebanon National Drugs Database** web pages: ATC code, brand or generic, ingredients.

Everything is saved under backend/data/moph/, which is never committed (decision log O5).
A file that is already there is not fetched again, and pages are requested one at a time
with a pause, so the Ministry's site is not loaded.
"""

import argparse
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

SITE = "https://www.moph.gov.lb"
PRICE_LIST_URL = (
    SITE + "/userfiles/files/HealthCareSystem/Pharmaceuticals/DrugsPublicPriceList"
    "/{day:02d}-{month:02d}-{year}/WebMarketed{year}{month:02d}{day:02d}-.xls"
)
DATABASE_PAGE_URL = SITE + "/en/Drugs/index/3/4848/page:{page}/sort:Drug.brand_name/direction:ASC"
USER_AGENT = "Mozilla/5.0 (catalog import for a university project)"
TIMEOUT_S = 120
ATTEMPTS = 4
_PAGE_LINK = re.compile(rb"/page:(\d+)")


def download(url: str, target: Path, *, attempts: int = ATTEMPTS) -> bool:
    """Saves `url` to `target` unless it is already there. True when something was fetched."""
    if target.is_file() and target.stat().st_size > 0:
        return False
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                data = response.read()
            break
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == attempts:
                raise RuntimeError(f"Could not download {url}: {error}") from error
            time.sleep(5 * attempt)
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(data)
    partial.replace(target)
    return True


def last_page(first_page: bytes) -> int:
    """The highest page number linked from the first page of the database."""
    pages = [int(number) for number in _PAGE_LINK.findall(first_page)]
    if not pages:
        raise RuntimeError("The database page lists no further pages: its layout has changed.")
    return max(pages)


def page_path(folder: Path, page: int) -> Path:
    return folder / "pages" / f"page_{page:03d}.html"


def fetch(folder: Path, *, year: int, month: int, day: int, delay_s: float) -> None:
    (folder / "pages").mkdir(parents=True, exist_ok=True)
    price_list = folder / f"WebMarketed{year}{month:02d}{day:02d}-.xls"
    if download(PRICE_LIST_URL.format(year=year, month=month, day=day), price_list):
        print(f"price list saved: {price_list.name}")

    download(DATABASE_PAGE_URL.format(page=1), page_path(folder, 1))
    pages = last_page(page_path(folder, 1).read_bytes())
    for page in range(2, pages + 1):
        if download(DATABASE_PAGE_URL.format(page=page), page_path(folder, page)):
            print(f"page {page} of {pages}", flush=True)
            time.sleep(delay_s)
    print(f"done: the price list and {pages} database pages are in {folder}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="the price list's date, YYYY-MM-DD")
    parser.add_argument("--folder", type=Path, default=Path("data/moph"))
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    arguments = parser.parse_args()
    year, month, day = (int(part) for part in arguments.date.split("-"))
    fetch(arguments.folder, year=year, month=month, day=day, delay_s=arguments.delay_seconds)


if __name__ == "__main__":
    main()
