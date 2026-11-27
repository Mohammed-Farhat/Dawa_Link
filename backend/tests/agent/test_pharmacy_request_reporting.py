"""Repeated keep-looking requests reuse contacts and cannot claim new outreach."""

import json

from dawalink.agent.llm import ToolResults
from dawalink.agent.llm.scripted import call, reply
from dawalink.agent.turn import Status
from tests.agent.conftest import Scene


def test_keep_looking_reports_existing_contacts_without_duplicates(scene: Scene) -> None:
    scene.stock(days_left=200)
    for latitude in (33.897, 33.898):
        pharmacy = scene.world.make.pharmacy(lat=latitude, lon=35.483)
        scene.stock(pharmacy_id=pharmacy, days_left=200)
    watch = scene.tool("create_watch", product_id=scene.augmentin)
    ask = call("request_early_release", claim_id=watch["watch_id"])
    first = scene.turn(ask, reply("I asked 3 pharmacies to release stock."))
    assert first.status is Status.DONE
    assert "grounding" not in scene.run(first).guardrails

    truthful = (
        "The same 3 pharmacies have already been asked; "
        "no additional pharmacies were contacted. Your watch is still running."
    )
    for _ in range(2):
        repeated = scene.turn(
            ask,
            reply("I've asked 3 more pharmacies to release stock."),
            reply(truthful),
            text="Please keep looking for the same Augmentin.",
        )
        assert repeated.status is Status.DONE
        assert repeated.text == truthful
        assert scene.run(repeated).guardrails == ["grounding"]
        tool_results = scene.model.seen[1].messages[-1]
        assert isinstance(tool_results, ToolResults)
        reported = json.loads(tool_results.results[0].content)
        assert (reported["asked"], reported["newly_asked"], reported["already_asked"]) == (3, 0, 3)
        assert scene.world.one("SELECT count(*) AS n FROM claims").n == 1
        assert scene.world.one("SELECT count(*) AS n FROM early_release_requests").n == 1
        assert scene.world.one("SELECT count(*) AS n FROM early_release_asks").n == 3
        assert scene.world.one("SELECT count(*) AS n FROM orders").n == 0


def test_persistent_false_contact_claim_falls_back_safely(scene: Scene) -> None:
    scene.stock(days_left=200)
    watch = scene.tool("create_watch", product_id=scene.augmentin)
    ask = call("request_early_release", claim_id=watch["watch_id"])
    scene.turn(ask, reply("I asked one pharmacy to release stock."))
    misleading = "I contacted another pharmacy."
    result = scene.turn(ask, reply(misleading), reply(misleading), text="Please keep looking.")
    assert result.text != misleading
    assert scene.run(result).outcome == "guardrail_blocked"
    assert scene.world.one("SELECT count(*) AS n FROM early_release_asks").n == 1
    assert scene.world.one("SELECT count(*) AS n FROM orders").n == 0
