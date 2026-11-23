"""Search by a typed name (docs/03 CS-6, decision log BLD-D40 and BLD-D42): every
medicine in stock the name stands for, from its first letter. A medicine nobody has is
not shown."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from dawalink.db.models import ProductIngredient
from tests.api.conftest import Api, code_of


@dataclass
class Shelf:
    api: Api
    http: TestClient
    headers: dict[str, str]
    pharmacy: uuid.UUID
    panadol: uuid.UUID
    extra: uuid.UUID
    advance: uuid.UUID  # in the catalog, in no pharmacy

    def search(self, q: str, **more: Any) -> Any:
        return self.http.post(
            "/api/v1/listings/search-by-name", json={"q": q} | more, headers=self.headers
        )

    def names(self, q: str, **more: Any) -> list[str]:
        return [group["product"]["name"] for group in self.search(q, **more).json()["groups"]]


@pytest.fixture
def shelf(api: Api) -> Shelf:
    """Three Panadols in the catalog, two of them on a shelf; and another medicine whose
    name starts the same way. The assistant is switched off: search never needs it."""
    make = api.world.make
    client = api.client()
    pharmacy = make.pharmacy(name="Hamra Pharmacy", lat=33.897, lon=35.484)
    panadol = make.product(moph_name="PANADOL", search_name="panadol", dosage_text="500mg")
    extra = make.product(moph_name="PANADOL EXTRA", search_name="panadol extra")
    advance = make.product(moph_name="PANADOL ADVANCE", search_name="panadol advance")
    panderm = make.product(moph_name="PANDERM", search_name="panderm")
    for product in (panadol, extra, panderm):
        make.item(pharmacy_id=pharmacy, product_id=product, days_left=60, qty_on_hand=4)
    return Shelf(
        api, api.http(assistant=False), api.token(client), pharmacy, panadol, extra, advance
    )


class TestWhatANameFinds:
    def test_a_name_shows_every_medicine_in_stock_that_carries_it(self, shelf: Shelf) -> None:
        found = shelf.search("panadol").json()

        assert [group["product"]["name"] for group in found["groups"]] == [
            "PANADOL",
            "PANADOL EXTRA",
        ]
        assert found["closest"] is False
        first = found["groups"][0]
        assert (first["total_found"], first["by_ingredient"]) == (1, False)
        assert first["items"][0]["pharmacy"]["name"] == "Hamra Pharmacy"

    def test_a_medicine_nobody_stocks_is_not_shown_at_all(self, shelf: Shelf) -> None:
        """BLD-D42: search is of what is in stock. Panadol Advance is in the catalog and
        in no pharmacy."""
        found = shelf.search("panadol").json()

        assert "not_in_stock" not in found
        assert "PANADOL ADVANCE" not in shelf.search("panadol").text
        assert str(shelf.advance) not in {group["product"]["id"] for group in found["groups"]}

    def test_one_letter_finds_the_medicines_in_stock_that_start_with_it(self, shelf: Shelf) -> None:
        """BLD-D42: "p" is the start of a name's word, never a guess at a spelling."""
        make = shelf.api.world.make
        other = make.product(moph_name="CONCOR 5", search_name="concor 5")
        make.item(pharmacy_id=shelf.pharmacy, product_id=other, days_left=60, qty_on_hand=4)

        assert shelf.names("p") == ["PANADOL", "PANADOL EXTRA", "PANDERM"]
        assert shelf.names("pa") == ["PANADOL", "PANADOL EXTRA", "PANDERM"]
        assert shelf.names("c") == ["CONCOR 5"]
        # The start of any word of the name.
        assert shelf.names("ex") == ["PANADOL EXTRA"]
        assert shelf.names("%") == []

    def test_a_name_that_begins_with_the_letters_comes_first(self, shelf: Shelf) -> None:
        """Found in the browser on the real catalog: "p" listed "Micardis Plus" before
        the Panadols, because the list was in the order of the alphabet."""
        make = shelf.api.world.make
        later_word = make.product(moph_name="ASPICOT PLUS", search_name="aspicot plus")
        make.item(pharmacy_id=shelf.pharmacy, product_id=later_word, days_left=60, qty_on_hand=4)

        assert shelf.names("p") == ["PANADOL", "PANADOL EXTRA", "PANDERM", "ASPICOT PLUS"]

    def test_only_pharmacies_open_now_when_asked(self, shelf: Shelf) -> None:
        make = shelf.api.world.make
        # It is 10:00 in the test: this one opens in the evening.
        evenings = {weekday: [("18:00", "23:00")] for weekday in range(7)}
        closed = make.pharmacy(name="Night Pharmacy", lat=33.9, lon=35.5, hours=evenings)
        make.item(pharmacy_id=closed, product_id=shelf.panadol, days_left=60, qty_on_hand=4)

        (everyone, *_) = shelf.search("panadol").json()["groups"]
        (open_ones, *_) = shelf.search("panadol", open_now=True).json()["groups"]

        assert everyone["total_found"] == 2
        assert [item["pharmacy"]["name"] for item in open_ones["items"]] == ["Hamra Pharmacy"]

    def test_a_misspelled_name_is_the_closest_brand_and_says_so(self, shelf: Shelf) -> None:
        """ "pandol": Panadol, not Panderm, although Panderm shares more of its letters'
        order. The page is told it is a closest match, and what else it could be."""
        found = shelf.search("pandol").json()

        assert [group["product"]["name"] for group in found["groups"]] == [
            "PANADOL",
            "PANADOL EXTRA",
        ]
        assert found["closest"] is True
        assert found["did_you_mean"] == ["PANDERM"]

    @pytest.mark.parametrize("same_medicine", [True, False])
    def test_a_medicine_nobody_stocks_is_never_taken_for_a_misspelling(
        self, shelf: Shelf, same_medicine: bool
    ) -> None:
        """Review B#1: "concor" is written right, is in the catalog, and is on no shelf;
        B-Cor is, and shares a word with it. The page says nobody has Concor. It never
        says "the closest name is B-Cor" with [Reserve]: another brand is shown only by the
        assistant, with "ask the pharmacist first" (R-S4, INV-26). The same with a B-Cor
        of another strength: the client named a medicine, and it is that one or nothing."""
        make = shelf.api.world.make
        key = "bisoprolol=5mg | tablet | C07AB07"
        make.product(moph_name="CONCOR", search_name="concor", equivalence_key=key)
        other = make.product(
            moph_name="B-COR",
            search_name="b cor",
            equivalence_key=key if same_medicine else "bisoprolol=2.5mg | tablet | C07AB07",
        )
        make.item(pharmacy_id=shelf.pharmacy, product_id=other, days_left=60, qty_on_hand=4)

        found = shelf.search("concor").json()

        assert (found["groups"], found["closest"], found["did_you_mean"]) == ([], False, [])

    def test_a_named_medicine_in_stock_is_shown_alone(self, shelf: Shelf) -> None:
        """When a pharmacy has Concor, Concor is what the name finds, and only Concor."""
        make = shelf.api.world.make
        key = "bisoprolol=5mg | tablet | C07AB07"
        concor = make.product(moph_name="CONCOR", search_name="concor", equivalence_key=key)
        other = make.product(moph_name="B-COR", search_name="b cor", equivalence_key=key)
        for product in (concor, other):
            make.item(pharmacy_id=shelf.pharmacy, product_id=product, days_left=60, qty_on_hand=4)

        found = shelf.search("concor").json()

        assert [group["product"]["name"] for group in found["groups"]] == ["CONCOR"]
        assert (found["closest"], found["did_you_mean"]) == (False, [])

    def test_a_misspelling_never_leads_to_another_brand_of_what_it_means(
        self, shelf: Shelf
    ) -> None:
        """ "zandol" is a misspelling of Zanadol, which nobody stocks. Zadol, in stock, is
        the closest name on a shelf, and another brand of Zanadol: it is not offered,
        neither as the closest name nor as "Did you mean…?"."""
        make = shelf.api.world.make
        key = "zanamol=10mg | tablet | X01"
        make.product(moph_name="ZANADOL", search_name="zanadol", equivalence_key=key)
        other = make.product(moph_name="ZADOL", search_name="zadol", equivalence_key=key)
        make.item(pharmacy_id=shelf.pharmacy, product_id=other, days_left=60, qty_on_hand=4)

        found = shelf.search("zandol").json()

        assert (found["groups"], found["closest"], found["did_you_mean"]) == ([], False, [])

    def test_a_misspelling_finds_the_closest_name_in_stock_when_it_is_another_medicine(
        self, shelf: Shelf
    ) -> None:
        """The same misspelling, with a Zadol that is not Zanadol: it is offered as the
        closest name, and said to be."""
        make = shelf.api.world.make
        make.product(
            moph_name="ZANADOL", search_name="zanadol", equivalence_key="zanamol=10mg | tablet"
        )
        other = make.product(
            moph_name="ZADOL", search_name="zadol", equivalence_key="zadomol=5mg | tablet"
        )
        make.item(pharmacy_id=shelf.pharmacy, product_id=other, days_left=60, qty_on_hand=4)

        found = shelf.search("zandol").json()

        assert [group["product"]["name"] for group in found["groups"]] == ["ZADOL"]
        assert found["closest"] is True

    def test_a_strength_moves_the_medicine_that_has_it_first(self, shelf: Shelf) -> None:
        assert shelf.names("panadol extra 500")[0] == "PANADOL EXTRA"
        assert shelf.names("panadol 500mg")[0] == "PANADOL"

    def test_a_name_nothing_looks_like_finds_nothing(self, shelf: Shelf) -> None:
        found = shelf.search("zzzzqq").json()

        assert (found["groups"], found["did_you_mean"]) == ([], [])

    def test_a_medicine_is_found_by_what_it_contains(self, shelf: Shelf) -> None:
        with shelf.api.world.as_owner():
            shelf.api.world.session.add(
                ProductIngredient(
                    product_id=shelf.panadol,
                    position=1,
                    name="Paracetamol",
                    name_normalized="paracetamol",
                )
            )
            shelf.api.world.session.flush()

        found = shelf.search("paracetamol").json()

        assert [(g["product"]["name"], g["by_ingredient"]) for g in found["groups"]] == [
            ("PANADOL", True)
        ]

    def test_a_controlled_medicine_is_never_among_them(self, shelf: Shelf) -> None:
        """INV-6, by this path too."""
        make = shelf.api.world.make
        hidden = make.product(
            moph_name="PANADOL NIGHT", search_name="panadol night", controlled=True
        )
        make.item(pharmacy_id=shelf.pharmacy, product_id=hidden, days_left=60, qty_on_hand=4)

        found = shelf.search("panadol").json()

        assert "PANADOL NIGHT" not in {group["product"]["name"] for group in found["groups"]}
        assert "PANADOL NIGHT" not in shelf.names("p")


