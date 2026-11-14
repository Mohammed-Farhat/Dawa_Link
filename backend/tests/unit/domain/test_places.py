"""Finding the area a client named (docs/04 R-S2, decision log BLD-D14)."""

import pytest

from dawalink.domain.places import Place, close, key, named

HAMRA = Place(101, "Hamra", "Beirut", ("Hamra Street", "الحمرا"))
ACHRAFIEH = Place(123, "Achrafieh", "Beirut", ("Ashrafieh",))
RAS_NABAA = Place(119, "Ras el Nabaa", "Beirut")
BAABDA = Place(12, "Baabda", "Baabda", whole_district=True)
BAABDAT = Place(177, "Baabdat", "Matn")
ARAMOUN_ALEY = Place(222, "Aramoun", "Aley")
ARAMOUN_KESERWAN = Place(300, "Aramoun", "Keserwan")
PLACES = [HAMRA, ACHRAFIEH, RAS_NABAA, BAABDA, BAABDAT, ARAMOUN_ALEY, ARAMOUN_KESERWAN]


class TestTheSimplifiedName:
    @pytest.mark.parametrize(
        "written",
        ["Hamra", "hamra", "HAMRA ", "el Hamra", "Al-Hamra", "al hamra", "Hamra."],
    )
    def test_case_article_and_punctuation_do_not_matter(self, written: str) -> None:
        assert key(written) == "hamra"

    def test_accents_and_hyphens_do_not_matter(self) -> None:
        assert key("Zahlé") == key("zahle")
        assert key("Ras-en-Nabaa") == key("Ras el Nabaa") == "rasnabaa"

    def test_arabic_script_is_kept_and_its_article_dropped(self) -> None:
        assert key("الحمرا") == key("حمرا") != ""
        # The same letter written in two ways.
        assert key("الأشرفية") == key("الاشرفيه")

    def test_a_name_that_is_only_an_article_is_left_alone(self) -> None:
        assert key("ال") == "ال"
        assert key("  ") == ""


class TestAPlaceByItsName:
    def test_any_listed_spelling_finds_it(self) -> None:
        assert named(PLACES, "el hamra") == [HAMRA]
        assert named(PLACES, "Hamra street") == [HAMRA]
        assert named(PLACES, "الحمرا") == [HAMRA]
        assert named(PLACES, "ashrafieh") == [ACHRAFIEH]

    def test_a_similar_name_is_not_the_same_place(self) -> None:
        """Baabda and Baabdat are two towns: only the exact name is accepted."""
        assert named(PLACES, "Baabda") == [BAABDA]
        assert named(PLACES, "Baabdat") == [BAABDAT]
        assert named(PLACES, "Hamr") == []

    def test_a_name_in_two_districts_gives_both_until_one_is_chosen(self) -> None:
        assert named(PLACES, "Aramoun") == [ARAMOUN_ALEY, ARAMOUN_KESERWAN]
        assert named(PLACES, "Aramoun", "keserwan") == [ARAMOUN_KESERWAN]
        assert named(PLACES, "Aramoun", "Chouf") == []

    def test_nothing_to_look_for(self) -> None:
        assert named(PLACES, " - ") == []
        assert close(PLACES, "") == []


class TestSuggestions:
    def test_another_spelling_is_suggested_not_accepted(self) -> None:
        assert named(PLACES, "Ashrafiyye") == []
        assert close(PLACES, "Ashrafiyye")[0] == ACHRAFIEH

    def test_the_most_alike_come_first_and_only_a_few(self) -> None:
        many = [Place(index, f"Kfar {index}", "Chouf") for index in range(400, 420)]

        assert [place.name for place in close([*many, BAABDAT, BAABDA], "Babda")][:2] == [
            "Baabda",
            "Baabdat",
        ]
        assert len(close(many, "Kfar 40")) == 5

    def test_an_unrelated_name_suggests_nothing(self) -> None:
        assert close(PLACES, "Timbuktu") == []
