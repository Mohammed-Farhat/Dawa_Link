"""The chat over HTTP: a message, its stream, a card's tap, the ticket (docs/06 §6.3,
§6.6, §6.7; docs/04 R-AG2, R-AG7, INV-21; docs/09 FA-5, FS-7)."""

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dawalink.agent.chat import post_client_message
from dawalink.agent.llm import ModelReply, Prompt, ToolResults
from dawalink.agent.llm.scripted import call, reply
from dawalink.api import chat_stream
from dawalink.api.limits import Limiter
from dawalink.api.routes import conversations as conversations_routes
from tests.api.conftest import HAMRA, Api, code_of, events_of
from tests.db.factories import TODAY

KEY = {"Idempotency-Key": "a-tap"}


def show_the_card(prompt: Prompt) -> ModelReply:
    """The scripted model reads the proposal a tool just made, and shows it."""
    results = prompt.messages[-1]
    assert isinstance(results, ToolResults)
    made = json.loads(results.results[-1].content)
    return reply("Here it is.", proposal_ids=[made["proposal_id"]], quick_replies=["Thanks"])


@dataclass
class Chat:
    api: Api
    client: uuid.UUID
    headers: dict[str, str]
    chat: uuid.UUID
    box: uuid.UUID

    def path(self, rest: str = "/messages") -> str:
        return f"/api/v1/conversations/{self.chat}{rest}"

    def say(self, http: TestClient, text: str = "I need Augmentin", **more: Any) -> Any:
        body = {"text": text, "client_message_id": str(uuid.uuid4())} | more
        return http.post(self.path(), json=body, headers=self.headers)

    def reserve_turn(self) -> tuple[Any, Any]:
        """What the scripted model does to propose this chat's box."""
        return (
            call("propose_reservation", listing_id=str(self.box), pickup_day=str(TODAY)),
            show_the_card,
        )


@pytest.fixture
def chat(api: Api) -> Chat:
    make = api.world.make
    client = api.client()
    pharmacy = make.pharmacy(
        name="Hamra Pharmacy", address="12 Hamra Street", lat=33.897, lon=35.484
    )
    product = make.product(
        moph_name="AUGMENTIN 1G", search_name="augmentin 1g", public_price_lbp=1_000_000
    )
    return Chat(
        api,
        client,
        api.token(client),
        make.conversation(
            client_id=client, loc_lat=HAMRA.point.lat, loc_lon=HAMRA.point.lon, loc_source="shared"
        ),
        make.item(pharmacy_id=pharmacy, product_id=product, days_left=60, qty_on_hand=5),
    )