class TestTheSameRulesAsTheMedicinesOwnPage:
    def test_boxes_that_expire_too_early_are_said_not_hidden(self, shelf: Shelf) -> None:
        """R-F4: the medicine is in stock, and none of its boxes lasts 90 days."""
        (group, *_) = shelf.search("panadol", days_of_use=90).json()["groups"]

        assert (group["items"], group["total_found"]) == ([], 0)
        assert group["no_match"] is not None

    def test_each_medicine_shows_its_best_boxes_and_counts_them_all(self, shelf: Shelf) -> None:
        make = shelf.api.world.make
        for number in range(4):
            other = make.pharmacy(name=f"Pharmacy {number}", lat=33.9 + number / 100, lon=35.5)
            make.item(pharmacy_id=other, product_id=shelf.panadol, days_left=60, qty_on_hand=2)

        (group, *_) = shelf.search("panadol", per_medicine=3).json()["groups"]

        assert (len(group["items"]), group["total_found"]) == (3, 5)

    def test_the_place_travels_in_the_body_and_is_never_sent_back(self, shelf: Shelf) -> None:
        answer = shelf.search("panadol", location={"lat": 34.2511, "lon": 35.6642})

        assert answer.json()["location"] == {"source": "shared", "label": "Your location"}
        # A pharmacy's own pin is public; the client's point is in no answer.
        assert "34.25" not in answer.text
        assert "35.66" not in answer.text

    def test_it_needs_a_client_and_a_letter(self, shelf: Shelf) -> None:
        nobody = shelf.http.post("/api/v1/listings/search-by-name", json={"q": "panadol"})
        empty = shelf.search("")

        assert nobody.status_code == 401
        assert (empty.status_code, code_of(empty)) == (422, "VALIDATION_ERROR")


