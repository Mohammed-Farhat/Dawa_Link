"""A client's earlier chats (decision log D9, BLD-D40): listed, read, never continued."""

import json
import uuid
from typing import Any

from dawalink.agent.llm import ModelReply, Prompt, ToolResults
from dawalink.agent.llm.scripted import call, reply
from tests.api.conftest import Api, code_of
from tests.db.factories import TODAY


def say(http: Any, headers: dict[str, str], chat_id: str, text: str) -> Any:
    return http.post(
        f"/api/v1/conversations/{chat_id}/messages",
        json={"text": text, "client_message_id": str(uuid.uuid4())},
        headers=headers,
    )


def test_the_chats_are_listed_newest_first_with_what_they_were_about(api: Api) -> None:
    headers = api.token(api.client())
    http = api.http(reply("Which strength?"), reply("By car or on foot?"))
    first = http.get("/api/v1/conversations/active-chat", headers=headers).json()["conversation_id"]
    say(
        http,
        headers,
        first,
        "I need Augmentin for my mother, she takes it twice a day since Monday",
    )
    api.world.later(minutes=5)
    second = http.post("/api/v1/conversations/new-chat", headers=headers).json()["conversation_id"]
    say(http, headers, second, "baddi panadol")

    chats = http.get("/api/v1/conversations/chats", headers=headers).json()["items"]

    assert [(chat["conversation_id"], chat["active"]) for chat in chats] == [
        (second, True),
        (first, False),
    ]
    assert chats[0]["title"] == "baddi panadol"
    # A long first message is cut, and says so.
    assert chats[1]["title"].startswith("I need Augmentin for my mother")
    assert len(chats[1]["title"]) <= 61
    assert chats[1]["title"].endswith("…")


def test_an_earlier_chat_is_read_and_never_written_in(api: Api) -> None:
    headers = api.token(api.client())
    http = api.http(reply("Which strength?"), reply("Never said."))
    old = http.get("/api/v1/conversations/active-chat", headers=headers).json()["conversation_id"]
    say(http, headers, old, "I need Augmentin")
    http.post("/api/v1/conversations/new-chat", headers=headers)

    page = http.get(f"/api/v1/conversations/{old}/messages", headers=headers).json()
    again = say(http, headers, old, "and Panadol")

    assert page["archived"] is True
    assert [message["text"] for message in page["messages"]] == [
        "I need Augmentin",
        "Which strength?",
    ]
    assert (again.status_code, code_of(again)) == (422, "VALIDATION_ERROR")
    still = http.get(f"/api/v1/conversations/{old}/messages", headers=headers).json()
    assert len(still["messages"]) == 2


def test_a_chat_nobody_wrote_in_is_listed_only_while_it_is_the_open_one(api: Api) -> None:
    headers = api.token(api.client())
    http = api.http()
    http.get("/api/v1/conversations/active-chat", headers=headers)

    assert [
        c["title"] for c in http.get("/api/v1/conversations/chats", headers=headers).json()["items"]
    ] == [None]

    http.post("/api/v1/conversations/new-chat", headers=headers)

    chats = http.get("/api/v1/conversations/chats", headers=headers).json()["items"]
    assert [(chat["active"], chat["title"]) for chat in chats] == [(True, None)]


def test_the_list_holds_only_the_callers_own_chats_and_no_request_thread(api: Api) -> None:
    mine, theirs = api.client(), api.client()
    http = api.http(reply("Hello."))
    their_login = api.token(theirs)
    their_chat = http.get("/api/v1/conversations/active-chat", headers=their_login).json()[
        "conversation_id"
    ]
    say(http, their_login, their_chat, "something private")
    request = api.world.make.request(client_id=mine)
    api.world.make.conversation(client_id=mine, kind="request", request_id=request)

    chats = http.get("/api/v1/conversations/chats", headers=api.token(mine)).json()

    assert chats["items"] == []
    assert "something private" not in str(chats)


def test_a_card_of_an_earlier_chat_is_read_and_cant_be_tapped(api: Api) -> None:
    """D9, BLD-D40: an earlier chat is read, never continued. A card that was still good
    when the client pressed [New chat] is shown as expired, and its tap reserves nothing."""
    make = api.world.make
    client = api.client()
    headers = api.token(client)
    pharmacy = make.pharmacy(name="Hamra Pharmacy", lat=33.897, lon=35.484)
    product = make.product(moph_name="AUGMENTIN 1G", search_name="augmentin 1g")
    box = make.item(pharmacy_id=pharmacy, product_id=product, days_left=60, qty_on_hand=5)

    def show_the_card(prompt: Prompt) -> ModelReply:
        results = prompt.messages[-1]
        assert isinstance(results, ToolResults)
        made = json.loads(results.results[-1].content)
        return reply("Here it is.", proposal_ids=[made["proposal_id"]])

    http = api.http(
        call("propose_reservation", listing_id=str(box), pickup_day=str(TODAY)), show_the_card
    )
    old = http.get("/api/v1/conversations/active-chat", headers=headers).json()["conversation_id"]
    http.put(f"/api/v1/conversations/{old}/location", json={"district_id": 1}, headers=headers)
    say(http, headers, old, "I need Augmentin")
    page = http.get(f"/api/v1/conversations/{old}/messages", headers=headers).json()
    (card,) = [card for message in page["messages"] for card in message["cards"]]
    assert card["state"] == "open"

    http.post("/api/v1/conversations/new-chat", headers=headers)

    again = http.get(f"/api/v1/conversations/{old}/messages", headers=headers).json()
    (shown,) = [card for message in again["messages"] for card in message["cards"]]
    assert shown["state"] == "expired"
    tapped = http.post(
        f"/api/v1/proposals/{card['card_id']}/execute",
        json={"selected_item_keys": None},
        headers=headers | {"Idempotency-Key": "a-tap"},
    )
    assert (tapped.status_code, code_of(tapped)) == (409, "PROPOSAL_EXPIRED")
    assert api.world.one("SELECT count(*) FROM orders") == (0,)
