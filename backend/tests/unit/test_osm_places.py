"""Joining OpenStreetMap's places with our hand-written areas (R-S2, BLD-D15).

Every place here is invented: the tests don't depend on what the map says today.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from dawalink import osm_places
from dawalink.db.reference import read_areas
from dawalink.domain.geo import Point
from dawalink.ops import build_areas, fetch_osm_places
from dawalink.osm_places import FIRST_ID, Found, Listed, Row, merge, names_of, read, script

DISTRICTS = {"north": "North", "south": "South", "saida": "South"}


def point(lat: float, lon: float = 35.5) -> Point:
    return Point(Decimal(str(lat)), Decimal(str(lon)))


def district(name: str) -> dict[str, Any]:
    return {"type": "relation", "id": 1, "tags": {"name:en": f"{name} District"}}


def node(osm_id: int, name: str, lat: float = 33.9, kind: str = "village", **tags: str) -> Any:
    return {
        "type": "node",
        "id": osm_id,
        "lat": lat,
        "lon": 35.5,
        "tags": {
            "place": kind,
            "name:en": name,
            **{k.replace("_", ":"): v for k, v in tags.items()},
        },
    }


def found(osm_id: int, name: str, lat: float = 33.9, **changes: Any) -> Found:
    values: dict[str, Any] = {
        "kind": "village",
        "district": "North",
        "other_names": (),
        "point": point(lat),
    }
    return Found(osm_id=osm_id, name=name, **{**values, **changes})


def listed(area_id: int, name: str, lat: float = 33.9, **changes: Any) -> Listed:
    values: dict[str, Any] = {"district": "North", "other_names": (), "point": point(lat)}
    return Listed(id=area_id, name=name, **{**values, **changes})


class TestNames:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Kfar Zeina", "latin"),
            ("Aïn el-Remmaneh", "latin"),
            ("Dala'a", "latin"),
            ("كفر زينا", "arabic"),
            ("Kfar زينا", None),  # two scripts in one name
            ("Zone 3", None),
            ("see http://x.example", None),
            ("Name (old)", None),
            ("Rmeish - Bint Jbeil", None),  # a label, not a name
            ("כפר", None),
            ("K", None),
            ("a " * 7 + "b", None),
            ("x" * 41, None),
            (" Kfar", None),
        ],
    )
    def test_a_name_is_plain_latin_or_arabic_letters(self, name: str, expected: str | None) -> None:
        """Volunteers type these names and the agent reads them (TH-58)."""
        assert script(name) == expected

    def test_the_latin_name_is_shown_and_the_rest_are_other_spellings(self) -> None:
        tags = {
            "name": "كفر زينا",
            "name:en": "Kfar Zeina",
            "name:fr": "Kfar Zeïna",  # the same once simplified: not repeated
            "alt_name": "Kfarzayna; Zone 3",
            "name:de": "Kfar Zeina Dorf",  # a language we don't read
        }

        assert names_of(tags) == ("Kfar Zeina", ("كفر زينا", "Kfarzayna"))

    def test_an_arabic_name_is_shown_when_there_is_no_latin_one(self) -> None:
        assert names_of({"name": "كفر زينا"}) == ("كفر زينا", ())

    def test_a_place_without_a_usable_name_has_none(self) -> None:
        assert names_of({"name": "Zone 3", "name:en": "<b>x</b>"}) is None


class TestReadingTheAnswer:
    def test_each_place_is_in_the_district_it_follows(self) -> None:
        places, report = read(
            [
                district("North"),
                node(1, "Kfar Zeina"),
                {"type": "relation", "id": 2, "tags": {"name:en": "Saïda District"}},
                node(2, "Ain Baal", kind="town"),
            ],
            DISTRICTS,
        )

        assert [(p.name, p.district, p.kind) for p in places] == [
            ("Kfar Zeina", "North", "village"),
            ("Ain Baal", "South", "town"),
        ]
        assert places[0].point == point(33.9)
        assert not report.left_out

    def test_a_place_in_a_district_we_dont_know_is_left_out_not_moved(self) -> None:
        places, report = read(
            [district("North"), district("South"), district("Elsewhere"), node(1, "Kfar Zeina")],
            DISTRICTS,
        )

        assert places == []
        assert report.left_out == {"in no district we know": 1}

    def test_what_we_didnt_ask_for_is_left_out(self) -> None:
        answer = [
            district("North"),
            district("South"),
            node(1, "A Farm", kind="farm"),
            node(2, "Zone 3"),
            {"type": "node", "id": 3, "tags": {"place": "village", "name": "Kfar Zeina"}},
        ]

        _, report = read(answer, DISTRICTS)

        assert report.left_out == {"not a place we asked for": 1, "no usable name": 2}

    def test_every_district_of_ours_must_be_in_the_answer(self) -> None:
        with pytest.raises(ValueError, match="no district for: South"):
            read([district("North"), node(1, "Kfar Zeina")], DISTRICTS)


class TestJoining:
    def test_a_new_place_is_added_from_the_first_free_id(self) -> None:
        rows, _ = merge([found(7, "Kfar Zeina"), found(5, "Ain Baal")], [listed(101, "Hamra")])

        assert [(row.id, row.name, row.osm_id) for row in rows] == [
            (FIRST_ID, "Ain Baal", 5),
            (FIRST_ID + 1, "Kfar Zeina", 7),
        ]

    def test_a_hand_written_area_of_the_same_district_wins(self) -> None:
        hamra = listed(101, "Hamra", lat=33.90, other_names=("الحمرا",))

        rows, report = merge([found(1, "El Hamra", lat=33.95)], [hamra])

        assert rows == []
        assert [(seen.listed.id, seen.point) for seen in report.seen] == [(101, point(33.95))]
        assert report.left_out == {"already hand-written": 1}

    def test_so_does_one_a_short_walk_away_across_the_district_line(self) -> None:
        jnah = listed(152, "Jnah", lat=33.900, district="South")

        rows, _ = merge([found(1, "Jnah", lat=33.910)], [jnah])

        assert rows == []

    def test_the_same_name_far_away_in_another_district_is_another_place(self) -> None:
        hamra = listed(101, "Hamra", lat=33.9, district="South")

        rows, _ = merge([found(1, "El Hamra", lat=33.3)], [hamra])

        assert [(row.name, row.district) for row in rows] == [("El Hamra", "North")]

    def test_a_village_named_like_another_district_is_kept(self) -> None:
        south = listed(2, "South", lat=33.9, district="South", whole_district=True)

        rows, _ = merge([found(1, "South", lat=33.9)], [south])

        assert [(row.name, row.district) for row in rows] == [("South", "North")]

    def test_one_place_drawn_twice_is_listed_once_as_the_bigger_kind(self) -> None:
        town = found(9, "Ain Baal", lat=33.900, kind="town")
        quarter = found(3, "Ain Baal", lat=33.905, kind="neighbourhood")

        rows, report = merge([quarter, town], [])

        assert [(row.osm_id, row.kind) for row in rows] == [(9, "town")]
        assert report.left_out == {"on the map twice": 1}

    def test_two_places_with_one_name_in_a_district_are_both_left_out(self) -> None:
        """Asking "which one?" would show the client the same name twice."""
        rows, report = merge(
            [found(1, "Mazraa", lat=33.3), found(2, "El Mazraa", lat=33.9), found(3, "Ain Baal")],
            [],
        )

        assert [row.name for row in rows] == ["Ain Baal"]
        assert report.name_twice == [("Mazraa", "North")]

    def test_the_same_name_in_two_districts_stays_twice(self) -> None:
        rows, _ = merge([found(1, "Mazraa"), found(2, "Mazraa", district="South")], [])

        assert [(row.name, row.district) for row in rows] == [
            ("Mazraa", "North"),
            ("Mazraa", "South"),
        ]

    def test_a_places_own_name_is_never_another_places_other_spelling(self) -> None:
        """Else the client could not choose between them by name."""
        town = found(1, "Ain Baal", kind="town", other_names=("Ain", "Mazraa"))
        village = found(2, "El Ain")
        far = [found(3, "Mazraa", lat=33.3), found(4, "Mazraa", lat=33.6)]

        rows, _ = merge([town, village, *far], [])

        assert {row.name: row.other_names for row in rows} == {"Ain Baal": (), "El Ain": ()}

    def test_a_name_that_is_a_far_places_other_spelling_is_nobodys(self) -> None:
        """Typed in Arabic, both are written alike: code can't know which one is meant."""
        village = found(1, "Boutmeh", lat=33.9, other_names=("بطمة", "Boutme"))
        suburb = found(2, "البطمة", lat=33.6, kind="suburb")

        rows, report = merge([suburb, village], [])

        assert [(row.name, row.other_names) for row in rows] == [("Boutmeh", ("Boutme",))]
        assert report.name_twice == [("البطمة", "North")]

    def test_a_place_left_out_still_makes_its_other_spellings_nobodys(self) -> None:
        """Two far points, both راشكيدا: leaving one out doesn't make the name clear."""
        one = found(1, "Rachkida", lat=33.9, other_names=("راشكيدا",))
        other = found(2, "Rachkidde", lat=33.6, other_names=("راشكيدا", "Rachkida"))

        rows, _ = merge([one, other], [])

        assert [(row.name, row.other_names) for row in rows] == [("Rachkidde", ())]

    def test_a_spelling_shared_by_two_far_places_is_nobodys(self) -> None:
        north = found(1, "Kfar Zeina", lat=33.9, other_names=("Kharayeb",))
        south = found(2, "Ain Baal", lat=33.3, other_names=("Kharayeb", "Ain Ba'al el Fawqa"))

        rows, _ = merge([north, south], [])

        assert {row.name: row.other_names for row in rows} == {
            "Kfar Zeina": (),
            "Ain Baal": ("Ain Ba'al el Fawqa",),
        }

    def test_another_spelling_belongs_to_the_bigger_place(self) -> None:
        town = found(1, "Ain Baal", kind="town", other_names=("Ain",))
        village = found(2, "Kfar Zeina", other_names=("Ain", "Kfar Zayna"))

        rows, _ = merge([village, town], [])

        assert {row.name: row.other_names for row in rows} == {
            "Ain Baal": ("Ain",),
            "Kfar Zeina": ("Kfar Zayna",),
        }


