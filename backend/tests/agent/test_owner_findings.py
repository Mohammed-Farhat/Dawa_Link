"""The agent's side of the owner's findings of 2026-11-22, on a scripted model.

- A reply written before its tools' results is refused: a failed hand-over was announced
  to the client as done (docs/09, the turn loop).
- A reply never says a person has the case when nobody was told.
- Where an ask for a person stands, and the running watches, come from the tables.
- The reply's language follows the client's message.
- After a team reply the chat is with the team: the assistant is silent, and never
  answers afterwards the messages that were written to the team.
"""

import uuid
from typing import Any

import pytest

from dawalink.agent.chat import post_client_message, post_team_reply
from dawalink.agent.guards import output as output_guard
from dawalink.agent.llm import ToolResults, UserText
from dawalink.agent.llm.scripted import call, calls, reply
from dawalink.agent.tools import Reply
from dawalink.agent.turn import REPLIED_TOO_EARLY, Status, run_turn
from dawalink.domain.numbers import TEAM_HOLD
from dawalink.services import conversations, escalations, events
from dawalink.services.events import Decision
from tests.agent.conftest import Scene
from tests.db.factories import TODAY

PASSED_ON = "I've passed your request to a person from DawaLink."


def block(scene: Scene, position: int = 0) -> str:
    """The facts the model was given in a turn (its first message)."""
    message = scene.model.seen[position].messages[0]
    assert isinstance(message, UserText)
    return message.text


def sent_back(scene: Scene, position: int = -1) -> list[str]:
    """The tool results the model was sent in one of its calls, as text."""
    message = scene.model.seen[position].messages[-1]
    assert isinstance(message, ToolResults)
    return [result.content for result in message.results]


class TestAReplyWrittenBeforeItsResults:
    def test_a_reply_sent_with_a_tool_that_fails_is_refused(self, scene: Scene) -> None:
        """Seen on 2026-11-22: escalate failed, and the reply sent with it said a person
        had the case."""
        result = scene.turn(
            calls(
                ("escalate", {"reason": "not_a_reason", "summary": "The client wants a person."}),
                ("reply", {"text": PASSED_ON}),
            ),
            reply("I couldn't reach a person just now. Please try again in a moment."),
            text="I want to talk to a person",
        )

        assert result.status is Status.DONE
        assert result.text == "I couldn't reach a person just now. Please try again in a moment."
        assert REPLIED_TOO_EARLY in " ".join(sent_back(scene))
        assert scene.tool_calls(result) == [("escalate", False, "INVALID_ARGUMENTS")]
        assert scene.world.all("SELECT id FROM escalations") == []
        assert [message.author for message in scene.messages()] == ["client", "agent"]

    def test_a_reply_next_to_a_hand_over_that_worked_is_kept(self, scene: Scene) -> None:
        """Its answer adds nothing the reply needs: no second model call."""
        result = scene.turn(
            calls(
                (
                    "escalate",
                    {"reason": "client_asked_human", "summary": "The client wants a person."},
                ),
                ("reply", {"text": PASSED_ON}),
            ),
            text="I want to talk to a person",
        )

        assert (result.status, result.text) == (Status.DONE, PASSED_ON)
        assert scene.run(result).llm_calls == 1

    def test_a_reply_next_to_any_other_tool_was_written_blind(self, scene: Scene) -> None:
        result = scene.turn(
            calls(
                ("search_catalog", {"query": "augmentin"}),
                ("reply", {"text": "I found three strengths."}),
            ),
            reply("I found Augmentin 1 g."),
        )

        assert result.text == "I found Augmentin 1 g."
        assert scene.run(result).llm_calls == 2
        # The search itself counted: its result went back with the refusal.
        assert any("AUGMENTIN 1G" in content for content in sent_back(scene))

    def test_a_long_summary_is_cut_never_refused(self, scene: Scene) -> None:
        result = scene.turn(
            call(
                "escalate", reason="client_asked_human", summary="The client wants a person. " * 40
            ),
            reply(PASSED_ON),
            text="I want to talk to a person",
        )

        assert scene.tool_calls(result) == [("escalate", True, None)]
        (case,) = scene.world.all("SELECT summary FROM escalations")
        assert len(case.summary) <= 300


