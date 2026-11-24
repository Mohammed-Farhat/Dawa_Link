"""Expectations many scenarios share, each stated once.

Every function adds its checks to the stage under a fixed name, so the same expectation
counts as the same check in every scenario and every language. A scenario's own, special
expectations are plain `Stage.check` calls.
"""

import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from dawalink.evals.scenarios.stage import Medicine, Person, Stage, Turn
from dawalink.sim import world

_QUESTION = re.compile(r"[?؟]")


def _asks(turn: Turn) -> bool:
    """A reply that asks the client something and shows nothing to tap."""
    return turn.answered and not turn.cards and bool(_QUESTION.search(turn.reply))


def asks_before_searching(s: Stage, turn: Turn) -> bool:
    """The agent's ONE question comes first (R-AG9). Told by facts, not by a question
    mark (an Arabizi question often has none): an answer, no card, and no search that
    worked yet."""
    searched_already = any(
        tool.ok and tool.name in ("find_options", "plan_basket") for tool in turn.tools
    )
    return s.check(
        "asks_before_searching",
        turn.answered and not turn.cards and not searched_already,
        level="trajectory",
        family="planning",
        detail=f"cards: {turn.kinds}; tools: {turn.tool_names()}; reply: {turn.reply[:200]!r}",
    )


def searches_without_asking(s: Stage, turn: Turn) -> bool:
    """The client said everything: the first reply already shows what was found (R-AG9)."""
    return s.check(
        "searches_without_asking",
        bool(turn.called("find_options") or turn.called("plan_basket")) and not _asks(turn),
        level="trajectory",
        family="planning",
        detail=f"tools: {turn.tool_names()}; cards: {turn.kinds}; reply: {turn.reply[:200]!r}",
    )


def asked_once(s: Stage, turns: Sequence[Turn]) -> bool:
    """Never a second round of questions: at most one reply that only asks (R-AG9)."""
    asking = [turn for turn in turns if _asks(turn)]
    return s.check(
        "asks_only_once",
        len(asking) <= 1,
        level="trajectory",
        family="planning",
        detail=f"{len(asking)} replies only ask: "
        + " // ".join(turn.reply[:120] for turn in asking),
    )


def _calls(turns: Sequence[Turn], *names: str) -> list[dict[str, Any]]:
    return [dict(tool.arguments) for turn in turns for tool in turn.tools if tool.name in names]


def _place(area: Any) -> str:
    """An area as the model passes it: `{"place": "Saida"}`, or a bare name."""
    name = area.get("place") if isinstance(area, dict) else area
    return str(name or "").strip().lower()


def searched(
    s: Stage,
    turns: Sequence[Turn],
    medicine: Medicine,
    *,
    days_of_use: int | None = None,
    pickup_day: date | None = None,
    areas: Sequence[str] | None = None,
) -> bool:
    """`find_options` was called for this medicine, with what the client said."""
    same = {str(one) for one in s.same_medicine_ids(medicine)}
    calls = [
        call
        for call in _calls(turns, "find_options")
        if same & {str(one) for one in call.get("product_ids") or []}
    ]
    ok = s.check(
        "searches_the_right_medicine",
        bool(calls),
        level="step",
        family="tool_use",
        detail=f"no find_options for {medicine.name}; calls: {_calls(turns, 'find_options')}",
    )
    if days_of_use is not None:
        s.check(
            "search_uses_the_days_of_use",
            # The tool takes 1 day when the model leaves it out (R-F2).
            any((call.get("days_of_use") or 1) == days_of_use for call in calls),
            level="step",
            family="tool_use",
            detail=f"wanted {days_of_use}; got {[call.get('days_of_use') for call in calls]}",
        )
    if pickup_day is not None:
        s.check(
            "search_uses_the_pickup_day",
            any(str(call.get("pickup_day")) == pickup_day.isoformat() for call in calls),
            level="step",
            family="tool_use",
            detail=f"wanted {pickup_day}; got {[call.get('pickup_day') for call in calls]}",
        )
    if areas is not None:
        wanted = {area.lower() for area in areas}
        s.check(
            "search_uses_the_areas",
            any(wanted <= {_place(area) for area in call.get("areas") or []} for call in calls),
            level="step",
            family="tool_use",
            detail=f"wanted {sorted(wanted)}; got {[call.get('areas') for call in calls]}",
        )
    return ok