class TestAMessageAndItsAnswer:
    def test_the_answer_arrives_as_progress_then_the_whole_reply(self, chat: Chat) -> None:
        http = chat.api.http(*chat.reserve_turn())

        answer = chat.say(http)

        assert answer.status_code == 200
        assert answer.headers["content-type"].startswith("text/event-stream")
        events = events_of(answer)
        names = [name for name, _ in events]
        assert names[0] == "turn_started"
        assert names[-2:] == ["message", "turn_completed"]
        assert set(names[1:-2]) <= {"progress"}
        message = dict(events)["message"]
        assert (message["author"], message["text"]) == ("agent", "Here it is.")
        assert message["quick_replies"] == ["Thanks"]
        (card,) = message["cards"]
        assert (card["origin"], card["type"], card["state"]) == ("proposal", "reserve", "open")
        assert card["action_label"] == "Reserve"
        assert card["title"] == "AUGMENTIN 1G at Hamra Pharmacy"
        assert dict(events)["turn_completed"]["outcome"] == "ok"

    def test_a_card_never_carries_a_coordinate_or_an_internal_field(self, chat: Chat) -> None:
        http = chat.api.http(*chat.reserve_turn())

        sent = chat.say(http).text

        assert "33.89" not in sent
        assert "35.48" not in sent
        assert "listing_id" not in sent
        assert "price_lbp_shown" not in sent

    def test_the_page_reads_the_messages_again_by_polling(self, chat: Chat) -> None:
        http = chat.api.http(*chat.reserve_turn())
        chat.say(http)

        page = http.get(chat.path(), headers=chat.headers).json()
        later = http.get(chat.path(), params={"after_seq": page["last_seq"]}, headers=chat.headers)

        assert [m["author"] for m in page["messages"]] == ["client", "agent"]
        assert page["kind"] == "chat"
        assert page["busy"] is False
        assert page["location"] == {"source": "shared", "label": "Your location"}
        assert later.json()["messages"] == []

    def test_the_agents_own_events_are_never_sent_to_the_client(self, chat: Chat) -> None:
        http = chat.api.http()
        with chat.api.world.as_owner():
            chat.api.world.connection.exec_driver_sql(
                "INSERT INTO chat_messages (conversation_id, seq, author, kind, text_redacted)"
                " VALUES (%s, 1, 'system', 'event', '{\"type\": \"not_available\"}')",
                (chat.chat,),
            )

        page = http.get(chat.path(), headers=chat.headers).json()

        assert page["messages"] == []
        assert "not_available" not in json.dumps(page)

    def test_the_same_message_sent_twice_is_stored_once(self, chat: Chat) -> None:
        http = chat.api.http(reply("Which strength?"), reply("Which strength?"))
        same = str(uuid.uuid4())

        chat.say(http, client_message_id=same)
        chat.say(http, client_message_id=same)

        page = http.get(chat.path(), headers=chat.headers).json()
        assert [m["author"] for m in page["messages"]].count("client") == 1

    @pytest.mark.parametrize("text", ["", "   ", "\n\t"])
    def test_an_empty_message_is_refused_and_nothing_is_kept(self, chat: Chat, text: str) -> None:
        """FI-6."""
        http = chat.api.http()

        answer = chat.say(http, text)

        assert (answer.status_code, code_of(answer)) == (422, "VALIDATION_ERROR")
        assert chat.api.world.all("SELECT 1 FROM chat_messages") == []
        assert chat.api.models[-1].seen == []

    def test_a_message_that_is_too_long_is_refused(self, chat: Chat) -> None:
        answer = chat.say(chat.api.http(), "x" * 1_001)

        assert (answer.status_code, code_of(answer)) == (422, "MESSAGE_TOO_LONG")

    def test_the_turn_finishes_even_when_nobody_listens_to_the_stream(self, chat: Chat) -> None:
        """A dropped connection loses nothing: the reply is saved and the next poll has it."""
        http = chat.api.http(reply("Which strength?"))
        agent = http.app.state.agent  # type: ignore[attr-defined]
        tx = chat.api.world.tx()
        from dawalink.agent.chat import post_client_message

        posted = post_client_message(
            tx,
            client_id=chat.client,
            conversation_id=chat.chat,
            text="I need Augmentin",
            client_message_id=uuid.uuid4(),
        )
        chat.api.world.session.flush()
        pool = http.app.state.turn_pool  # type: ignore[attr-defined]

        # The stream is never read: nobody is listening.
        chat_stream.answer(pool, agent, chat.chat, client_message_seq=posted.seq, request_id="r")

        pool.shutdown(wait=True)
        page = http.get(chat.path(), headers=chat.headers).json()
        assert [m["text"] for m in page["messages"]][-1] == "Which strength?"