class TestSayingAPersonHasTheCase:
    def test_it_is_refused_when_nobody_was_told(self, scene: Scene) -> None:
        result = scene.turn(
            reply(PASSED_ON),
            call("escalate", reason="client_asked_human", summary="The client wants a person."),
            reply(PASSED_ON),
            text="I want to talk to a person",
        )

        assert (result.status, result.text) == (Status.DONE, PASSED_ON)
        assert scene.run(result).guardrails == ["handover"]
        assert len(scene.world.all("SELECT id FROM escalations")) == 1

    def test_it_is_fine_while_a_case_is_open(self, scene: Scene) -> None:
        scene.tool("escalate", reason="client_asked_human", summary="The client wants a person.")

        result = scene.turn(reply("A person from DawaLink has been told."), text="any news?")

        assert scene.run(result).guardrails == []

    def test_after_two_tries_the_client_gets_our_own_words(self, scene: Scene) -> None:
        result = scene.turn(reply(PASSED_ON), reply(PASSED_ON), text="hello?")

        assert result.outcome == "guardrail_blocked"
        assert result.text != PASSED_ON


class TestWhatTheModelIsTold:
    def test_where_an_ask_for_a_person_stands_is_read_from_the_table(self, scene: Scene) -> None:
        scene.turn(reply("Hello."), text="hello")
        assert "A person from DawaLink: not asked for." in block(scene)

        scene.tool("escalate", reason="client_asked_human", summary="The client wants a person.")
        scene.turn(reply("A person was told."), text="any news?")
        assert "nobody has replied yet" in block(scene)
        assert "escalated" not in block(scene)  # the old flag is no longer shown

        (case,) = scene.world.all("SELECT id FROM escalations")
        admin = scene.world.make.user("admin", totp_secret=b"not-a-real-secret")
        tx = scene.world.tx()
        escalations.resolve(tx, admin, case.id, note="")
        scene.world.settle(tx)
        scene.turn(reply("How can I help?"), text="ok thanks")
        told = block(scene)
        assert "the team closed the client's earlier case" in told
        assert "escalate again" in told

    def test_a_running_watch_is_listed_with_its_id(self, scene: Scene) -> None:
        """Without it a later turn can't ask pharmacies for a watch it started itself."""
        watching = scene.tool("create_watch", product_id=scene.augmentin, days_of_use=7)

        scene.turn(reply("I'm still watching."), text="did you ask the pharmacies?")

        told = block(scene)
        assert f"watch_id {watching['watch_id']}" in told
        assert "no pharmacy asked yet" in told

    def test_the_language_is_the_one_of_the_clients_message(self, scene: Scene) -> None:
        scene.turn(reply("Hello! Which medicine do you need?"), text="hello")
        assert "The client's last message is in English: answer in it." in block(scene)

        scene.turn(reply("Shu baddak?", case_notes={"language": "arabizi"}), text="baddi dawa")
        assert "The client's last message is in Arabizi: answer in it." in block(scene)

        # Too little to tell: the language noted earlier stands.
        scene.turn(reply("Tayyeb."), text="ok")
        assert "Answer in Arabizi, the language the client has been using." in block(scene)

    def test_with_nothing_to_go_on_the_reply_is_in_english(self, scene: Scene) -> None:
        scene.turn(reply("Hello!"), text="h")

        assert "can't be told: answer in English" in block(scene)

    def test_the_questions_are_asked_once(self, scene: Scene) -> None:
        scene.turn(
            reply("Where, for how many days, and when?", case_notes={"questions_asked": True})
        )
        assert "You already asked" not in block(scene)

        scene.turn(reply("Searching."), text="any day")

        assert "You already asked your one round of questions" in block(scene)
        assert scene.conversation().case_state["questions_asked"] is True

    def test_once_asked_it_is_never_unasked(self, scene: Scene) -> None:
        scene.turn(reply("Where?", case_notes={"questions_asked": True}))
        scene.turn(reply("Ok.", case_notes={"questions_asked": False}), text="anywhere")

        assert scene.conversation().case_state["questions_asked"] is True


class TestTheRepliesLanguage:
    def test_arabizi_to_an_english_message_is_sent_back_once(self, scene: Scene) -> None:
        """Seen on 2026-11-22: "hello" answered "Marhaba! Kifak? Shou fi bdak…"."""
        result = scene.turn(
            reply("Marhaba! Kifak? Shou baddak lyom? Ekteb esm el dawa."),
            reply("Hello! Which medicine do you need?"),
            text="hello",
        )

        assert result.text == "Hello! Which medicine do you need?"
        assert scene.run(result).guardrails == ["language"]

    def test_arabizi_to_arabizi_is_right(self, scene: Scene) -> None:
        result = scene.turn(reply("Marhaba! Shu baddak lyom?"), text="marhaba, baddi dawa")

        assert scene.run(result).guardrails == []