class TestBuildingAgain:
    def test_a_place_keeps_its_id_and_takes_the_maps_new_details(self) -> None:
        earlier = [Row(1004, "Kfar Zena", "North", (), "village", point(33.1), 7)]

        rows, _ = merge([found(7, "Kfar Zeina"), found(8, "Ain Baal")], [], earlier)

        assert [(row.id, row.name, row.point) for row in rows] == [
            (1004, "Kfar Zeina", point(33.9)),
            (1005, "Ain Baal", point(33.9)),
        ]

    def test_a_place_the_map_drew_again_keeps_its_id(self) -> None:
        earlier = [Row(1004, "Kfar Zeina", "North", (), "village", point(33.9), 7)]

        rows, _ = merge([found(99, "Kfar Zeina")], [], earlier)

        assert [(row.id, row.osm_id) for row in rows] == [(1004, 99)]

    def test_a_place_the_map_dropped_stays_listed(self) -> None:
        """An id in use is never changed or reused: a conversation may point at it."""
        earlier = [Row(1004, "Kfar Zeina", "North", (), "village", point(33.9), 7)]

        rows, _ = merge([found(8, "Ain Baal")], [], earlier)

        assert [(row.id, row.name) for row in rows] == [(1004, "Kfar Zeina"), (1005, "Ain Baal")]


