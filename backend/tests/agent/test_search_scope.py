import pytest

from dawalink.agent import context, state
from dawalink.agent.llm.scripted import call, reply
from dawalink.agent.state import SearchArea, SearchScope
from dawalink.db.models import Conversation
from tests.agent.conftest import Scene

QUESTION = "Where should the pharmacy be: nearest, in an area, or anywhere? I don't know is fine."


@pytest.mark.parametrize("tool", ["find_options", "plan_basket"])
def test_missing_scope_blocks_availability_before_routing_but_not_catalog(
    scene: Scene, tool: str
) -> None:
    scene.stock()
    args = (
        {"product_ids": [str(scene.augmentin)]}
        if tool == "find_options"
        else {"items": [{"product_id": str(scene.augmentin)}]}
    )
    scene.tool_turn().state.search_scope = SearchScope()
    before = list(scene.routing.asked)
    blocked = scene.tool(tool, **args)
    assert blocked["error_code"] == "SEARCH_SCOPE_REQUIRED"
    assert scene.routing.asked == before
    assert scene.tool("search_catalog", query="Augmentin")["ok"]
    assert scene.world.one("SELECT count(*) AS n FROM proposals").n == 0


def test_same_turn_question_flag_does_not_allow_search(scene: Scene) -> None:
    scene.stock()
    result = scene.turn(
        call("find_options", product_ids=[str(scene.augmentin)], sort="nearest"),
        reply(QUESTION, case_notes={"questions_asked": True}),
        text="Augmentin 1g, seven days, tomorrow",
    )
    assert result.text == QUESTION
    assert scene.tool_calls(result) == [("find_options", False, "SEARCH_SCOPE_REQUIRED")]
    saved = scene.conversation().case_state
    assert state.load(saved).search_scope.kind == "unanswered"
    assert state.load(saved).scope_question_seq == result.message_seq


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Nearest to me", "nearest"),
        ("Anywhere", "anywhere"),
        ("I don't know", "nearest"),
        ("ما بعرف", "nearest"),
        ("Today, seven days", "nearest"),  # Ask-once policy: skipped where uses the origin.
    ],
)
def test_answer_is_remembered_without_repeating_the_question(
    scene: Scene, answer: str, expected: str
) -> None:
    scene.turn(reply(QUESTION, case_notes={"questions_asked": True}), text="Augmentin please")
    scene.say(answer)
    loaded = context.load(scene.world.tx(), scene.chat)
    assert loaded is not None
    assert loaded.case_state.search_scope.kind == expected
    # The actual answer unlocks a search in this same turn, without another question.
    acknowledged = "ما في مخزون معروض." if answer == "ما بعرف" else "No listed stock."
    result = scene.turn(
        call("find_options", product_ids=[str(scene.augmentin)]),
        reply(acknowledged),
        text=None,
    )
    assert scene.tool_calls(result) == [("find_options", True, None)]
    scene.say("Two boxes please")
    later = context.load(scene.world.tx(), scene.chat)
    assert later is not None
    assert later.case_state.search_scope.kind == expected
    assert state.load(scene.conversation().case_state).search_scope.kind == expected


def test_flag_without_actual_scope_question_cannot_unlock_search(scene: Scene) -> None:
    scene.turn(reply("Which medicine?", case_notes={"questions_asked": True}), text="Hello")
    result = scene.turn(
        call("find_options", product_ids=[str(scene.augmentin)]),
        reply(QUESTION),
        text="Augmentin, seven days, today",
    )
    assert scene.tool_calls(result) == [("find_options", False, "SEARCH_SCOPE_REQUIRED")]


def test_worker_without_client_answer_keeps_scope_unanswered(scene: Scene) -> None:
    scene.turn(reply(QUESTION), text="Augmentin please")
    loaded = context.load(scene.world.tx(), scene.chat, followup=True)
    assert loaded is not None
    assert loaded.case_state.search_scope.kind == "unanswered"


@pytest.mark.parametrize("text", ["Nearest to me", "Anywhere", "in Beirut"])
def test_supplied_scope_allows_first_search_without_clarification(scene: Scene, text: str) -> None:
    # No stock: a simple reply suffices, so this tests the search gate rather than cards.
    result = scene.turn(
        call("find_options", product_ids=[str(scene.augmentin)]),
        reply("No listed stock."),
        text="Augmentin, seven days, today. " + text,
    )
    assert scene.tool_calls(result) == [("find_options", True, None)]
    assert state.load(scene.conversation().case_state).search_scope.kind != "unanswered"


def test_changed_area_scope_replaces_old_filter_without_moving_origin(scene: Scene) -> None:
    scene.turn(reply("Understood."), text="Augmentin in Saida or Beirut")
    scene.turn(reply("Understood."), text="Beirut only please")
    saved = state.load(scene.conversation().case_state)
    assert saved.search_scope == SearchScope(kind="areas", areas=[SearchArea(place="Beirut")])
    origin = scene.world.session.get_one(Conversation, scene.chat).loc_area_id
    turn = scene.tool_turn()
    turn.state = saved
    # Old model arguments cannot widen the new client choice back to Saida.
    response = scene.tool("find_options", product_ids=[scene.augmentin], areas=[{"place": "Saida"}])
    assert response["ok"]
    assert response["searched_in"] == ["Beirut"]
    assert scene.world.session.get_one(Conversation, scene.chat).loc_area_id == origin
    scene.turn(reply("Understood."), text="Actually nearest to me")
    scene.tool_turn().state = state.load(scene.conversation().case_state)
    assert (
        scene.tool("find_options", product_ids=[scene.augmentin], areas=[{"place": "Beirut"}])[
            "searched_in"
        ]
        == []
    )


def test_submitted_request_uses_its_form_without_a_new_scope_question(scene: Scene) -> None:
    _, thread = scene.start_request()
    result = scene.turn(
        call("plan_basket", items=[{"product_id": str(scene.augmentin)}]),
        reply("No listed stock."),
        text=None,
        conversation=thread,
    )
    assert scene.tool_calls(result) == [("plan_basket", True, None)]