class TestAChipBesideACard:
    def test_reserve_it_is_left_out_beside_a_card(self, scene: Scene) -> None:
        """Its tap would only send the words; the card's button reserves."""
        box = scene.stock()
        made = scene.tool("propose_reservation", listing_id=box, pickup_day=TODAY)
        turn = scene.tool_turn()

        checked = output_guard.check(
            scene.world.tx(),
            Reply(
                text="Here it is.",
                proposal_ids=[uuid.UUID(made["proposal_id"])],
                quick_replies=["Reserve it", "Show me other options", "No thanks"],
            ),
            conversation_id=scene.chat,
            client_id=scene.client,
            run_id=turn.run_id,
            client_text="I need Augmentin",
        )

        assert checked.reply.quick_replies == ["Show me other options", "No thanks"]
        assert checked.ok

    def test_start_sourcing_is_left_out_beside_its_card(self, scene: Scene) -> None:
        """`09` FA-53: "Yes, start sourcing" beside the [Start sourcing] card would only
        send the words; the client would think the request had started."""
        made = scene.tool(
            "prepare_request_summary",
            items=[{"product_id": str(scene.augmentin)}, {"product_id": str(scene.concor)}],
            alternatives_ok=False,
        )
        turn = scene.tool_turn()

        checked = output_guard.check(
            scene.world.tx(),
            Reply(
                text="Shall I look for both?",
                proposal_ids=[uuid.UUID(made["proposal_id"])],
                quick_replies=["Yes, start sourcing", "Add another medicine", "No thanks"],
            ),
            conversation_id=scene.chat,
            client_id=scene.client,
            run_id=turn.run_id,
            client_text="I need Augmentin and Concor",
        )

        assert checked.reply.quick_replies == ["Add another medicine", "No thanks"]

    def test_without_a_card_a_chip_is_only_an_answer(self, scene: Scene) -> None:
        checked = output_guard.check(
            scene.world.tx(),
            Reply(text="Shall I prepare it?", quick_replies=["Reserve it", "No thanks"]),
            conversation_id=scene.chat,
            client_id=scene.client,
            run_id=scene.tool_turn().run_id,
            client_text="I need Augmentin",
        )

        assert checked.reply.quick_replies == ["Reserve it", "No thanks"]


