"""The agent's races, with two real connections (docs/04 R-AG2, R-AG7; docs/09 FA-15, FA-20, FA-23).

As in `test_races.py`, both actions are inside open transactions before either may
continue, so the outcome never depends on luck.
"""

import uuid
from typing import Any

from dawalink.agent.turn import turn_is_done
from dawalink.domain.vocabulary import ProposalKind
from dawalink.services import conversations, events, proposals
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.events import Decision
from dawalink.services.proposals import CardText
from tests.db.factories import TODAY
from tests.races.conftest import Arena

PRICE = 600_000  # a 1,000,000 LBP box with 60 days left: 40% off


class TestTheTurnLease:
    def test_two_turns_at_once_on_one_conversation_only_one_runs(self, arena: Arena) -> None:
        """FA-15, R-AG2: a chat message and a worker event start a turn at the same moment."""
        chat = arena.make.conversation()

        results = arena.together(
            lambda tx: conversations.take_lease(tx, chat, "the-chat-turn"),
            lambda tx: conversations.take_lease(tx, chat, "the-worker-turn"),
            hold="conversations",
        )

        assert sorted(results) == [False, True]
        owner = arena.one("SELECT turn_owner FROM conversations WHERE id = :c", c=chat).turn_owner
        assert owner in ("the-chat-turn", "the-worker-turn")

    def test_an_event_at_the_moment_a_turn_is_saved_still_gets_its_turn(self, arena: Arena) -> None:
        """FA-20: whichever commits first, the conversation is left asking for a turn."""
        chat = arena.make.conversation()
        arena.run(lambda tx: events.post_decision(tx, chat, Decision.WINDOW_CHECK, items=[]))
        handled = arena.one(
            "SELECT max(seq) AS seq FROM chat_messages WHERE conversation_id = :c", c=chat
        ).seq

        def save_the_turn(tx: Tx) -> None:
            turn_is_done(tx, conversations.locked(tx, chat), handled)

        def a_new_event(tx: Tx) -> None:
            events.post_decision(tx, chat, Decision.NOT_AVAILABLE, units=1)

        results = arena.together(save_the_turn, a_new_event, hold="conversations")

        assert results == [None, None]
        row = arena.one("SELECT pending_turn_at FROM conversations WHERE id = :c", c=chat)
        assert row.pending_turn_at is not None


class TestACardTappedTwice:
    def test_a_double_tap_reserves_once(self, arena: Arena) -> None:
        """FA-23, INV-21: a card works once, even when two taps arrive together."""
        client = arena.make.client()
        chat = arena.make.conversation(client_id=client)
        item = arena.make.item(days_left=60, qty_on_hand=3)

        def make_card(tx: Tx) -> uuid.UUID:
            return proposals.create(
                tx,
                conversation_id=chat,
                client_id=client,
                kind=ProposalKind.RESERVE,
                payload={
                    "listing_id": str(item),
                    "qty": 1,
                    "price_lbp_shown": PRICE,
                    "pickup_day": TODAY.isoformat(),
                    "days_of_use": 1,
                    "request_item_id": None,
                },
                card=CardText("A box", []),
                run_id=None,
            ).id

        card = arena.run(make_card)

        def tap(tx: Tx) -> Any:
            return proposals.execute(tx, client_id=client, proposal_id=card)

        results = arena.together(tap, tap, hold="proposals")

        refused = [result for result in results if isinstance(result, ServiceError)]
        assert [error.code for error in refused] == [Code.PROPOSAL_USED]
        row = arena.one("SELECT qty_reserved FROM inventory_items WHERE id = :i", i=item)
        assert row.qty_reserved == 1
        assert arena.one("SELECT count(*) AS n FROM orders WHERE client_id = :c", c=client).n == 1
