"""Scoring a conversation with a played client (docs/08 E7).

Everything is read from what the agent did (its tool calls, its cards, the questions in
its replies), never from a second model's opinion of the conversation.

**The limit to keep in mind:** what the client had told the agent at each turn comes from
the playing model's own report of its message (`Said.says`). A message that says "bukra"
and is reported without "day" makes `asks_again` too kind and `waits_until_told` too
strict, and the other way round. The saved conversations are there to be read.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from dawalink.evals.played_client import FACTS, Persona
from dawalink.evals.score_understanding import (
    RESERVE_CARDS,
    Seen,
    _asked,
    _used,
    acted,
    asks_about,
    together,
)


@dataclass(frozen=True)
class Exchange:
    """One message of the client and the agent's turn that answered it."""

    said: str
    says: Sequence[str]
    seen: Seen


def has_cards(seen: Seen) -> bool:
    return any(card in RESERVE_CARDS for card in seen.cards)


def score(
    persona: Persona,
    exchanges: Sequence[Exchange],
    *,
    products: Sequence[Sequence[str]],
    today: date,
) -> dict[str, bool | None]:
    """Every check for one conversation. `products[i]` are the catalog products that are
    a right answer for the persona's i-th medicine."""
    result: dict[str, bool | None] = dict.fromkeys(CHECKS)
    if not exchanges:
        return result
    whole = together([exchange.seen for exchange in exchanges])
    searched = {a.product_id for a in _asked(whole)}

    result["gets_cards"] = has_cards(exchanges[-1].seen)
    result["right_medicine"] = all(
        searched & {str(product) for product in accepted} for accepted in products
    )
    result["searches_with_the_truth"] = _used(persona.truth, whole, today)

    told: set[str] = set()
    waited: bool | None = None
    again = False
    for exchange in exchanges:
        told |= set(exchange.says)
        if acted(exchange.seen):
            # A search, a plan or a card: only once the client has said all three.
            waited = (waited is not False) and told >= set(FACTS)
        again = again or bool(set(asks_about(exchange.seen.reply)) & told)
    result["waits_until_told"] = waited
    result["asks_again"] = again
    if persona.style == "all_at_once":
        result["first_message_is_enough"] = has_cards(exchanges[0].seen)
    return result


# The checks, and whether a "yes" is good.
CHECKS: Mapping[str, bool] = {
    "gets_cards": True,  # the conversation ended with something to reserve
    "right_medicine": True,
    "searches_with_the_truth": True,  # the day, the days of use and, on foot, walking
    "waits_until_told": True,  # nothing searched or proposed before all three were said
    "asks_again": False,  # asks for something the client had already said
    "first_message_is_enough": True,  # a client who says everything gets cards at once
}