class TestTheChatWithTheTeam:
    """The owner, 2026-11-22: after an admin replies, the chat is between them until the
    admin closes the case."""

    @pytest.fixture
    def held(self, scene: Scene) -> dict[str, Any]:
        """A chat the team has replied in."""
        scene.turn(
            call("escalate", reason="client_asked_human", summary="The client wants a person."),
            reply(PASSED_ON),
            text="I want to talk to a person",
        )
        (case,) = scene.world.all("SELECT id FROM escalations")
        admin = scene.world.make.user("admin", totp_secret=b"not-a-real-secret")
        tx = scene.world.tx()
        post_team_reply(tx, admin_id=admin, escalation_id=case.id, text="Hello, how can we help?")
        scene.world.settle(tx)
        return {"case": case.id, "admin": admin}

    def to_the_team(self, scene: Scene, text: str) -> int:
        """A message stored the way the API stores one in a held chat."""
        tx = scene.world.tx()
        posted = post_client_message(
            tx,
            client_id=scene.client,
            conversation_id=scene.chat,
            text=text,
            client_message_id=uuid.uuid4(),
            to_the_team=True,
        )
        scene.world.settle(tx)
        return posted.seq

    def close(self, scene: Scene, held: dict[str, Any]) -> None:
        tx = scene.world.tx()
        escalations.resolve(tx, held["admin"], held["case"], note="")
        scene.world.settle(tx)

    def test_the_assistant_says_nothing_in_a_held_chat(
        self, scene: Scene, held: dict[str, Any]
    ) -> None:
        before = len(scene.messages())
        self.to_the_team(scene, "my order was wrong")

        result = run_turn(
            scene.agent(reply("This must never be sent.")), scene.chat, runs_in="chat"
        )

        assert result.status is Status.NOTHING
        assert scene.model.seen == []  # no model call at all
        assert [m.author for m in scene.messages()[before:]] == ["client"]

    def test_after_the_close_it_does_not_answer_what_was_said_to_the_team(
        self, scene: Scene, held: dict[str, Any]
    ) -> None:
        self.to_the_team(scene, "my order was wrong")
        self.to_the_team(scene, "can you call the pharmacy")
        self.close(scene, held)

        # Nothing to answer: the two messages were the team's.
        waiting = run_turn(scene.agent(reply("Never sent.")), scene.chat, runs_in="chat")
        assert waiting.status is Status.NOTHING

        result = scene.turn(reply("Looking for Augmentin."), text="now find me augmentin")

        assert result.status is Status.DONE
        told = block(scene)
        assert "client, to the DawaLink team (not to you): my order was wrong" in told
        assert "client, to the DawaLink team (not to you): can you call the pharmacy" in told
        assert "client: now find me augmentin" in told
        assert "team_closed: the DawaLink team closed the client's case" in told
        assert "DawaLink team: Hello, how can we help?" in told

    @pytest.mark.rows_by_hand  # an order made without its stock, for the event only
    def test_an_event_in_a_held_chat_waits_and_is_looked_at_on_the_close(
        self, scene: Scene, held: dict[str, Any]
    ) -> None:
        order = scene.world.make.order(
            client_id=scene.client, pharmacy_id=scene.pharmacy, product_id=scene.augmentin
        )
        tx = scene.world.tx()
        events.post_decision(tx, scene.chat, Decision.NOT_AVAILABLE, order_id=order, units=1)
        scene.world.settle(tx)

        result = run_turn(scene.agent(reply("Never sent.")), scene.chat, runs_in="worker")

        assert result.status is Status.NOTHING
        hold_ends = scene.world.tx().now + TEAM_HOLD
        assert scene.conversation().pending_turn_at == hold_ends

        self.close(scene, held)

        assert scene.conversation().pending_turn_at == scene.world.tx().now
        after = run_turn(scene.agent(reply("That box is gone.")), scene.chat, runs_in="worker")
        assert after.status is Status.DONE

    def test_a_forgotten_case_gives_the_chat_back_after_the_hold(
        self, scene: Scene, held: dict[str, Any]
    ) -> None:
        """N-55: nobody closed the case. The next message is the assistant's, and one
        card says so, to the client and to the agent's side."""
        self.to_the_team(scene, "hello? anyone?")
        scene.world.later(hours=TEAM_HOLD.total_seconds() / 3600, seconds=1)
        assert not escalations.held_by_team(scene.world.tx(), scene.chat)

        result = scene.turn(reply("I'm here. Which medicine?"), text="I need Augmentin")

        assert result.status is Status.DONE
        cards = [m.cards[0]["template"] for m in scene.messages() if m.kind == "card"]
        assert cards == ["assistant_back"]
        told = block(scene)
        assert "client, to the DawaLink team (not to you): hello? anyone?" in told
        assert "assistant_back: the DawaLink team stopped answering" in told
        assert "client: I need Augmentin" in told

    def test_a_reply_that_arrives_during_a_turn_is_not_talked_over(self, scene: Scene) -> None:
        """The team replied while the assistant was still writing: its reply is dropped."""
        scene.tool("escalate", reason="client_asked_human", summary="The client wants a person.")
        (case,) = scene.world.all("SELECT id FROM escalations")
        admin = scene.world.make.user("admin", totp_secret=b"not-a-real-secret")

        def the_team_replies_meanwhile(prompt: Any) -> Any:
            tx = scene.world.tx()
            post_team_reply(tx, admin_id=admin, escalation_id=case.id, text="We are here.")
            scene.world.settle(tx)
            return reply("A person was told.")

        result = scene.turn(the_team_replies_meanwhile, text="any news?")

        assert result.status is Status.NOTHING
        assert [m.author for m in scene.messages()][-2:] == ["client", "admin"]
        # What the turn read is kept: the same message is not answered again later.
        client_seq = scene.messages()[-2].seq
        assert scene.conversation().case_state["read_up_to"] >= client_seq