class TestWhenTheAssistantCantAnswer:
    def test_with_no_model_the_chat_says_so_and_keeps_nothing(self, chat: Chat) -> None:
        http = chat.api.http(assistant=False)

        answer = chat.say(http)

        assert (answer.status_code, code_of(answer)) == (503, "ASSISTANT_UNAVAILABLE")
        assert answer.json()["error"]["details"] == {"fallback": "search"}
        assert http.get(chat.path(), headers=chat.headers).json()["messages"] == []

    def test_a_model_that_fails_is_reported_inside_the_stream(self, chat: Chat) -> None:
        from dawalink.agent.llm import LLMUnavailable

        http = chat.api.http(*[LLMUnavailable("down")] * 3)

        events = events_of(chat.say(http))

        assert [name for name, _ in events][-1] == "error"
        assert events[-1][1]["error"]["code"] == "ASSISTANT_UNAVAILABLE"

    def test_while_a_turn_runs_the_chat_is_busy(self, chat: Chat) -> None:
        http = chat.api.http()
        with chat.api.world.as_owner():
            chat.api.world.connection.exec_driver_sql(
                "UPDATE conversations SET turn_lease_until = %s, turn_owner = 'worker'",
                (chat.api.world.clock.now().replace(year=2027),),
            )

        answer = chat.say(http)

        assert (answer.status_code, code_of(answer)) == (409, "CONVERSATION_BUSY")
        assert answer.json()["error"]["details"]["retry_after_ms"] > 0
        assert http.get(chat.path(), headers=chat.headers).json()["busy"] is True

    def test_a_message_whose_turn_died_with_the_server_is_answered_when_sent_again(
        self, chat: Chat
    ) -> None:
        """FX-15: the API stopped in the middle of a turn. The message is kept, the turn's
        lease runs out by itself, and the website's [Retry] sends the same message: it is
        answered, and stored once."""
        world = chat.api.world
        sent = uuid.uuid4()
        tx = world.tx()
        post_client_message(
            tx,
            client_id=chat.client,
            conversation_id=chat.chat,
            text="I need Augmentin",
            client_message_id=sent,
        )
        world.settle(tx)
        with world.as_owner():
            world.connection.exec_driver_sql(
                "UPDATE conversations SET turn_lease_until = %s, turn_owner = 'api'",
                (world.clock.now() - timedelta(seconds=1),),
            )
        http = chat.api.http(reply("Which strength?"))

        answer = chat.say(http, "I need Augmentin", client_message_id=str(sent))

        assert answer.status_code == 200
        assert dict(events_of(answer))["message"]["text"] == "Which strength?"
        written = world.all("SELECT author FROM chat_messages ORDER BY seq")
        assert [row.author for row in written] == ["client", "agent"]
        assert http.get(chat.path(), headers=chat.headers).json()["busy"] is False

    def test_a_client_may_write_only_so_fast(self, chat: Chat) -> None:
        http = chat.api.http(reply("Yes?"))
        http.app.state.chat_per_client = Limiter(1, 60)  # type: ignore[attr-defined]

        chat.say(http)
        second = chat.say(http)

        assert (second.status_code, code_of(second)) == (429, "RATE_LIMITED")

    def test_a_client_has_only_so_many_messages_a_day(
        self, chat: Chat, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N-17, docs/10 TH-52: counted from the messages kept, so a restart changes
        nothing. (The real number is 100; two here.)"""
        monkeypatch.setattr(conversations_routes, "CHAT_MESSAGES_PER_DAY", 2)
        http = chat.api.http(reply("One."), reply("Two."), reply("Never said."))

        answers = [chat.say(http, f"message {number}") for number in range(3)]

        assert [answer.status_code for answer in answers] == [200, 200, 429]
        assert code_of(answers[-1]) == "RATE_LIMITED"
        assert "Search still works" in answers[-1].json()["error"]["message"]
        assert len(chat.api.models[-1].seen) == 2
        assert chat.api.world.one("SELECT count(*) FROM chat_messages WHERE author = 'client'") == (
            2,
        )

    def test_before_the_email_is_confirmed_there_is_no_assistant(self, api: Api) -> None:
        http = api.http()
        headers = api.token(api.client("UNVERIFIED"))

        answer = http.get("/api/v1/conversations/active-chat", headers=headers)

        assert (answer.status_code, code_of(answer)) == (403, "EMAIL_NOT_VERIFIED")


class TestTappingACard:
    def card(self, chat: Chat, http: TestClient) -> str:
        return str(dict(events_of(chat.say(http)))["message"]["cards"][0]["card_id"])

    def test_the_tap_reserves_and_the_ticket_shows_the_order_number(self, chat: Chat) -> None:
        http = chat.api.http(*chat.reserve_turn())
        card = self.card(chat, http)

        done = http.post(f"/api/v1/proposals/{card}/execute", json={}, headers=chat.headers | KEY)

        assert done.status_code == 200
        (reserved,) = done.json()["reservations"]
        assert reserved["ref"].startswith("R-")
        assert reserved["state"] == "RESERVED"
        assert reserved["status_text"].startswith("Reserved: pick up by ")
        assert reserved["source"] == "assistant"
        assert reserved["pharmacy"]["name"] == "Hamra Pharmacy"
        assert reserved["saving"]["lbp"] > 0
        ticket = http.get(f"/api/v1/reservations/{reserved['id']}", headers=chat.headers).json()
        assert ticket["ref"] == reserved["ref"]
        active = http.get("/api/v1/reservations", headers=chat.headers).json()
        assert [item["ref"] for item in active["items"]] == [reserved["ref"]]
        # The card now says it was used, and a "reserved" card stands in the chat.
        page = http.get(chat.path(), headers=chat.headers).json()
        assert page["messages"][1]["cards"][0]["state"] == "used"
        assert page["messages"][-1]["cards"][0]["type"] == "reserved"
        assert page["messages"][-1]["cards"][0]["data"]["order_ref"] == reserved["ref"]

    def test_a_card_works_once(self, chat: Chat) -> None:
        http = chat.api.http(*chat.reserve_turn())
        card = self.card(chat, http)
        http.post(f"/api/v1/proposals/{card}/execute", json={}, headers=chat.headers | KEY)

        again = http.post(f"/api/v1/proposals/{card}/execute", json={}, headers=chat.headers | KEY)

        assert (again.status_code, code_of(again)) == (409, "PROPOSAL_USED")
        active = http.get("/api/v1/reservations", headers=chat.headers).json()
        assert len(active["items"]) == 1

    def test_a_tap_needs_its_key(self, chat: Chat) -> None:
        http = chat.api.http(*chat.reserve_turn())
        card = self.card(chat, http)

        answer = http.post(f"/api/v1/proposals/{card}/execute", json={}, headers=chat.headers)

        assert (answer.status_code, code_of(answer)) == (400, "IDEMPOTENCY_KEY_REQUIRED")

    def test_everything_is_checked_again_at_the_tap(self, chat: Chat) -> None:
        """The card promises nothing: the box was sold at the counter in the meantime."""
        http = chat.api.http(*chat.reserve_turn())
        card = self.card(chat, http)
        with chat.api.world.as_owner():
            chat.api.world.connection.exec_driver_sql("UPDATE inventory_items SET qty_on_hand = 0")

        answer = http.post(f"/api/v1/proposals/{card}/execute", json={}, headers=chat.headers | KEY)

        assert answer.status_code == 409
        assert code_of(answer) in {"NOT_ENOUGH_STOCK", "LISTING_NOT_AVAILABLE"}
        assert http.get("/api/v1/reservations", headers=chat.headers).json()["items"] == []

    def test_the_client_cancels_from_the_ticket(self, chat: Chat) -> None:
        http = chat.api.http(*chat.reserve_turn())
        card = self.card(chat, http)
        reserved = http.post(
            f"/api/v1/proposals/{card}/execute", json={}, headers=chat.headers | KEY
        ).json()["reservations"][0]

        cancelled = http.post(f"/api/v1/reservations/{reserved['id']}/cancel", headers=chat.headers)
        twice = http.post(f"/api/v1/reservations/{reserved['id']}/cancel", headers=chat.headers)

        assert cancelled.json()["state"] == "CANCELLED_BY_CLIENT"
        assert code_of(twice) == "RESERVATION_NOT_ACTIVE"
        history = http.get(
            "/api/v1/reservations", params={"view": "history"}, headers=chat.headers
        ).json()
        assert [item["status_text"] for item in history["items"]] == ["Cancelled by you"]


class TestSomeoneElsesThings:
    """Another client's conversation, card and reservation don't exist (docs/06 §2.2)."""

    def test_they_all_answer_not_found(self, chat: Chat) -> None:
        http = chat.api.http(*chat.reserve_turn())
        card = str(dict(events_of(chat.say(http)))["message"]["cards"][0]["card_id"])
        reserved = http.post(
            f"/api/v1/proposals/{card}/execute", json={}, headers=chat.headers | KEY
        ).json()["reservations"][0]
        other = chat.api.token(chat.api.client())

        answers = [
            http.get(chat.path(), headers=other),
            http.post(
                chat.path(),
                json={"text": "hello", "client_message_id": str(uuid.uuid4())},
                headers=other,
            ),
            http.put(chat.path("/location"), json={"district_id": 1}, headers=other),
            http.post(f"/api/v1/proposals/{card}/execute", json={}, headers=other | KEY),
            http.get(f"/api/v1/reservations/{reserved['id']}", headers=other),
            http.post(f"/api/v1/reservations/{reserved['id']}/cancel", headers=other),
        ]

        assert [(a.status_code, code_of(a)) for a in answers] == [(404, "NOT_FOUND")] * 6
        assert http.get("/api/v1/reservations", headers=other).json()["items"] == []

    def test_a_pharmacist_cant_use_a_clients_chat(self, chat: Chat) -> None:
        http = chat.api.http()
        pharmacist = chat.api.token(chat.api.world.make.user("pharmacist"))

        answer = http.get(chat.path(), headers=pharmacist)

        assert (answer.status_code, code_of(answer)) == (403, "FORBIDDEN")


class TestTheChatsLocation:
    def test_a_district_or_a_point_is_kept_and_never_shown_back(self, chat: Chat) -> None:
        http = chat.api.http()

        by_district = http.put(
            chat.path("/location"), json={"district_id": 1}, headers=chat.headers
        )
        named = http.get(chat.path(), headers=chat.headers).json()["location"]
        by_point = http.put(
            chat.path("/location"),
            json={"lat": 33.89612345, "lon": 35.48321987},
            headers=chat.headers,
        )
        shared = http.get(chat.path(), headers=chat.headers).json()["location"]

        assert (by_district.status_code, by_point.status_code) == (204, 204)
        assert named["source"] == "district"
        assert named["label"]
        assert shared == {"source": "shared", "label": "Your location"}
        # Rounded to about 100 m before it is stored (N-43).
        stored = chat.api.world.one("SELECT loc_lat::text, loc_lon::text FROM conversations")
        assert stored == ("33.896", "35.483")

    def test_nothing_or_nonsense_is_refused(self, chat: Chat) -> None:
        http = chat.api.http()

        answers = [
            http.put(chat.path("/location"), json=body, headers=chat.headers)
            for body in ({}, {"lat": 95, "lon": 35}, {"district_id": 999}, {"lat": 33.9})
        ]

        assert [code_of(answer) for answer in answers] == ["VALIDATION_ERROR"] * 4

    def test_a_point_may_be_sent_only_so_often(self, chat: Chat) -> None:
        http = chat.api.http()
        http.app.state.locations_per_client = Limiter(1, 3600)  # type: ignore[attr-defined]
        point = {"lat": 33.896, "lon": 35.483}

        http.put(chat.path("/location"), json=point, headers=chat.headers)
        second = http.put(chat.path("/location"), json=point, headers=chat.headers)
        district = http.put(chat.path("/location"), json={"district_id": 1}, headers=chat.headers)

        assert (second.status_code, code_of(second)) == (429, "RATE_LIMITED")
        assert district.status_code == 204  # a district starts no routing call

    def test_a_new_chat_starts_empty_and_archives_the_old_one(self, chat: Chat) -> None:
        http = chat.api.http(reply("Yes?"))
        chat.say(http)

        fresh = http.post("/api/v1/conversations/new-chat", headers=chat.headers).json()
        current = http.get("/api/v1/conversations/active-chat", headers=chat.headers).json()

        assert fresh["conversation_id"] != str(chat.chat)
        assert current == fresh
        assert chat.api.world.one(
            "SELECT status FROM conversations WHERE id = :id", id=chat.chat
        ) == ("ARCHIVED",)