class TestWhatASearchCosts:
    def statements(self, shelf: Shelf, q: str) -> tuple[int, Any]:
        seen: list[str] = []

        def count(*args: Any) -> None:
            seen.append(args[2])

        event.listen(shelf.api.world.connection, "before_cursor_execute", count)
        try:
            answer = shelf.search(q)
        finally:
            event.remove(shelf.api.world.connection, "before_cursor_execute", count)
        assert answer.status_code == 200
        return len(seen), answer.json()

    def test_one_letter_costs_the_same_for_thirty_medicines_as_for_three(
        self, shelf: Shelf
    ) -> None:
        """Review A#29: "p" matched up to 40 medicines and ran a whole listing search for
        each, 324 statements on the real catalog. The boxes, the hours, the travel times and
        the pharmacies are now read once for all of them."""
        make = shelf.api.world.make
        self.statements(shelf, "p")  # the first request of an app does a few things once

        few, found = self.statements(shelf, "p")
        assert len(found["groups"]) == 3
        for number in range(27):
            pharmacy = make.pharmacy(name=f"Pharmacy {number}", lat=33.9 + number / 1000, lon=35.5)
            product = make.product(moph_name=f"PILLEX {number:02d}", search_name=f"pillex {number}")
            make.item(pharmacy_id=pharmacy, product_id=product, days_left=60, qty_on_hand=2)
        many, found = self.statements(shelf, "p")

        assert len(found["groups"]) == 30
        assert many == few
        assert many < 30


