import pytest
from pydantic import ValidationError

from dawalink.agent import scope, state
from dawalink.agent.state import CaseNotes, CaseState, SearchArea, SearchScope
from dawalink.domain.places import Place

PLACES = [
    Place(1, "Beirut", "Beirut", ("بيروت",), True),
    Place(2, "Saida", "Saida", ("Sidon", "صيدا"), True),
    Place(3, "Hamra", "Beirut"),
    Place(4, "Hamra", "Nabatieh"),
]


@pytest.mark.parametrize(
    ("text", "kind", "names"),
    [
        ("Augmentin 1g, seven days, tomorrow", None, []),
        ("I am in Beirut", None, []),
        ("I live in Beirut", None, []),
        ("I am currently in Beirut", None, []),
        ("ana bel Hamra", None, []),
        ("انا ببيروت", None, []),
        ("I want the nearest pharmacy", "nearest", []),
        ("I don't know where", "nearest", []),
        ("I need Augmentin near my home", "nearest", []),
        ("El a2rab la ele, please", "nearest", []),
        ("الأقرب إلي", "nearest", []),
        ("anywhere please", "anywhere", []),
        ("Just find it", "anywhere", []),
        ("وين ما كان", "anywhere", []),
        ("Concor today in Beirut", "areas", ["Beirut"]),
        ("Saida or Beirut", "areas", ["Saida", "Beirut"]),
        ("Beirut only please", "areas", ["Beirut"]),
        ("ببيروت", "areas", ["بيروت"]),
        ("in Atlantis", "areas", ["Atlantis"]),
    ],
)
def test_scope_is_not_inferred_from_a_saved_origin_or_missing_where(
    text: str, kind: str | None, names: list[str]
) -> None:
    result = scope.explicit_scope(text, PLACES)
    assert (result.kind if result else None) == kind
    assert ([a.place for a in result.areas] if result else []) == names


def test_scope_round_trips_and_model_notes_cannot_invent_it() -> None:
    known = CaseState(search_scope=SearchScope(kind="areas", areas=[SearchArea(place="Beirut")]))
    assert state.load(state.dump(known)).search_scope == known.search_scope
    assert (
        state.load({"preference": "nearest", "questions_asked": True}).search_scope.kind
        == "unanswered"
    )
    with pytest.raises(ValidationError):
        CaseNotes.model_validate({"search_scope": {"kind": "anywhere"}})


@pytest.mark.parametrize(
    "text",
    [
        "Where should the pharmacy be? Nearest, a named area, or anywhere?",
        "وين بدك الصيدلية؟ الأقرب أو بأي منطقة؟",
        "Which area should I search?",
    ],
)
def test_actual_scope_questions_are_recognized(text: str) -> None:
    assert scope.asks_scope(text)
    assert not scope.asks_scope("Which medicine?")


def test_district_qualifies_an_area_instead_of_widening_the_search() -> None:
    assert scope.explicit_scope("in Hamra in Beirut", PLACES) == SearchScope(
        kind="areas", areas=[SearchArea(place="Hamra", district="Beirut")]
    )