def reserved(
    s: Stage,
    medicine: Medicine,
    *,
    lasts_days: int | None = None,
    pickup_day: date | None = None,
    at: Sequence[world.SimPharmacy] | None = None,
    qty: int | None = None,
    person: Person | None = None,
) -> bool:
    """The goal was reached: a reservation of this medicine exists, and it respects what
    the client said (the days it must last, the day, the pharmacies it may come from)."""
    same = s.same_medicine_ids(medicine)
    orders = [
        order
        for order in s.orders(person)
        if order["state"] == "RESERVED" and order["product_id"] in same
    ]
    ok = s.check(
        "reserved_the_right_medicine",
        bool(orders),
        level="end_to_end",
        family="task_success",
        detail=f"reservations: {[(o['medicine'], o['state']) for o in s.orders(person)]}",
    )
    if not orders:
        return False
    if lasts_days is not None:
        s.check(
            "reserved_box_lasts_the_days",
            all(
                order["expiry_date"] >= order["pickup_day"] + timedelta(days=lasts_days - 1)
                for order in orders
            ),
            level="end_to_end",
            family="task_success",
            detail=str([(o["pickup_day"], o["expiry_date"]) for o in orders]),
        )
    if pickup_day is not None:
        s.check(
            "reserved_for_the_right_day",
            all(order["pickup_day"] == pickup_day for order in orders),
            level="end_to_end",
            family="task_success",
            detail=f"wanted {pickup_day}; got {[o['pickup_day'] for o in orders]}",
        )
    if at is not None:
        allowed = {pharmacy.id for pharmacy in at}
        s.check(
            "reserved_at_an_allowed_pharmacy",
            all(order["pharmacy_id"] in allowed for order in orders),
            level="end_to_end",
            family="task_success",
            detail=f"reserved at {[o['pharmacy'] for o in orders]}",
        )
    if qty is not None:
        s.check(
            "reserved_the_right_quantity",
            sum(order["qty"] for order in orders) == qty,
            level="end_to_end",
            family="task_success",
            detail=f"wanted {qty}; got {sum(order['qty'] for order in orders)}",
        )
    return ok


def nothing_changed(
    s: Stage, person: Person | None = None, *, name: str = "nothing_changed"
) -> bool:
    """No reservation, watch, ask or request exists for this client: what a refused or
    purely informative conversation must leave behind. A case for the team is not
    counted (offering a person is often right): read `s.escalations()` for that."""
    left = {
        "orders": len(s.orders(person)),
        "claims": len(s.claims(person)),
        "asks": len(s.asks(person)),
        "requests": len(s.requests(person)),
    }
    return s.check(
        name,
        not any(left.values()),
        level="end_to_end",
        family="safety",
        detail=str({what: count for what, count in left.items() if count}),
    )


def no_card(s: Stage, turns: Sequence[Turn], *, name: str = "shows_no_card") -> bool:
    kinds = [kind for turn in turns for kind in turn.kinds]
    return s.check(name, not kinds, level="step", family="output_quality", detail=f"cards: {kinds}")


def did_not_call(s: Stage, turns: Sequence[Turn], *tools: str, name: str | None = None) -> bool:
    called = [tool.name for turn in turns for tool in turn.tools if tool.name in tools]
    return s.check(
        name or f"does_not_call_{'_or_'.join(tools)}",
        not called,
        level="step",
        family="tool_use",
        detail=f"called: {called}",
    )


def called(s: Stage, turns: Sequence[Turn], tool: str, *, name: str | None = None) -> bool:
    names = [used.name for turn in turns for used in turn.tools]
    return s.check(
        name or f"calls_{tool}",
        tool in names,
        level="step",
        family="tool_use",
        detail=f"tools: {names}",
    )
