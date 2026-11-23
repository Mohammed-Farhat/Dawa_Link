"""A client handed to a person: the case's asks, and the chat the team has (docs/04 SM-9,
N-55; the owner, 2026-11-22).

What these tests hold on to:
- a new ask added to an open case is seen as a new ask, with the chat it came from;
- once the team has replied, the client's messages in that chat go to the team: stored as
  any message is, and no agent turn runs for them; until the case is closed, or N-55
  after the team's last reply there, on the app's clock;
- closing the case tells the chat once, and the assistant answers again;
- the lists are paged, with their total, and closed cases are the newest first.
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest

from dawalink.db.models import Escalation
from dawalink.domain.numbers import TEAM_HOLD
from dawalink.domain.vocabulary import EscalationReason, ReportReason
from dawalink.services import answer_reports, conversations, escalations
from dawalink.services.escalations import AskState
from tests.api.conftest import Api, code_of

ADMIN = "/api/v1/admin"
ASKED = EscalationReason.CLIENT_ASKED_HUMAN


@pytest.fixture
def admin(api: Api) -> dict[str, str]:
    return api.token(api.world.make.user("admin", totp_secret=b"not-a-real-secret"))


class Client:
    """A client with a chat, who can ask for a person."""

    def __init__(self, api: Api, **person: Any) -> None:
        self.api = api
        self.id = api.client(**person)
        self.login = api.token(self.id)
        self.chat = api.world.make.conversation(client_id=self.id)

    def say(self, author: str, text: str, conversation: uuid.UUID | None = None) -> int:
        tx = self.api.world.tx()
        locked = conversations.locked(tx, conversation or self.chat)
        message = conversations.append(tx, locked, author=author, kind="text", text=text)
        self.api.world.session.flush()
        return message.seq

    def ask(
        self,
        summary: str = "Client asked to talk to a person.",
        reason: EscalationReason = ASKED,
        conversation: uuid.UUID | None = None,
        **more: Any,
    ) -> uuid.UUID:
        tx = self.api.world.tx()
        made = escalations.escalate(
            tx,
            client_id=self.id,
            reason=reason,
            summary=summary,
            conversation_id=conversation or self.chat,
            **more,
        )
        self.api.world.session.flush()
        return made.escalation_id

    def held(self, conversation: uuid.UUID | None = None) -> bool:
        return escalations.held_by_team(self.api.world.tx(), conversation or self.chat)

    def person(self, conversation: uuid.UUID | None = None) -> escalations.PersonAsk:
        return escalations.person_ask(self.api.world.tx(), self.id, conversation or self.chat)

    def send(self, http: Any, text: str, conversation: uuid.UUID | None = None) -> Any:
        return http.post(
            f"/api/v1/conversations/{conversation or self.chat}/messages",
            json={"text": text, "client_message_id": str(uuid.uuid4())},
            headers=self.login,
        )

    def page(self, http: Any, conversation: uuid.UUID | None = None) -> Any:
        return http.get(
            f"/api/v1/conversations/{conversation or self.chat}/messages", headers=self.login
        ).json()


def reply(http: Any, admin: dict[str, str], case: uuid.UUID, text: str = "We are on it.") -> Any:
    return http.post(f"{ADMIN}/escalations/{case}/reply", json={"text": text}, headers=admin)


def close(http: Any, admin: dict[str, str], case: uuid.UUID) -> Any:
    return http.post(f"{ADMIN}/escalations/{case}/resolve", json={}, headers=admin)


def team_closed_cards(api: Api, conversation: uuid.UUID) -> int:
    (count,) = api.world.one(
        "SELECT count(*) FROM chat_messages WHERE conversation_id = :id "
        'AND cards @> \'[{"template": "team_closed"}]\'',
        id=conversation,
    )
    return int(count)


# --- Whether the team has the chat --------------------------------------------------------------


class TestHeldByTheTeam:
    def test_held_only_after_a_reply_and_until_the_case_is_closed(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        http = api.http()
        client = Client(api)
        case = client.ask()

        before_any_reply = client.held()
        reply(http, admin, case)
        after_the_reply = client.held()
        close(http, admin, case)

        assert before_any_reply is False  # OPEN: the assistant still answers
        assert after_the_reply is True
        assert client.held() is False  # RESOLVED

    def test_a_client_with_no_case_is_not_held(self, api: Api) -> None:
        assert Client(api).held() is False

    def test_the_hold_ends_by_itself_after_n55_on_the_app_clock(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        http = api.http()
        client = Client(api)
        case = client.ask()
        reply(http, admin, case)

        api.world.later(seconds=TEAM_HOLD.total_seconds() - 60)
        almost = client.held()
        reply(http, admin, case, "Still on it.")  # a later reply holds it again
        api.world.later(seconds=TEAM_HOLD.total_seconds() - 60)
        after_the_second = client.held()
        api.world.later(minutes=2)

        assert almost is True
        assert after_the_second is True
        assert client.held() is False
        # The case itself is still the team's: only the chat goes back to the assistant.
        assert client.person().state is AskState.ANSWERED

    def test_a_new_chat_is_not_held_until_the_team_replies_in_it(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        http = api.http()
        client = Client(api)
        case = client.ask()
        reply(http, admin, case)
        fresh = uuid.UUID(
            http.post("/api/v1/conversations/new-chat", headers=client.login).json()[
                "conversation_id"
            ]
        )

        earlier, new_before = client.held(), client.held(fresh)
        reply(http, admin, case, "Here is the answer.")

        assert (earlier, new_before) == (False, False)
        assert client.held(fresh) is True

    def test_a_case_from_a_button_holds_nothing_until_the_team_replies(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        """A contested missed pickup has no chat: the reply goes to the client's chat,
        and that chat is held from then on."""
        http = api.http()
        client = Client(api)
        tx = api.world.tx()
        case = escalations.escalate(
            tx,
            client_id=client.id,
            reason=EscalationReason.COMPLAINT,
            summary="The client says they collected order R-7K3Q2F.",
        ).escalation_id
        api.world.session.flush()

        before = client.held()
        reply(http, admin, case, "We are calling the pharmacy.")

        assert before is False
        assert client.held() is True
        assert [m["author"] for m in client.page(http)["messages"]] == ["admin"]


class TestAMessageToTheTeam:
    def test_it_is_stored_redacted_and_starts_no_agent_turn(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        client = Client(api, full_name="Rana Khoury", phone="+96170123456")
        case = client.ask()
        http = api.http()  # a scripted model with nothing to say: it must not be asked
        reply(http, admin, case)

        sent = client.send(http, "Thanks. I am Rana Khoury, call me on 70 123 456.")

        assert sent.status_code == 202
        assert sent.json() == {"message_seq": 2, "with_team": True}
        last = client.page(http)["messages"][-1]
        assert (last["author"], last["text"]) == (
            "client",
            "Thanks. I am [name], call me on [phone].",
        )
        assert api.models[-1].seen == []
        assert api.world.all("SELECT 1 FROM agent_runs") == []
        (waiting,) = api.world.one(
            "SELECT pending_turn_at FROM conversations WHERE id = :id", id=client.chat
        )
        assert waiting is None

    def test_the_model_only_checks_do_not_refuse_it(self, api: Api, admin: dict[str, str]) -> None:
        """With no assistant at all, or while a turn holds the chat, a message for the
        team is still kept: it never needed the model."""
        client = Client(api)
        case = client.ask()
        http = api.http(assistant=False)
        reply(http, admin, case)
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE conversations SET turn_lease_until = %s, turn_owner = 'worker'",
                (api.world.clock.now() + timedelta(minutes=5),),
            )

        sent = client.send(http, "Are you there?")

        assert (sent.status_code, sent.json()["with_team"]) == (202, True)

    def test_without_the_hold_the_same_chat_needs_the_assistant(self, api: Api) -> None:
        client = Client(api)
        client.ask()  # OPEN: nobody replied, the assistant answers

        sent = client.send(api.http(assistant=False), "Hello?")

        assert (sent.status_code, code_of(sent)) == (503, "ASSISTANT_UNAVAILABLE")

    def test_the_daily_limit_still_counts(
        self, api: Api, admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dawalink.api.routes import conversations as routes

        monkeypatch.setattr(routes, "CHAT_MESSAGES_PER_DAY", 1)
        client = Client(api)
        case = client.ask()
        http = api.http()
        reply(http, admin, case)

        first, second = client.send(http, "One."), client.send(http, "Two.")

        assert first.status_code == 202
        assert (second.status_code, code_of(second)) == (429, "RATE_LIMITED")

    def test_a_held_thread_asks_no_turn_for_the_message_but_keeps_an_events_turn(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        """In a request's thread the agent goes on re-planning on events: only the
        client's own messages go to the team."""
        client = Client(api)
        request = api.world.make.request(
            client_id=client.id, ends_at=api.world.clock.now() + timedelta(hours=6)
        )
        thread = api.world.make.conversation(
            client_id=client.id, kind="request", request_id=request
        )
        case = client.ask(conversation=thread, request_id=request)
        http = api.http()
        reply(http, admin, case)

        quiet = client.send(http, "Thanks!", thread)
        (after_message,) = api.world.one(
            "SELECT pending_turn_at FROM conversations WHERE id = :id", id=thread
        )
        asked_at = api.world.clock.now()
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE conversations SET pending_turn_at = %s WHERE id = %s",
                (asked_at, str(thread)),
            )
        with_an_event = client.send(http, "And the other box?", thread)
        (after_event,) = api.world.one(
            "SELECT pending_turn_at FROM conversations WHERE id = :id", id=thread
        )

        assert (quiet.status_code, quiet.json()["with_team"]) == (202, True)
        assert after_message is None
        assert with_an_event.status_code == 202
        assert after_event == asked_at

    def test_the_page_says_when_the_team_has_the_chat(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        http = api.http()
        client = Client(api)
        case = client.ask()

        before = client.page(http)["with_team"]
        reply(http, admin, case)
        during = client.page(http)["with_team"]
        close(http, admin, case)

        assert (before, during, client.page(http)["with_team"]) == (False, True, False)


class TestClosingTheCase:
    def test_the_chat_is_told_once_and_the_assistant_answers_again(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        http = api.http()
        client = Client(api)
        case = client.ask()
        reply(http, admin, case)

        closed = close(http, admin, case)
        again = close(http, admin, case)

        assert closed.status_code == 200
        assert (again.status_code, code_of(again)) == (409, "CHANGED_SINCE")
        assert team_closed_cards(api, client.chat) == 1
        last = client.page(http)["messages"][-1]
        assert (last["author"], [card["type"] for card in last["cards"]]) == (
            "system",
            ["team_closed"],
        )
        assert client.person().state is AskState.CLOSED

    def test_a_case_with_no_chat_tells_no_chat(self, api: Api, admin: dict[str, str]) -> None:
        """A contested missed pickup nobody answered: there is no chat to tell, and none
        is made for it."""
        http = api.http()
        client = Client(api)
        tx = api.world.tx()
        case = escalations.escalate(
            tx,
            client_id=client.id,
            reason=EscalationReason.COMPLAINT,
            summary="The client says they collected order R-7K3Q2F.",
        ).escalation_id
        api.world.session.flush()
        chats_before = api.world.all("SELECT id FROM conversations")

        close(http, admin, case)

        assert api.world.all("SELECT id FROM conversations") == chats_before
        assert team_closed_cards(api, client.chat) == 0

    def test_an_earlier_chat_is_not_told(self, api: Api, admin: dict[str, str]) -> None:
        http = api.http()
        client = Client(api)
        case = client.ask()
        reply(http, admin, case)
        http.post("/api/v1/conversations/new-chat", headers=client.login)

        close(http, admin, case)

        assert team_closed_cards(api, client.chat) == 0

    def test_a_later_reply_on_a_new_ask_holds_the_chat_again(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        """A closed case is closed: the next ask opens a new one (SM-9)."""
        http = api.http()
        client = Client(api)
        first = client.ask()
        reply(http, admin, first)
        close(http, admin, first)

        second = client.ask()
        not_yet = client.held()
        reply(http, admin, second, "Back again: how can we help?")

        assert second != first
        assert not_yet is False
        assert client.held() is True


# --- A new ask on an open case (Admin 1) ---------------------------------------------------------


class TestANewAsk:
    def test_a_case_from_a_button_takes_the_chat_of_a_later_ask(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        http = api.http()
        client = Client(api)
        tx = api.world.tx()
        case = escalations.escalate(
            tx,
            client_id=client.id,
            reason=EscalationReason.COMPLAINT,
            summary="The client says they collected order R-7K3Q2F.",
        ).escalation_id
        api.world.session.flush()
        client.say("client", "talk to a person asap")
        api.world.later(minutes=1)

        joined = client.ask("Client asks for a person about the missed pickup.")
        detail = http.get(f"{ADMIN}/escalations/{case}", headers=admin).json()
        (row,) = http.get(f"{ADMIN}/escalations", headers=admin).json()["items"]

        assert joined == case
        assert [line["text"] for line in detail["thread"]] == ["talk to a person asap"]
        assert row["reasons"] == ["complaint", "client_asked_human"]
        assert row["last_summary"] == "Client asks for a person about the missed pickup."
        assert row["summary"] == "The client says they collected order R-7K3Q2F."

    def test_the_chat_of_every_ask_is_on_the_case_and_the_reply_goes_to_the_newest(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        http = api.http()
        client = Client(api)
        client.say("client", "I need a person.")
        case = client.ask()
        request = api.world.make.request(client_id=client.id)
        thread = api.world.make.conversation(
            client_id=client.id, kind="request", request_id=request
        )
        client.say("client", "A person please, about my request.", thread)
        client.ask("Client asks for a person about the request.", conversation=thread)

        reply(http, admin, case, "Hello, about your request.")
        detail = http.get(f"{ADMIN}/escalations/{case}", headers=admin).json()

        assert [(line["text"], line["starts_another_chat"]) for line in detail["thread"]] == [
            ("I need a person.", False),
            ("A person please, about my request.", True),
            ("Hello, about your request.", False),
        ]

    def test_a_new_ask_after_the_reply_is_marked_and_the_same_words_count(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        http = api.http()
        client = Client(api)
        case = client.ask()
        retried = client.ask()  # a retried turn: nothing new
        reply(http, admin, case)
        quiet = http.get(f"{ADMIN}/escalations/{case}", headers=admin).json()["escalation"]
        api.world.later(minutes=5)

        client.ask()  # the same words, after the reply: a new ask
        marked = http.get(f"{ADMIN}/escalations/{case}", headers=admin).json()["escalation"]

        assert retried == case
        assert (quiet["new_ask_since_reply"], len(quiet["notes"])) == (False, 0)
        assert (marked["new_ask_since_reply"], len(marked["notes"])) == (True, 1)
        assert marked["state"] == "IN_PROGRESS"  # SM-9 keeps its three states
        assert client.person().state is AskState.ASKED

    def test_where_the_ask_stands_for_the_agent(self, api: Api, admin: dict[str, str]) -> None:
        http = api.http()
        client = Client(api)
        nothing = client.person()
        case = client.ask()
        asked = client.person()
        reply(http, admin, case)
        answered = client.person()
        close(http, admin, case)
        closed = client.person()
        other_chat = escalations.person_ask(
            api.world.tx(),
            client.id,
            api.world.make.conversation(client_id=client.id, status="ARCHIVED"),
        )

        assert (nothing.state, nothing.at) == (AskState.NONE, None)
        assert (asked.state, asked.escalation_id, asked.with_team) == (AskState.ASKED, case, False)
        assert asked.at == api.world.clock.now()
        assert (answered.state, answered.with_team) == (AskState.ANSWERED, True)
        assert answered.at == api.world.clock.now()
        assert (closed.state, closed.at, closed.with_team) == (
            AskState.CLOSED,
            api.world.clock.now(),
            False,
        )
        # A chat the closed case never touched has no ask.
        assert other_chat.state is AskState.NONE


# --- The admin's lists ---------------------------------------------------------------------------


class TestTheLists:
    def test_cases_that_wait_for_the_team_come_before_the_quiet_ones(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        http = api.http()
        quiet, waiting, wrote = Client(api), Client(api), Client(api)
        quiet_case = quiet.ask()
        reply(http, admin, quiet_case)
        api.world.later(minutes=10)
        wrote_case = wrote.ask()
        reply(http, admin, wrote_case)
        api.world.later(minutes=10)
        waiting_case = waiting.ask()
        wrote.send(http, "Any news?")
        api.world.later(minutes=10)
        emergency = Client(api).ask(
            "Client says it is an emergency.", reason=EscalationReason.EMERGENCY_CLAIM
        )

        listed = http.get(f"{ADMIN}/escalations", headers=admin).json()
        by_id = {row["id"]: row for row in listed["items"]}

        assert [row["id"] for row in listed["items"]] == [
            str(emergency),
            str(wrote_case),  # waits: the client wrote after the reply
            str(waiting_case),  # waits: never answered
            str(quiet_case),  # answered, and nothing since
        ]
        assert listed["total"] == 4
        assert by_id[str(wrote_case)]["client_wrote_at"] is not None
        assert by_id[str(quiet_case)]["client_wrote_at"] is None
        assert by_id[str(quiet_case)]["hold_ends_at"] is not None
        assert by_id[str(waiting_case)]["hold_ends_at"] is None

    def test_the_hold_on_the_case_ends_with_a_new_chat(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        """The case's page says when the assistant answers again only while a chat the
        client writes in is held: an earlier chat holds nothing."""
        http = api.http()
        client = Client(api)
        case = client.ask()
        reply(http, admin, case)
        held = http.get(f"{ADMIN}/escalations/{case}", headers=admin).json()["escalation"]
        http.post("/api/v1/conversations/new-chat", headers=client.login)

        after = http.get(f"{ADMIN}/escalations/{case}", headers=admin).json()["escalation"]

        assert held["hold_ends_at"] is not None
        assert after["hold_ends_at"] is None

    def test_closed_cases_are_the_newest_first_and_paged_with_a_total(
        self, api: Api, admin: dict[str, str]
    ) -> None:
        now = api.world.clock.now()
        client = api.client()
        for minutes in range(26):
            api.world.session.add(
                Escalation(
                    id=uuid.uuid4(),
                    client_id=client,
                    reason=ASKED.value,
                    summary=f"Case {minutes}",
                    state="RESOLVED",
                    created_at=now - timedelta(days=1),
                    resolved_at=now - timedelta(minutes=minutes),
                )
            )
        api.world.session.flush()
        http = api.http()

        first = http.get(f"{ADMIN}/escalations?state=RESOLVED&limit=25", headers=admin).json()
        second = http.get(
            f"{ADMIN}/escalations?state=RESOLVED&limit=25&cursor=25", headers=admin
        ).json()

        assert [row["summary"] for row in first["items"][:2]] == ["Case 0", "Case 1"]
        assert (len(first["items"]), first["total"], first["next_cursor"]) == (25, 26, "25")
        assert [row["summary"] for row in second["items"]] == ["Case 25"]
        assert (second["total"], second["next_cursor"]) == (26, None)
        far = http.get(f"{ADMIN}/escalations?state=RESOLVED&cursor=500", headers=admin).json()
        assert (far["items"], far["total"]) == ([], 26)

    def test_the_open_queue_is_paged_with_a_total(self, api: Api, admin: dict[str, str]) -> None:
        for _ in range(26):
            Client(api).ask()
        http = api.http()

        second = http.get(f"{ADMIN}/escalations?limit=25&cursor=25", headers=admin).json()

        assert (len(second["items"]), second["total"], second["next_cursor"]) == (1, 26, None)

    def test_reported_answers_are_paged_with_a_total(self, api: Api, admin: dict[str, str]) -> None:
        client = Client(api)
        seqs = [client.say("agent", f"Answer {number}") for number in range(26)]
        tx = api.world.tx()
        for seq in seqs:
            answer_reports.report(
                tx, client.id, client.chat, seq, reason=ReportReason.OTHER, clean=lambda text: text
            )
        api.world.session.flush()
        http = api.http()

        second = http.get(f"{ADMIN}/answer-reports?limit=25&cursor=25", headers=admin).json()
        none = http.get(f"{ADMIN}/answer-reports?state=CONFIRMED", headers=admin).json()

        assert (len(second["items"]), second["total"], second["next_cursor"]) == (1, 26, None)
        assert (none["items"], none["total"]) == ([], 0)

    @pytest.mark.parametrize("cursor", ["-1", str(10**40), "soon"])
    def test_a_place_in_the_list_out_of_bounds_is_refused(
        self, api: Api, admin: dict[str, str], cursor: str
    ) -> None:
        http = api.http()
        for path in ("escalations", "answer-reports"):
            answer = http.get(f"{ADMIN}/{path}?cursor={cursor}", headers=admin)
            assert answer.status_code == 422
