"""Turns OpenStreetMap's list of Lebanon's places into areas a client can name (docs/04 R-S2).

Our own hand-written list (`data/areas.csv`) knows the districts and the well-known
neighbourhoods, with the ways people spell them. OpenStreetMap adds every town and village
with its real centre. This module joins the two; `ops.build_areas` writes the result to
`data/areas_osm.csv`.

The rules, all on the careful side, because a wrong area sends a client to the wrong
pharmacy without anyone noticing:
- a place written like a hand-written area of the same district, or within a short walk
  of it, is that area: the hand-written row stays and nothing is added;
- inside one district a name means one place. Two map points with one name close together
  are one place; far apart, neither is listed, because asking "which one?" would show the
  client the same name twice;
- a place outside every district we know is left out, never moved to the nearest one;
- a name is kept only if it is plain letters, Latin or Arabic: these names are typed by
  volunteers, and the agent reads them.
"""

import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from dawalink.domain.geo import Point, straight_line_km
from dawalink.domain.places import key

# The kinds of place we ask the map for, the biggest first.
KINDS = ("city", "town", "village", "suburb", "quarter", "neighbourhood")
# Which of a place's names we read: English, French and Arabic, as Lebanon writes them.
_DISPLAY_TAGS = ("name:en", "int_name", "name:fr", "name")
_OTHER_TAGS = (
    "name",
    "name:en",
    "name:fr",
    "name:ar",
    "int_name",
    "alt_name",
    "alt_name:en",
    "alt_name:fr",
    "alt_name:ar",
    "short_name",
)
_BETWEEN_WORDS = frozenset(" -'\N{RIGHT SINGLE QUOTATION MARK}")
MIN_NAME_CHARS = 2
MAX_NAME_CHARS = 40
MAX_NAME_WORDS = 6
MAX_OTHER_NAMES = 8
SAME_PLACE_KM = 2.0  # two map points with one name, this close, are one place
NEAR_A_HAND_WRITTEN_AREA_KM = 3.0
FIRST_ID = 1000  # the hand-written areas keep every id below this
COORDINATE_STEP = Decimal("0.00001")


@dataclass(frozen=True)
class Listed:
    """An area of the hand-written list."""

    id: int
    name: str
    district: str
    other_names: tuple[str, ...]
    point: Point
    whole_district: bool = False

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(key(name) for name in (self.name, *self.other_names)) - {""}


@dataclass(frozen=True)
class Found:
    """A place read from the map, in one of our districts."""

    osm_id: int
    kind: str
    district: str
    name: str
    other_names: tuple[str, ...]
    point: Point

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(key(name) for name in (self.name, *self.other_names))


@dataclass(frozen=True)
class Row:
    """One line of the generated file."""

    id: int
    name: str
    district: str
    other_names: tuple[str, ...]
    kind: str
    point: Point
    osm_id: int


@dataclass(frozen=True)
class Seen:
    """A hand-written area the map also has, and how far apart the two centres are."""

    listed: Listed
    point: Point
    km: float


@dataclass
class Report:
    left_out: Counter[str] = field(default_factory=Counter)
    seen: list[Seen] = field(default_factory=list)
    name_twice: list[tuple[str, str]] = field(default_factory=list)  # (name, district)


def script(name: str) -> str | None:
    """'latin' or 'arabic' when `name` is plain letters of one of them, else None."""
    if not MIN_NAME_CHARS <= len(name) <= MAX_NAME_CHARS:
        return None
    if name != name.strip() or len(name.split()) > MAX_NAME_WORDS:
        return None
    if " -" in name or "- " in name:  # "Rmeish - Bint Jbeil": a label, not a name
        return None
    scripts = set()
    for letter in name:
        if letter in _BETWEEN_WORDS:
            continue
        category = unicodedata.category(letter)
        if category.startswith("M"):  # an accent or a vowel mark written on its own
            continue
        if not category.startswith("L"):
            return None
        scripts.add(unicodedata.name(letter, "").split(" ")[0])
    if scripts == {"LATIN"}:
        return "latin"
    if scripts == {"ARABIC"}:
        return "arabic"
    return None


