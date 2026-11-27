from datetime import timedelta

import pytest

from dawalink.agent import context
from dawalink.agent.llm import LLMRefused
from dawalink.agent.llm.scripted import call, reply
from tests.agent.conftest import Scene
from tests.agent.test_cards import proposal_from
from tests.db.factories import TODAY


@pytest.mark.parametrize(
    ("correction", "old_offset", "new_offset"),
    [
        ("today instead of tomorrow", 1, 0),
        ("No, I can collect today instead of tomorrow", 1, 0),
        ("لا، بقدر اجي اليوم بدل بكرا", 1, 0),
        ("tomorrow instead of today", 0, 1),
    ],
)
@pytest.mark.parametrize("card_offset", [0, 1])
def test_corrected_pickup_is_saved_and_guards_cards_on_a_later_turn(
    scene: Scene, correction: str, old_offset: int, new_offset: int, card_offset: int
) -> None:
    old_day = TODAY + timedelta(days=old_offset)
    new_day = TODAY + timedelta(days=new_offset)
    initial = "today" if old_offset == 0 else "tomorrow"
    scene.turn(reply("Which medicine?"), text=f"I want pickup {initial}")
    assert scene.conversation().case_state["client_pickup_day"] == str(old_day)

    acknowledgement = "تمام، أي دواء بدك؟" if "اليوم" in correction else "Which medicine?"
    scene.turn(reply(acknowledgement), text=correction)
    saved = scene.conversation().case_state
    assert saved["client_pickup_day"] == str(new_day)
    assert saved["pickup_day"] == str(new_day)

    # The next message has no date. Even conflicting model notes must not restore
    # the old client constraint used by the guard.
    scene.turn(
        reply("Which medicine?", case_notes={"pickup_day": str(old_day)}), text="One box please"
    )
    box = scene.stock()
    result = scene.turn(
        call(
            "propose_reservation",
            listing_id=str(box),
            pickup_day=str(TODAY + timedelta(days=card_offset)),
        ),
        proposal_from(scene),
        LLMRefused("cannot repair"),
        text="I need Augmentin",
    )
    assert scene.conversation().case_state["client_pickup_day"] == str(new_day)
    assert bool(result.proposal_ids) == (card_offset == new_offset)
    assert ("pickup_day" in scene.run(result).guardrails) == (card_offset != new_offset)
    assert scene.world.one("SELECT count(*) AS n FROM orders").n == 0


@pytest.mark.parametrize(
    "text",
    [
        "Maybe today instead of tomorrow",
        "Can I collect today instead of tomorrow?",
        "today or tomorrow",
        "ممكن اجي اليوم بدل بكرا؟",
        "ما بقدر اجي اليوم بدل بكرا",
    ],
)
def test_uncertain_pickup_revision_does_not_overwrite_saved_client_date(
    scene: Scene, text: str
) -> None:
    scene.turn(reply("Which medicine?"), text="I want pickup tomorrow")
    scene.say(text)
    loaded = context.load(scene.world.tx(), scene.chat)
    assert loaded is not None
    assert loaded.case_state.client_pickup_day == TODAY + timedelta(days=1)
    assert loaded.case_state.pickup_day == TODAY + timedelta(days=1)
