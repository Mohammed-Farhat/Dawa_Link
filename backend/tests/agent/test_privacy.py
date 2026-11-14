"""Nothing personal or private reaches the model: one run through all 17 tools.

A scripted model uses every tool across a chat and a request, and keeps everything it was
sent: the prompts, the facts, the conversation, every tool result. That text is then
searched for what must never be in it (INV-8, INV-10, INV-23, INV-24; docs/10 TH-49):

- the client's name, email and phone, although the client typed them;
- a pharmacy's address, phone, licence and pharmacist;
- any coordinate, the client's or a pharmacy's;
- private stock.
"""

import json
import re
import uuid
from typing import Any

from dawalink.agent.llm import ModelReply, Prompt, ToolResults
from dawalink.agent.llm.scripted import call, calls, reply
from dawalink.agent.pending import PendingTurns
from dawalink.agent.tools import ALL
from dawalink.services import proposals
from tests.agent.conftest import Scene
from tests.db.factories import TODAY


def results(prompt: Prompt) -> list[dict[str, Any]]:
    last = prompt.messages[-1]
    assert isinstance(last, ToolResults)
    return [json.loads(result.content) for result in last.results]


def tap(scene: Scene, proposal_id: str) -> proposals.Executed:
    tx = scene.world.tx()
    done = proposals.execute(tx, client_id=scene.client, proposal_id=uuid.UUID(proposal_id))
    scene.world.settle(tx)
    return done