def _names(tags: Mapping[str, object], which: Iterable[str]) -> list[str]:
    names: list[str] = []
    for tag in which:
        value = tags.get(tag)
        if isinstance(value, str):
            names.extend(part.strip() for part in value.split(";"))
    return [name for name in names if script(name) and len(key(name)) >= MIN_NAME_CHARS]


def names_of(tags: Mapping[str, object]) -> tuple[str, tuple[str, ...]] | None:
    """The name we show and the other ways the place is written, or None without a usable one."""
    shown = _names(tags, _DISPLAY_TAGS)
    latin = [name for name in shown if script(name) == "latin"]
    everything = [*latin, *shown, *_names(tags, _OTHER_TAGS)]
    if not everything:
        return None
    name, others, known = everything[0], [], {key(everything[0])}
    for other in everything[1:]:
        if key(other) not in known:
            known.add(key(other))
            others.append(other)
    return name, tuple(others[:MAX_OTHER_NAMES])


def district_of(tags: Mapping[str, object], districts: Mapping[str, str]) -> str | None:
    """Our name for a district of the map ("Zahlé District" is our "Zahle")."""
    for tag in ("name:en", "int_name", "name"):
        value = tags.get(tag)
        if isinstance(value, str):
            plain = value.removesuffix(" District").removesuffix(" Governorate")
            if key(plain) in districts:
                return districts[key(plain)]
    return None


def district_names(listed: Iterable[Listed]) -> dict[str, str]:
    """Every way a district is written in the hand-written list, simplified, to its name."""
    return {simple: area.district for area in listed if area.whole_district for simple in area.keys}


def read(
    elements: Iterable[Mapping[str, object]], districts: Mapping[str, str]
) -> tuple[list[Found], Report]:
    """The map's answer (a district, then the places inside it, and so on) as places."""
    report = Report()
    found: dict[int, Found] = {}
    district: str | None = None
    mapped = set()
    for element in elements:
        tags = element.get("tags")
        if not isinstance(tags, Mapping):
            continue
        if element.get("type") == "relation":
            district = district_of(tags, districts)
            if district is not None:
                mapped.add(district)
            continue
        osm_id, lat, lon, kind = (
            element.get("id"),
            element.get("lat"),
            element.get("lon"),
            tags.get("place"),
        )
        if element.get("type") != "node" or not isinstance(osm_id, int) or kind not in KINDS:
            report.left_out["not a place we asked for"] += 1
            continue
        if district is None:
            report.left_out["in no district we know"] += 1
            continue
        if osm_id in found:
            report.left_out["in two districts"] += 1
            del found[osm_id]
            continue
        names = names_of(tags)
        if names is None or not isinstance(lat, int | float) or not isinstance(lon, int | float):
            report.left_out["no usable name"] += 1
            continue
        point = Point(
            Decimal(str(lat)).quantize(COORDINATE_STEP), Decimal(str(lon)).quantize(COORDINATE_STEP)
        )
        found[osm_id] = Found(osm_id, str(kind), district, names[0], names[1], point)
    missing = sorted(set(districts.values()) - mapped)
    if missing:
        raise ValueError(f"The map's answer has no district for: {', '.join(missing)}.")
    return list(found.values()), report


def _same_as(place: Found, listed: Sequence[Listed]) -> Listed | None:
    """The hand-written area this map place is, if any."""
    alike = [area for area in listed if area.keys & place.keys]
    for area in alike:
        if area.district == place.district:
            return area
    near = [
        (straight_line_km(area.point, place.point), area)
        for area in alike
        if not area.whole_district
    ]
    near = [(km, area) for km, area in near if km <= NEAR_A_HAND_WRITTEN_AREA_KM]
    return min(near, key=lambda pair: pair[0])[1] if near else None


