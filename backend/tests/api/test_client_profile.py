"""What a client says about themselves (docs/03 CS-2, CS-13; docs/04 R-S2; decision log
BLD-D40): the name in parts, a birth date, a home town, and a place saved on the map."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dawalink.api.limits import Limiter
from dawalink.services import clients
from tests.api.conftest import PASSWORD, Api, code_of

NEW = {
    "email": "nour@example.com",
    "password": PASSWORD,
    "first_name": "Nour",
    "last_name": "Khoury",
    "birth_date": "1990-05-17",
    "district_id": 1,
    "accept_terms": True,
}


def field_of(answer: Any) -> Any:
    return answer.json()["error"]["details"].get("field")


@dataclass
class Person:
    api: Api
    http: TestClient
    id: uuid.UUID
    headers: dict[str, str]

    def me(self) -> Any:
        return self.http.get("/api/v1/me/profile", headers=self.headers).json()

    def change(self, **body: Any) -> Any:
        return self.http.patch("/api/v1/me/profile", json=body, headers=self.headers)

    def town_of(self, district_id: int) -> int:
        """A town of our own list inside this district."""
        (town,) = self.api.world.one(
            "SELECT id FROM areas WHERE district_id = :d AND NOT whole_district "
            "ORDER BY id LIMIT 1",
            d=district_id,
        )
        return int(town)


@pytest.fixture
def person(api: Api) -> Person:
    client = api.client(full_name="Rami Haddad")
    return Person(api, api.http(assistant=False), client, api.token(client))


class TestSigningUp:
    def test_the_name_is_kept_in_parts_and_as_one_line(self, api: Api) -> None:
        http = api.http()

        answer = http.post("/api/v1/auth/register/client", json=NEW | {"middle_name": "  Georges "})

        assert answer.status_code == 202
        assert api.world.one(
            "SELECT u.full_name, c.first_name, c.middle_name, c.last_name, c.birth_date::text "
            "FROM users u JOIN client_profiles c ON c.user_id = u.id WHERE u.email = :e",
            e=NEW["email"],
        ) == ("Nour Georges Khoury", "Nour", "Georges", "Khoury", "1990-05-17")

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"first_name": "N0ur"}, "first_name"),
            ({"last_name": "<b>Khoury</b>"}, "last_name"),
            ({"middle_name": "!!!"}, "middle_name"),
            ({"birth_date": "2999-01-01"}, "birth_date"),
            ({"birth_date": "1850-01-01"}, "birth_date"),
        ],
    )
    def test_a_name_is_letters_and_a_birth_date_is_a_real_past_day(
        self, api: Api, change: dict[str, str], field: str
    ) -> None:
        answer = api.http().post("/api/v1/auth/register/client", json=NEW | change)

        assert (answer.status_code, code_of(answer), field_of(answer)) == (
            422,
            "VALIDATION_ERROR",
            field,
        )
        assert api.world.one("SELECT count(*) FROM users WHERE email = :e", e=NEW["email"]) == (0,)

    def test_a_name_may_be_written_in_arabic(self, api: Api) -> None:
        arabic = {"first_name": "نور", "last_name": "الخوري"}

        assert api.http().post("/api/v1/auth/register/client", json=NEW | arabic).status_code == 202

    def test_a_home_town_belongs_to_the_district_chosen(self, api: Api, person: Person) -> None:
        town = person.town_of(1)
        http = api.http()

        elsewhere = http.post(
            "/api/v1/auth/register/client", json=NEW | {"district_id": 2, "home_area_id": town}
        )
        at_home = http.post("/api/v1/auth/register/client", json=NEW | {"home_area_id": town})

        assert (code_of(elsewhere), field_of(elsewhere)) == ("VALIDATION_ERROR", "home_area_id")
        assert at_home.status_code == 202
        assert api.world.one(
            "SELECT c.home_area_id FROM client_profiles c JOIN users u ON u.id = c.user_id "
            "WHERE u.email = :e",
            e=NEW["email"],
        ) == (town,)

    def test_a_place_on_the_map_is_enough_and_needs_no_district(self, api: Api) -> None:
        """The owner, 2026-11-18: where a client lives is a place on the map, or an area."""
        body = {k: v for k, v in NEW.items() if k != "district_id"}

        answer = api.http().post(
            "/api/v1/auth/register/client",
            json=body | {"home_place": {"lat": 33.897654, "lon": 35.484321}},
        )

        assert answer.status_code == 202
        assert api.world.one(
            "SELECT c.district_id, c.home_lat::text, c.home_lon::text FROM client_profiles c "
            "JOIN users u ON u.id = c.user_id WHERE u.email = :e",
            e=NEW["email"],
        ) == (None, "33.898", "35.484")

    def test_one_of_the_two_is_needed_and_a_place_is_in_lebanon(self, api: Api) -> None:
        body = {k: v for k, v in NEW.items() if k != "district_id"}
        http = api.http()

        neither = http.post("/api/v1/auth/register/client", json=body)
        abroad = http.post(
            "/api/v1/auth/register/client",
            json=body | {"home_place": {"lat": 48.8566, "lon": 2.3522}},
        )

        assert (code_of(neither), field_of(neither)) == ("VALIDATION_ERROR", "district_id")
        assert (code_of(abroad), field_of(abroad)) == ("VALIDATION_ERROR", "location")
        assert api.world.one("SELECT count(*) FROM users WHERE email = :e", e=NEW["email"]) == (0,)

    def test_a_mistake_in_the_form_answers_the_same_for_a_known_email(self, api: Api) -> None:
        """R-AU7: the form is checked before the email is looked at."""
        http = api.http()
        http.post("/api/v1/auth/register/client", json=NEW)
        wrong = {"birth_date": "2999-01-01"}

        known = http.post("/api/v1/auth/register/client", json=NEW | wrong)
        unknown = http.post(
            "/api/v1/auth/register/client", json=NEW | wrong | {"email": "new@example.com"}
        )

        assert (known.status_code, code_of(known)) == (unknown.status_code, code_of(unknown))


class TestTheTownsOfADistrict:
    def test_they_are_our_own_list_without_the_district_itself(self, person: Person) -> None:
        places = person.http.get("/api/v1/places", params={"district_id": 1}).json()

        assert places
        assert set(places[0]) == {"id", "name"}
        assert [place["name"] for place in places] == sorted(place["name"] for place in places)
        whole = person.api.world.all("SELECT id FROM areas WHERE whole_district")
        assert not {row[0] for row in whole} & {place["id"] for place in places}

    def test_a_place_named_only_in_arabic_script_is_not_in_the_lists(self, person: Person) -> None:
        """The owner, 2026-11-18: one list in two alphabets reads as a mistake."""
        with person.api.world.as_owner():
            person.api.world.connection.exec_driver_sql(
                "INSERT INTO areas (id, name, district_id, ref_lat, ref_lon) "
                "VALUES (31999, %s, 1, 33.9, 35.5)",
                ("\u0627\u0644\u062d\u0645\u0631\u0627",),
            )

        places = person.http.get("/api/v1/places", params={"district_id": 1}).json()

        assert all(place["name"].isascii() for place in places)
        assert 31999 not in {place["id"] for place in places}

    def test_a_district_nobody_knows_has_none(self, person: Person) -> None:
        assert person.http.get("/api/v1/places", params={"district_id": 999}).json() == []


class TestTheProfile:
    def test_the_name_parts_are_changed_together(self, person: Person) -> None:
        answer = person.change(first_name="Rami", middle_name="K.", last_name="El-Haddad")

        assert answer.status_code == 200
        me = answer.json()
        assert me["full_name"] == "Rami K. El-Haddad"
        assert (me["client"]["first_name"], me["client"]["middle_name"]) == ("Rami", "K.")

    def test_a_name_needs_its_first_and_last_part(self, person: Person) -> None:
        answer = person.change(first_name="Rami")

        assert (code_of(answer), field_of(answer)) == ("VALIDATION_ERROR", "last_name")
        assert person.me()["full_name"] == "Rami Haddad"

    def test_the_birth_date_is_the_clients_own_and_nobody_elses(self, person: Person) -> None:
        person.change(birth_date="1988-02-29")

        assert person.me()["client"]["birth_date"] == "1988-02-29"
        admin = person.api.world.make.user("admin", totp_secret=b"encrypted-secret")
        seen = person.http.get(
            f"/api/v1/admin/clients/{person.id}", headers=person.api.token(admin)
        ).text
        assert "1988" not in seen

    def test_changing_the_district_leaves_the_town_of_the_old_one(self, person: Person) -> None:
        town = person.town_of(1)
        person.change(district_id=1, home_area_id=town)
        assert person.me()["client"]["home_area"]["id"] == town

        moved = person.change(district_id=2).json()

        assert (moved["client"]["district"]["id"], moved["client"]["home_area"]) == (2, None)

    def test_a_town_of_another_district_is_refused(self, person: Person) -> None:
        answer = person.change(district_id=2, home_area_id=person.town_of(1))

        assert (code_of(answer), field_of(answer)) == ("VALIDATION_ERROR", "home_area_id")


class TestTheSavedPlace:
    def put(self, person: Person, lat: float, lon: float) -> Any:
        return person.http.put(
            "/api/v1/me/home-place", json={"lat": lat, "lon": lon}, headers=person.headers
        )

    def test_it_is_kept_rounded_and_shown_only_to_its_owner(self, person: Person) -> None:
        saved = self.put(person, 34.251654, 35.664321)

        assert saved.status_code == 200
        assert saved.json()["client"]["home_place_saved"] is True
        # Rounded to about 100 m before it is stored (N-43).
        assert person.api.world.one(
            "SELECT home_lat::text, home_lon::text FROM client_profiles WHERE user_id = :u",
            u=person.id,
        ) == ("34.252", "35.664")
        own = person.http.get("/api/v1/me/home-place", headers=person.headers).json()
        assert own == {"lat": 34.252, "lon": 35.664}
        # The profile itself says only that a place is saved.
        assert "34.25" not in person.http.get("/api/v1/me/profile", headers=person.headers).text

    def test_it_can_be_moved_and_forgotten(self, person: Person) -> None:
        self.put(person, 33.897, 35.484)
        self.put(person, 34.436, 35.836)
        assert person.http.get("/api/v1/me/home-place", headers=person.headers).json() == {
            "lat": 34.436,
            "lon": 35.836,
        }

        gone = person.http.delete("/api/v1/me/home-place", headers=person.headers)

        assert gone.json()["client"]["home_place_saved"] is False
        missing = person.http.get("/api/v1/me/home-place", headers=person.headers)
        assert (missing.status_code, code_of(missing)) == (404, "NOT_FOUND")

    def test_a_place_outside_lebanon_is_refused(self, person: Person) -> None:
        answer = self.put(person, 48.8566, 2.3522)

        assert (answer.status_code, code_of(answer), field_of(answer)) == (
            422,
            "VALIDATION_ERROR",
            "location",
        )

    def test_a_place_that_is_refused_costs_none_of_the_hours_tries(self, person: Person) -> None:
        person.http.app.state.locations_per_client = Limiter(1, 3600)  # type: ignore[attr-defined]

        refused = [self.put(person, 48.8566, 2.3522) for _ in range(3)]
        saved = self.put(person, 33.897, 35.484)

        assert [answer.status_code for answer in refused] == [422, 422, 422]
        assert saved.status_code == 200

    def test_moving_it_counts_for_the_hourly_limit(self, person: Person) -> None:
        """N-47: a new place can start a paid routing call."""
        person.http.app.state.locations_per_client = Limiter(2, 3600)  # type: ignore[attr-defined]

        answers = [self.put(person, 33.89 + n / 100, 35.48) for n in range(3)]

        assert [a.status_code for a in answers] == [200, 200, 429]

    def test_another_client_never_reads_it(self, person: Person) -> None:
        self.put(person, 33.897, 35.484)
        other = person.api.token(person.api.client())

        answer = person.http.get("/api/v1/me/home-place", headers=other)

        assert answer.status_code == 404


class TestWhereASearchStarts:
    """R-S2: the saved place, else the home town, else the home district."""

    def home(self, person: Person) -> clients.Home | None:
        return clients.home(person.api.world.tx(), person.id)

    def test_the_district_then_the_town_then_the_saved_place(self, person: Person) -> None:
        district = self.home(person)
        assert district is not None
        assert district.kind == "district"

        town = person.town_of(1)
        person.change(district_id=1, home_area_id=town)
        person.api.world.session.expire_all()
        named = self.home(person)
        assert named is not None
        assert (named.kind, named.location.area_id) == ("town", town)

        person.http.put(
            "/api/v1/me/home-place", json={"lat": 33.9011, "lon": 35.4799}, headers=person.headers
        )
        person.api.world.session.expire_all()
        saved = self.home(person)
        assert saved is not None
        assert saved.kind == "place"
        assert (str(saved.location.point.lat), str(saved.location.point.lon)) == (
            "33.901",
            "35.480",
        )
        # What a person or the model may be told is still a name, never the point.
        assert saved.name == named.name
        assert "33.9" not in (saved.name or "")

    def test_the_search_page_says_it_in_words(self, person: Person) -> None:
        make = person.api.world.make
        product = make.product(moph_name="PANADOL", search_name="panadol")
        pharmacy = make.pharmacy(name="Hamra Pharmacy", lat=33.897, lon=35.484)
        make.item(pharmacy_id=pharmacy, product_id=product, days_left=60, qty_on_hand=4)
        person.http.put(
            "/api/v1/me/home-place", json={"lat": 34.2511, "lon": 35.6642}, headers=person.headers
        )

        answer = person.http.post(
            "/api/v1/listings/search", json={"product_id": str(product)}, headers=person.headers
        )

        assert answer.json()["location"]["source"] == "place"
        assert "34.25" not in answer.text


class TestAClientWithAPlaceAndNoDistrict:
    """BLD-D42 (docs/09 FI-32): at sign-up a client may give a place on the map and
    nothing else. Nothing a person reads says "null" where a district would have been,
    and no district is guessed from the point."""

    def place_only(self, person: Person) -> None:
        with person.api.world.as_owner():
            person.api.world.connection.exec_driver_sql(
                "UPDATE client_profiles SET district_id = NULL, home_area_id = NULL, "
                "home_lat = 33.898, home_lon = 35.484 WHERE user_id = %s",
                (person.id,),
            )
        person.api.world.session.expire_all()

    def test_they_search_and_watch_from_the_place(self, person: Person) -> None:
        self.place_only(person)
        make = person.api.world.make
        stocked = make.product(moph_name="PANADOL", search_name="panadol")
        missing = make.product(moph_name="CONCOR 5", search_name="concor 5")
        pharmacy = make.pharmacy(name="Hamra Pharmacy", lat=33.897, lon=35.484)
        make.item(pharmacy_id=pharmacy, product_id=stocked, days_left=60, qty_on_hand=4)

        found = person.http.post(
            "/api/v1/listings/search-by-name", json={"q": "panadol"}, headers=person.headers
        )
        watch = person.http.post(
            "/api/v1/watches", json={"product_id": str(missing), "qty": 1}, headers=person.headers
        )
        profile = person.me()["client"]

        # The website says "Your saved place" for this source; no name stands in for it.
        assert found.json()["location"] == {"source": "place", "label": None}
        assert found.json()["groups"][0]["items"][0]["pharmacy"]["name"] == "Hamra Pharmacy"
        assert (watch.status_code, watch.json()["district"]) == (201, None)
        assert (profile["district"], profile["home_area"], profile["home_place_saved"]) == (
            None,
            None,
            True,
        )
        assert person.api.world.one(
            "SELECT district_id FROM client_profiles WHERE user_id = :u", u=person.id
        ) == (None,)

    def test_with_neither_a_place_nor_a_district_a_search_asks_for_one(
        self, person: Person
    ) -> None:
        self.place_only(person)
        person.http.delete("/api/v1/me/home-place", headers=person.headers)

        answer = person.http.post(
            "/api/v1/listings/search-by-name", json={"q": "panadol"}, headers=person.headers
        )

        assert (answer.status_code, code_of(answer), field_of(answer)) == (
            422,
            "VALIDATION_ERROR",
            "location",
        )