def test_all_17_tools_and_nothing_private_reaches_the_model(scene: Scene) -> None:
    world = scene.world
    with world.as_owner():
        world.connection.exec_driver_sql(
            "UPDATE products SET equivalence_key = 'amox-clav|1g|tab' WHERE id = %s",
            (scene.augmentin,),
        )
    other_brand = world.make.product(moph_name="CLAVOX 1G", equivalence_key="amox-clav|1g|tab")
    glucophage = world.make.product(moph_name="GLUCOPHAGE 850MG", search_name="glucophage 850mg")
    box = scene.stock(scene.augmentin, price_override_lbp=700_000)
    scene.stock(scene.concor)
    scene.stock(other_brand)
    private = scene.stock(glucophage, days_left=200)  # early-release zone: not visible
    seen: dict[str, Any] = {}

    # --- Turn 1, in the chat: search, options, a plan, two kinds of card ----------------
    def after_search(prompt: Prompt) -> ModelReply:
        return calls(
            ("get_equivalents", {"product_id": str(scene.augmentin)}),
            ("find_options", {"product_ids": [str(scene.augmentin), str(other_brand)]}),
            (
                "plan_basket",
                {
                    "items": [
                        {"product_id": str(scene.augmentin)},
                        {"product_id": str(scene.concor)},
                    ]
                },
            ),
        )

    def after_plan(prompt: Prompt) -> ModelReply:
        seen["plan"] = results(prompt)[2]["plans"][0]["plan_id"]
        return calls(
            (
                "propose_reservation",
                {"listing_id": str(box), "pickup_day": str(TODAY), "recommended": True},
            ),
            ("propose_plan", {"plan_id": seen["plan"]}),
        )

    def show_cards(prompt: Prompt) -> ModelReply:
        seen["reserve"] = results(prompt)[0]["proposal_id"]
        return reply("Here are your options.", proposal_ids=[seen["reserve"]])

    scene.turn(
        call("search_catalog", query="augmentin"),
        after_search,
        after_plan,
        show_cards,
        text="ana Rami Haddad, e7kine 3a 70 123 456 aw rami.haddad@example.test. "
        "ana 3and 33.8961, 35.4832. baddi augmentin",
    )
    (order,) = tap(scene, seen["reserve"]).orders  # a "reserved" card joins the history

    # --- Turn 2, in the chat: status, a cancel card, a watch, asking pharmacies ----------
    def after_watch(prompt: Prompt) -> ModelReply:
        seen["watch"] = results(prompt)[2]["watch_id"]
        return calls(
            ("request_early_release", {"claim_id": seen["watch"]}),
            (
                "prepare_request_summary",
                {"items": [{"product_id": str(scene.concor)}], "alternatives_ok": True},
            ),
            ("escalate", {"reason": "client_asked_human", "summary": "The client wants a person."}),
        )

    def show_summary(prompt: Prompt) -> ModelReply:
        seen["summary"] = results(prompt)[1]["proposal_id"]
        return reply("Start the request when you are ready.", proposal_ids=[seen["summary"]])

    scene.turn(
        calls(
            ("get_reservations", {"view": "active"}),
            ("propose_cancellation", {"order_ref": order.ref}),
            ("create_watch", {"product_id": str(glucophage)}),
        ),
        after_watch,
        show_summary,
        text="wen sar talabe? w baddi glucophage kamen",
    )
    request = tap(scene, seen["summary"]).request
    assert request is not None

    # --- Turn 3, in the request's thread: the sourcing tools -----------------------------
    def after_status(prompt: Prompt) -> ModelReply:
        item = results(prompt)[0]["items"][0]["item_id"]
        return calls(
            ("open_claim", {"request_item_id": item}),
            (
                "propose_remove_item",
                {"request_id": str(request.id), "item_id": item},
            ),
            ("schedule_followup", {"in_minutes": 30}),
        )

    scene.stock(scene.concor, units=0)
    with world.as_owner():
        world.connection.exec_driver_sql(
            "UPDATE sourcing_requests SET alternatives_ok = false WHERE id = %s", (request.id,)
        )
    agent = scene.agent(
        calls(
            ("get_request_status", {"request_id": str(request.id)}),
            (
                "propose_constraint_change",
                {"request_id": str(request.id), "allow_alternatives": True},
            ),
        ),
        after_status,
        reply("Working on your request."),
    )
    assert PendingTurns(agent).run_pending_turns() == 1

    # Every tool ran, and every call succeeded.
    used = world.all("SELECT tool, ok, error_code FROM agent_tool_calls")
    assert {row.tool for row in used} == {tool.name for tool in ALL}
    assert [(row.tool, row.error_code) for row in used if not row.ok] == []

    sent = "\n".join(model.everything_sent() for model in scene.models)
    pharmacist = world.one(
        "SELECT u.full_name, u.email, p.phone, p.license_number FROM pharmacies p "
        "JOIN users u ON u.id = p.owner_user_id WHERE p.id = :p",
        p=scene.pharmacy,
    )
    forbidden = {
        "the client's name": r"Rami|Haddad",
        "the client's email": r"rami\.haddad|@example\.test",
        "the client's phone": r"70[\s.-]?123[\s.-]?456|\+961",
        "the pharmacy's address": r"Secret Lane",
        "the pharmacy's phone": re.escape(pharmacist.phone),
        "the pharmacy's licence": re.escape(pharmacist.license_number),
        "the pharmacist": re.escape(pharmacist.full_name) + "|" + re.escape(pharmacist.email),
        # The client's shared point and the pharmacy's pin, to any precision.
        "a coordinate": r"3[345]\.\d{3}",
        "the private box": re.escape(str(private)),
        "a pharmacy's ID": re.escape(str(scene.pharmacy)),
    }
    leaks = {what: re.findall(pattern, sent)[:3] for what, pattern in forbidden.items()}

    assert {what: found for what, found in leaks.items() if found} == {}
    # And the routing service was sent points, and nothing that says whose they are.
    asked = json.dumps(
        [(list(o.values()), list(d.values()), m) for o, d, m in scene.routing.asked], default=str
    )
    assert str(scene.client) not in asked
    assert str(scene.chat) not in asked
    # What the client typed is still useful to the agent, without the details.
    assert "ana [name], e7kine 3a [phone] aw [email]. ana 3and [location]. baddi augmentin" in sent
    assert "Hamra Pharmacy" in sent  # the admin-approved name is the one exception (R-AG8)
