"""Downloads Lebanon's place names from OpenStreetMap: python -m dawalink.ops.fetch_osm_places

Two small answers from the Overpass API (OpenStreetMap's public query service):
- `boundaries.json`: the administrative areas of Lebanon, names only (no outlines);
- `places.json`: for each district, the cities, towns, villages and neighbourhoods inside
  it, each with its centre point and its names.

Nothing about DawaLink or its clients is sent: the two questions below are all it asks.
The answers are © OpenStreetMap contributors, under the Open Database License. They are
saved outside git; `build_areas` turns them into `data/areas_osm.csv`.
"""

import argparse
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "place-list import for a university project"
TIMEOUT_S = 300
ATTEMPTS = 3
# In OpenStreetMap, Lebanon's governorates are level 4 and its districts level 5.
# Beirut is a governorate with no district inside it, so it is asked for by name.
GOVERNORATE_LEVEL = 4
DISTRICT_LEVEL = 5
BEIRUT = "Beirut Governorate"
PLACE_KINDS = "city|town|village|suburb|quarter|neighbourhood"

_LEBANON = 'area["ISO3166-1"="LB"][admin_level=2]->.lebanon;'
BOUNDARIES_QUERY = f"""
[out:json][timeout:120];
{_LEBANON}
rel(area.lebanon)[boundary=administrative][admin_level~"^[3-6]$"];
out tags;
"""
PLACES_QUERY = f"""
[out:json][timeout:240];
{_LEBANON}
(
  rel(area.lebanon)[boundary=administrative][admin_level={DISTRICT_LEVEL}];
  rel(area.lebanon)[boundary=administrative][admin_level={GOVERNORATE_LEVEL}]["name:en"="{BEIRUT}"];
)->.districts;
foreach.districts->.district(
  .district out tags;
  .district map_to_area->.inside;
  node(area.inside)[place~"^({PLACE_KINDS})$"][name];
  out;
);
"""


def ask(query: str, target: Path, *, attempts: int = ATTEMPTS) -> int:
    """Saves the answer to `query` in `target` and returns its size in bytes."""
    request = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                data = response.read()
            break
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == attempts:
                raise RuntimeError(f"Could not reach {OVERPASS_URL}: {error}") from error
            time.sleep(20 * attempt)
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(data)
    partial.replace(target)
    return len(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=Path("data/osm"))
    parser.add_argument("--only", choices=("boundaries", "places"), default=None)
    arguments = parser.parse_args()
    arguments.folder.mkdir(parents=True, exist_ok=True)
    if arguments.only != "places":
        size = ask(BOUNDARIES_QUERY, arguments.folder / "boundaries.json")
        print(f"boundaries.json: {size:,} bytes")
    if arguments.only != "boundaries":
        size = ask(PLACES_QUERY, arguments.folder / "places.json")
        print(f"places.json: {size:,} bytes")


if __name__ == "__main__":
    main()