def _close_together(places: Sequence[Found]) -> bool:
    return all(
        straight_line_km(places[0].point, place.point) <= SAME_PLACE_KM for place in places[1:]
    )


def _one_place_per_name(places: Sequence[Found], report: Report) -> list[Found]:
    """Makes every way of writing a place mean one place inside its district.

    `places` come the biggest first. When several of them are written alike:
    - close together, they are one place drawn more than once: the biggest one named so
      stays, and the others lose that name;
    - far apart, the name is no use to a client: nobody keeps it, and a place that has no
      other name to be shown by is left out.
    """
    Spot = tuple[str, str]  # (district, simplified name)
    written_so: dict[Spot, list[Found]] = defaultdict(list)
    for place in places:
        for simple in place.keys:
            written_so[(place.district, simple)].append(place)

    drawn_twice: set[int] = set()
    name_twice: set[int] = set()
    nobodys: set[Spot] = set()
    for spot, claimants in written_so.items():
        named_so = [place for place in claimants if key(place.name) == spot[1]]
        if len(claimants) == 1 or not named_so:
            continue
        if _close_together(claimants):
            drawn_twice.update(place.osm_id for place in named_so[1:])
        else:
            nobodys.add(spot)
            name_twice.update(place.osm_id for place in named_so)
            report.name_twice.append((named_so[0].name, spot[0]))
    left_out = drawn_twice | name_twice
    report.left_out["on the map twice"] += len(drawn_twice - name_twice)
    report.left_out["a name used twice in one district"] += len(name_twice)
    report.left_out = +report.left_out  # without the reasons that left nothing out

    listed = [place for place in places if place.osm_id not in left_out]
    shown_by = {(place.district, key(place.name)) for place in listed}
    result = []
    for place in listed:
        mine = []
        for other in place.other_names:
            spot = (place.district, key(other))
            if spot in shown_by or spot in nobodys:
                continue
            # A place left out above still counts: its name is as ambiguous as before.
            claimants = written_so[spot]
            first = next(one for one in claimants if one.osm_id not in left_out)
            if first is place and _close_together(claimants):
                mine.append(other)
        result.append(replace(place, other_names=tuple(mine)))
    return result


def merge(
    found: Iterable[Found],
    listed: Sequence[Listed],
    earlier: Sequence[Row] = (),
    report: Report | None = None,
) -> tuple[list[Row], Report]:
    """The generated rows: what the map adds to the hand-written list.

    `earlier` is the file as it was built last time. A place keeps the id it had, and a
    place the map no longer has stays listed: an id in use is never changed or reused.
    """
    report = report or Report()
    by_size = sorted(found, key=lambda place: (KINDS.index(place.kind), place.osm_id))
    new = []
    for place in by_size:
        same = _same_as(place, listed)
        if same is None:
            new.append(place)
        else:
            km = straight_line_km(same.point, place.point)
            report.seen.append(Seen(same, place.point, round(km, 2)))
            report.left_out["already hand-written"] += 1
    kept = {place.osm_id: place for place in _one_place_per_name(new, report)}

    rows = {row.osm_id: row for row in earlier}
    gone = {(row.district, key(row.name)): row for row in earlier if row.osm_id not in kept}
    next_id = max([FIRST_ID - 1, *(row.id for row in earlier)]) + 1
    for place in sorted(
        kept.values(), key=lambda place: (place.district, place.name, place.osm_id)
    ):
        before = rows.get(place.osm_id) or gone.get((place.district, key(place.name)))
        if before is None:
            row_id, next_id = next_id, next_id + 1
        else:
            # The same map point, or the same name in the same district drawn again.
            row_id = before.id
            del rows[before.osm_id]
        rows[place.osm_id] = Row(
            row_id,
            place.name,
            place.district,
            place.other_names,
            place.kind,
            place.point,
            place.osm_id,
        )
    return sorted(rows.values(), key=lambda row: row.id), report