HAND_FILE = """\
# A comment.
id,area,district,other_names,whole,ref_lat,ref_lon
1,North,North,Nord,1,33.90000,35.50000
2,South,South,Saida,1,33.30000,35.50000
101,Hamra,North,الحمرا,0,33.90000,35.50000
"""


def write_answer(folder: Path) -> None:
    answer = {
        "osm3s": {"timestamp_osm_base": "2026-11-14T08:00:00Z"},
        "elements": [
            district("Nord"),
            node(11, "El Hamra", lat=33.91),
            node(12, "Kfar Zeina", lat=33.95, name_ar="كفر زينا"),
            district("South"),
            node(13, "Ain Baal", lat=33.31, kind="town"),
        ],
    }
    (folder / "places.json").write_text(json.dumps(answer), encoding="utf-8")


class TestTheCommand:
    def test_it_writes_what_the_map_adds_with_the_credit(self, tmp_path: Path) -> None:
        (tmp_path / "areas.csv").write_text(HAND_FILE, encoding="utf-8")
        write_answer(tmp_path)
        target = tmp_path / "areas_osm.csv"

        rows, report = build_areas.build(tmp_path / "places.json", tmp_path / "areas.csv", target)

        assert [
            (a["id"], a["name"], a["district"], a["other_names"]) for a in read_areas(target)
        ] == [
            (1000, "Kfar Zeina", "North", ["كفر زينا"]),
            (1001, "Ain Baal", "South", []),
        ]
        assert all(not area["whole_district"] for area in read_areas(target))
        assert len(rows) == 2
        assert report.left_out == {"already hand-written": 1}
        text = target.read_text(encoding="utf-8")
        assert "© OpenStreetMap contributors" in text
        assert "Open Database License" in text
        assert "as of 2026-11-14" in text

    def test_building_twice_gives_the_same_file(self, tmp_path: Path) -> None:
        (tmp_path / "areas.csv").write_text(HAND_FILE, encoding="utf-8")
        write_answer(tmp_path)
        target = tmp_path / "areas_osm.csv"

        build_areas.build(tmp_path / "places.json", tmp_path / "areas.csv", target)
        first = target.read_bytes()
        build_areas.build(tmp_path / "places.json", tmp_path / "areas.csv", target)

        assert target.read_bytes() == first

    def test_it_says_what_it_did_and_checks_the_hand_written_centres(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "areas.csv").write_text(HAND_FILE, encoding="utf-8")
        write_answer(tmp_path)
        arguments = ["--folder", tmp_path, "--areas", tmp_path / "areas.csv"]
        arguments += ["--target", tmp_path / "areas_osm.csv", "--check"]
        monkeypatch.setattr("sys.argv", ["build_areas", *map(str, arguments)])

        build_areas.main()

        said = capsys.readouterr().out
        assert "2 places written" in said
        assert "left out, already hand-written: 1" in said
        assert "101 Hamra: 1.11 km from the map's" in said
        assert "1 North: not on the map" in said

    def test_it_needs_the_download(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="fetch_osm_places"):
            build_areas.build(
                tmp_path / "places.json", tmp_path / "areas.csv", tmp_path / "out.csv"
            )


class TestTheDownload:
    def test_it_asks_two_questions_and_says_nothing_about_us(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TH-58: the map service learns only that someone asked for Lebanon's places."""
        sent: list[Any] = []

        class Answer:
            def __enter__(self) -> "Answer":
                return self

            def __exit__(self, *details: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"elements": []}'

        def fake_urlopen(request: Any, timeout: float) -> Answer:
            sent.append(request)
            return Answer()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        monkeypatch.setattr("sys.argv", ["fetch_osm_places", "--folder", str(tmp_path)])

        fetch_osm_places.main()

        assert sorted(path.name for path in tmp_path.iterdir()) == [
            "boundaries.json",
            "places.json",
        ]
        assert {request.full_url for request in sent} == {fetch_osm_places.OVERPASS_URL}
        said = " ".join(
            [request.data.decode() + " " + str(request.header_items()) for request in sent]
        ).lower()
        assert "dawalink" not in said
        assert "@" not in said
        assert "%40" not in said

    def test_the_question_names_only_place_kinds_we_read(self) -> None:
        assert fetch_osm_places.PLACE_KINDS.split("|") == list(osm_places.KINDS)