class TestTheLastSearches:
    """BLD-D42: a client's last searches, kept in their account."""

    def keep(self, shelf: Shelf, q: str, headers: dict[str, str] | None = None) -> Any:
        return shelf.http.post(
            "/api/v1/me/searches", json={"q": q}, headers=headers or shelf.headers
        )

    def test_the_newest_is_first_and_a_name_is_listed_once(self, shelf: Shelf) -> None:
        for q in ("panadol", "panderm", "Panadol"):
            shelf.api.world.later(minutes=1)
            self.keep(shelf, q)

        listed = shelf.http.get("/api/v1/me/searches", headers=shelf.headers).json()

        assert listed == {"items": ["Panadol", "panderm"]}

    def test_only_eight_are_shown_and_twenty_kept(self, shelf: Shelf) -> None:
        make = shelf.api.world.make
        names = [f"zolvex{chr(97 + number)}" for number in range(25)]
        for name in names:
            make.product(moph_name=name.upper(), search_name=name)
        for name in names:
            shelf.api.world.later(minutes=1)
            self.keep(shelf, name)

        listed = shelf.http.get("/api/v1/me/searches", headers=shelf.headers).json()["items"]

        assert listed[0] == "zolvexy"
        assert len(listed) == 8
        assert shelf.api.world.one("SELECT count(*) FROM search_history") == (20,)

    def test_what_is_not_a_name_is_quietly_left_out(self, shelf: Shelf) -> None:
        for q in ("p", "<script>alert(1)</script>", "x" * 61, "70 123 456 !!"):
            assert self.keep(shelf, q).status_code == 200

        assert shelf.http.get("/api/v1/me/searches", headers=shelf.headers).json() == {"items": []}

    def test_only_a_medicine_of_the_catalog_is_kept(self, shelf: Shelf) -> None:
        """What a client types by mistake in the box is not stored (`10` TH-65): a phone
        number, a sentence, a word no medicine is called. A medicine nobody stocks is a
        medicine all the same, and a controlled one is never kept."""
        make = shelf.api.world.make
        make.product(moph_name="CONCOR 5", search_name="concor 5")
        make.product(moph_name="TRAMAL", search_name="tramal", controlled=True)

        for q in ("70 123 456", "my head hurts today", "qqzzxxvv", "tramal", "concor 5"):
            assert self.keep(shelf, q).status_code == 200

        assert shelf.http.get("/api/v1/me/searches", headers=shelf.headers).json() == {
            "items": ["concor 5"]
        }

    def test_clear_removes_them_all(self, shelf: Shelf) -> None:
        self.keep(shelf, "panadol")

        cleared = shelf.http.delete("/api/v1/me/searches", headers=shelf.headers)

        assert cleared.json() == {"items": []}
        assert shelf.api.world.one("SELECT count(*) FROM search_history") == (0,)

    def test_nobody_reads_or_clears_another_clients_searches(self, shelf: Shelf) -> None:
        self.keep(shelf, "panadol")
        other = shelf.api.token(shelf.api.client())

        seen = shelf.http.get("/api/v1/me/searches", headers=other).json()
        shelf.http.delete("/api/v1/me/searches", headers=other)

        assert seen == {"items": []}
        assert shelf.http.get("/api/v1/me/searches", headers=shelf.headers).json() == {
            "items": ["panadol"]
        }

    def test_a_search_older_than_30_days_is_purged(self, shelf: Shelf) -> None:
        self.keep(shelf, "panadol")
        shelf.api.world.later(days=31)
        self.keep(shelf, "panderm")

        # The daily clean-up, with its own database login.
        shelf.api.world.clock_tasks().run_daily_tasks()

        assert shelf.http.get("/api/v1/me/searches", headers=shelf.headers).json() == {
            "items": ["panderm"]
        }