class TestWhichMessagesWereForTheTeam:
    """Read from the messages, with nothing stored (`escalations.to_the_team`)."""

    @staticmethod
    def adder(scene: Scene) -> Any:
        tx = scene.world.tx()
        chat = conversations.locked(tx, scene.chat)

        def add(author: str, text: str | None = "x", **more: Any) -> int:
            kind = more.pop("kind", "text")
            return conversations.append(tx, chat, author=author, kind=kind, text=text, **more).seq

        return tx, add

    def test_only_a_card_gives_the_chat_back_never_a_message_of_the_assistant(
        self, scene: Scene
    ) -> None:
        """Found by review: in a request's thread the assistant still writes while the team
        has the thread, and what the client writes there stays the team's."""
        tx, add = self.adder(scene)
        add("client")
        add("agent")
        add("admin")
        first = add("client")
        add("agent")  # the assistant re-planned on an event: the hold goes on
        second = add("client")
        add("system", None, kind="card", cards=[{"template": "team_closed"}])
        add("client")
        add("admin")
        third = add("client")
        add("system", None, kind="card", cards=[{"template": "reserved", "order_ref": "R-AAAAAA"}])
        fourth = add("client")  # a reservation card gives nothing back

        messages = conversations.history(tx, scene.chat)

        assert escalations.to_the_team(tx, scene.chat, messages) == {first, second, third, fourth}
        assert escalations.team_has_the_last_word(tx, scene.chat, messages)

    def test_a_long_exchange_does_not_push_the_teams_reply_out_of_sight(self, scene: Scene) -> None:
        """A turn reads its last 20 messages: the team's reply may be older than that."""
        tx, add = self.adder(scene)
        add("admin")
        written = [add("client") for _ in range(25)]

        window = conversations.history(tx, scene.chat)

        assert len(window) == 20
        assert escalations.to_the_team(tx, scene.chat, window) == set(written[-20:])
        assert escalations.team_has_the_last_word(tx, scene.chat, window)

    def test_a_hand_back_older_than_the_window_still_counts(self, scene: Scene) -> None:
        tx, add = self.adder(scene)
        add("admin")
        add("system", None, kind="card", cards=[{"template": "assistant_back"}])
        for _ in range(25):
            add("client")

        window = conversations.history(tx, scene.chat)

        assert escalations.to_the_team(tx, scene.chat, window) == set()
        assert not escalations.team_has_the_last_word(tx, scene.chat, window)


class TestAnEventWaitingInAChatThatIsPutAway:
    @pytest.mark.rows_by_hand  # an order made without its stock, for the event only
    def test_new_chat_takes_the_waiting_event_along(self, scene: Scene) -> None:
        """Found by review: an archived chat gets no turn, and while the team had the chat
        the event's turn was put off for hours."""
        order = scene.world.make.order(
            client_id=scene.client, pharmacy_id=scene.pharmacy, product_id=scene.augmentin
        )
        tx = scene.world.tx()
        events.post_decision(tx, scene.chat, Decision.NOT_AVAILABLE, order_id=order, units=1)
        scene.world.settle(tx)

        tx = scene.world.tx()
        fresh = conversations.new_chat(tx, scene.client)
        scene.world.settle(tx)

        assert fresh.id != scene.chat
        assert scene.conversation().pending_turn_at is None  # the old chat asks for nothing
        assert scene.conversation(fresh.id).pending_turn_at is not None
        result = run_turn(scene.agent(reply("That box is gone.")), fresh.id, runs_in="worker")
        assert result.status is Status.DONE
        assert "not_available: the pharmacy marked order" in block(scene)

    def test_new_chat_with_nothing_waiting_starts_empty(self, scene: Scene) -> None:
        scene.turn(reply("Hello."), text="hello")

        tx = scene.world.tx()
        fresh = conversations.new_chat(tx, scene.client)
        scene.world.settle(tx)

        assert scene.messages(fresh.id) == []
        assert scene.conversation(fresh.id).pending_turn_at is None


class TestAReplyNextToACallThatNeverRan:
    def test_a_call_past_the_turns_limit_does_not_void_the_reply(self, scene: Scene) -> None:
        """Found by review: the tool never ran, so the reply can't be wrong about it."""
        searches = [call("search_catalog", query="augmentin") for _ in range(6)]

        result = scene.turn(
            *searches,
            calls(
                ("search_catalog", {"query": "concor"}),  # the 7th: refused, never run
                ("reply", {"text": "I found Augmentin 1 g."}),
            ),
        )

        assert (result.status, result.text) == (Status.DONE, "I found Augmentin 1 g.")
        assert len(scene.tool_calls(result)) == 6
