"""When a tool, the model or a service fails (the course's chapter 9: "tests robustness
when tools fail"; docs/07 §8; docs/09 FX-1, FX-18, FA-39, FA-40; docs/04 R-AG10).

Each story breaks one thing on purpose (`faults.py`), looks at what the agent did with
the failure, then mends it and checks that the client's goal is still reached: recovery,
family `reliability`. A check that is true by construction of the fault (no watch when
`create_watch` always fails) is not written: what the agent *says* about the failure is
the judge's, from `expected`.

Two automatic checks fail here by design and are not findings: `tool_calls_succeed` and,
for a tool tried twice alike, `no_repeated_tool_call`.
"""

import uuid
from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy import delete, insert

from dawalink.db.models import TravelTimeCache, User
from dawalink.evals.scenarios import expect
from dawalink.evals.scenarios.cases.request import (
    cards_of,
    claims_say,
    days_said,
    find_them,
    in_thread,
    items_say,
    notice_is,
    open_pharmacies,
    orders_say,
    own_client,
    request_of,
    reserved_of,
    start_request,
    worked,
)
from dawalink.evals.scenarios.scenario import Scenario
from dawalink.evals.scenarios.stage import AdminActor, Stage, StageError, Turn
from dawalink.sim import world

SEARCHES = ("find_options", "plan_basket")


def _succeeded(turns: Sequence[Turn], *names: str) -> bool:
    return any(tool.ok for turn in turns for tool in turn.tools if tool.name in names)


def _tried(turns: Sequence[Turn], *names: str) -> list[bool]:
    return [tool.ok for turn in turns for tool in turn.tools if tool.name in names]


# Beirut's clients, counted from the end (`request.own_client`): the fail family's English
# plays take 0 to 9, the request family 10 to 21, 42 and 43 (one client in every language:
# it sets no fault), the fail family's Arabizi plays 22 to 31 and its Arabic plays 32 to 41.
# A story that breaks only the model needs no slot per language: the model's fault belongs
# to its own play (`run.play` makes one `FlakyModel` per play). It takes 44.
_FIRST_SLOT = {"english": 0, "arabizi": 22, "arabic": 32}


def _alone(s: Stage, slot: int) -> None:
    """A client of its own for a story that breaks something (`request.own_client`).

    The runner plays a scenario's three languages side by side in one process, so each
    language needs its own client too: this is the one place a story reads `s.lang`, and
    only to choose that client, never the story. `--repeat` still shares one client
    between the repeats of a language (harness gap, reported).
    """
    own_client(s, _FIRST_SLOT[s.lang] + slot)


def _fault_held(turns: Sequence[Turn], *names: str, first_call_only: bool = False) -> None:
    """The broken tool must really have failed in the faulted turns. A call that came back
    ok means another play mended this client's tools: the harness's mistake, never the
    agent's. A tool the agent never called is the agent's own path, and is no error."""
    calls = [tool.ok for turn in turns for tool in turn.tools if tool.name in names]
    held = not calls or (not calls[0] if first_call_only else not any(calls))
    if not held:
        raise StageError(f"The fault on {names} didn't hold ({calls}): another play mended it.")


def _asks_say(s: Stage) -> str:
    return str([(a["pharmacy"], a["state"]) for a in s.asks()])


def _ends_with_a_reply(s: Stage, turn: Turn, *, name: str = "ends_with_a_reply") -> bool:
    return s.check(
        name,
        turn.answered and all(outcome == "ok" for outcome in turn.outcomes),
        level="step",
        family="reliability",
        detail=f"outcomes {turn.outcomes}; reply {turn.reply[:160]!r}",
    )


def _names_no_pharmacy(s: Stage, turn: Turn) -> bool:
    named = [p.name for p in s.pharmacies() if p.name.lower() in turn.reply.lower()]
    return s.check(
        "names_no_pharmacy",
        not named,
        level="component",
        family="output_quality",
        detail=f"the reply names {named}, which no tool of the turn returned",
    )


def _everything_now(medicine: tuple[str, str, str], days: int) -> dict[str, str]:
    en, az, ar = medicine
    az_days, ar_days = days_said(days)
    return {
        "en": f"I need {en}, for {days} days, from the nearest pharmacy. I can pick it up today.",
        "az": f"baddi {az}, la {az_days}, mn a2rab saydaliyye. fiyye jibo lyom.",
        "ar": f"بدي {ar}، لـ{ar_days}، من أقرب صيدلية. فيني جيبو اليوم.",
    }


_TRY_AGAIN = {
    "en": "Can you please try again?",
    "az": "fik tjarreb kamen marra please?",
    "ar": "فيك تجرّب كمان مرة من فضلك؟",
}


# --- a tool fails --------------------------------------------------------------------------


def _find_once(s: Stage) -> None:
    _alone(s, 0)
    brufen = s.medicine("brufen", "400mg")
    notice_is(s, not_needed=(brufen,))
    near, second = s.nearest(2)
    s.stock(brufen, near, days=90)
    s.stock(brufen, second, days=60)
    s.fault.tool("find_options", times=1)

    first = s.client.say(_everything_now(("Brufen 400", "brufen 400", "بروفين 400"), 5))
    turns = [first]
    if "reserve" not in first.kinds and "reserve_group" not in first.kinds:
        turns += s.client.converse(max_messages=2)
    _fault_held([first], "find_options", first_call_only=True)
    s.check(
        "searches_again_after_the_failure",
        _succeeded(turns, *SEARCHES),
        level="trajectory",
        family="reliability",
        detail=f"searches: {_tried(turns, *SEARCHES)}",
    )
    expect.searched(s, turns, brufen, days_of_use=5, pickup_day=s.today)
    shown = cards_of(turns, ("reserve",))
    s.check(
        "reaches_the_options_after_the_failure",
        bool(shown),
        level="end_to_end",
        family="reliability",
        detail=f"cards: {[t.kinds for t in turns]}",
    )
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, brufen, lasts_days=5, pickup_day=s.today)


def _search_down(s: Stage) -> None:
    _alone(s, 1)
    augmentin = s.medicine("augmentin", "1g")
    notice_is(s, needed=(augmentin,))
    near = s.nearest(1)[0]
    s.stock(augmentin, near, days=90)
    # Both ways of searching are broken: plan_basket would be a fair way round one of them.
    s.fault.tool("find_options", times=None)
    s.fault.tool("plan_basket", times=None)

    first = s.client.say(_everything_now(("Augmentin 1g", "augmentin 1g", "أوغمنتين 1 غرام"), 7))
    _fault_held([first], *SEARCHES)
    expect.called(s, [first], "find_options", name="tries_to_search")
    _ends_with_a_reply(s, first)
    expect.no_card(s, [first], name="no_card_without_a_search")
    _names_no_pharmacy(s, first)
    expect.nothing_changed(s, name="acts_on_nothing_it_could_not_see")
    s.fault.clear()
    again = s.client.say(_TRY_AGAIN)
    expect.searched(s, [again], augmentin, days_of_use=7)
    shown = cards_of([again], ("reserve",))
    s.check(
        "works_again_once_the_tool_is_back",
        bool(shown),
        level="end_to_end",
        family="reliability",
        detail=f"cards {again.kinds}; tools {again.tool_names()}",
    )
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, augmentin, lasts_days=7)


def _card_tool_down(s: Stage) -> None:
    _alone(s, 2)
    crestor = s.medicine("crestor", "20mg")
    notice_is(s, needed=(crestor,))
    near, second = s.nearest(2)
    s.stock(crestor, near, days=120)
    s.stock(crestor, second, days=100)
    s.fault.tool("propose_reservation", times=None)
    s.fault.tool("propose_plan", times=None)

    first = s.client.say(_everything_now(("Crestor 20", "crestor 20", "كريستور 20"), 30))
    _fault_held([first], "propose_reservation", "propose_plan")
    expect.searched(s, [first], crestor, days_of_use=30, pickup_day=s.today)
    expect.called(s, [first], "propose_reservation", name="tries_to_make_the_card")
    _ends_with_a_reply(s, first)
    expect.nothing_changed(s, name="starts_nothing_for_a_listed_medicine")
    s.fault.clear()
    again = s.client.say(_TRY_AGAIN)
    turns = [again]
    if "reserve" not in again.kinds:
        turns += s.client.converse(max_messages=1)
    shown = cards_of(turns, ("reserve",))
    s.check(
        "works_again_once_the_tool_is_back",
        bool(shown),
        level="end_to_end",
        family="reliability",
        detail=f"cards {[t.kinds for t in turns]}; tools {[t.tool_names() for t in turns]}",
    )
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, crestor, lasts_days=30)


def _watch_down(s: Stage) -> None:
    _alone(s, 3)
    amaryl = s.medicine("amaryl", "2mg")
    notice_is(s, needed=(amaryl,))
    holder = open_pharmacies(s, 1)[0]
    s.stock(amaryl, holder, days=200, qty=4)  # the early-release zone: private
    s.fault.tool("create_watch", times=None)

    first = s.client.say(_everything_now(("Amaryl 2", "amaryl 2", "أماريل 2"), 30))
    _fault_held([first], "create_watch")
    expect.searched(s, [first], amaryl, days_of_use=30)
    expect.called(s, [first], "create_watch", name="tries_to_start_the_watch")
    _ends_with_a_reply(s, first)
    s.fault.clear()
    again = s.client.say(
        {
            "en": "Can you try again to watch for it and ask the pharmacies?",
            "az": "fik tjarreb kamen marra tontor-li yeh w tes2al el saydaliyyet?",
            "ar": "فيك تجرّب كمان مرة تراقبلي ياه وتسأل الصيدليات؟",
        }
    )
    watches = [c for c in s.claims() if c["kind"] == "WATCH"]
    s.check(
        "starts_the_watch_once_the_tool_is_back",
        any(c["state"] in ("ACTIVE", "OFFER_PENDING") for c in watches),
        level="end_to_end",
        family="reliability",
        detail=f"tools {again.tool_names()}; claims {claims_say(s)}",
    )
    s.check(
        "asks_the_pharmacy_once_the_tool_is_back",
        any(a["pharmacy_id"] == holder.id for a in s.asks()),
        level="step",
        family="reliability",
        detail=f"asks {[(a['pharmacy'], a['state']) for a in s.asks()]}; holder {holder.name}",
    )
    s.check(
        "one_watch_only",
        len(watches) <= 1,
        level="component",
        family="tool_use",
        detail=f"{len(watches)} watches",
    )


def _ask_down(s: Stage) -> None:
    _alone(s, 4)
    finallerg = s.medicine("finallerg", "10mg")
    notice_is(s, not_needed=(finallerg,))
    holder = open_pharmacies(s, 1)[0]
    s.stock(finallerg, holder, days=200, qty=3)  # the early-release zone: private
    s.fault.tool("request_early_release", times=None)

    first = s.client.say(_everything_now(("Finallerg 10", "finallerg 10", "فينالرج 10"), 10))
    _fault_held([first], "request_early_release")
    s.check(
        "the_watch_still_starts",
        any(c["kind"] == "WATCH" and c["state"] == "ACTIVE" for c in s.claims()),
        level="step",
        family="tool_use",
        detail=f"tools {first.tool_names()}; claims {claims_say(s)}",
    )
    expect.called(s, [first], "request_early_release", name="tries_to_ask_the_pharmacies")
    _ends_with_a_reply(s, first)
    s.fault.clear()
    again = s.client.say(
        {
            "en": "Did you ask the pharmacies?",
            "az": "s2alt el saydaliyyet?",
            "ar": "سألت الصيدليات؟",
        }
    )
    # BLD-D55 decides what the agent does in the turn that finds nothing listed; no rule
    # says whether, after a failed ask, it asks again at once or offers to. Both reach the
    # goal, so only the end is checked (one more answer of the client is allowed); whether
    # it retried on its own is for the judge, from `expected`.
    turns = [again]
    if not _succeeded([again], "request_early_release"):
        reply = s.client.answer()
        turns += [reply] if reply is not None else []
    s.check(
        "the_pharmacies_are_asked_once_the_tool_is_back",
        _succeeded(turns, "request_early_release")
        and any(a["pharmacy_id"] == holder.id for a in s.asks()),
        level="end_to_end",
        family="reliability",
        detail=f"tools {[t.tool_names() for t in turns]}; asks {_asks_say(s)}",
    )
    s.check(
        "uses_the_watch_already_running",
        len([c for c in s.claims() if c["kind"] == "WATCH"]) == 1,
        level="component",
        family="memory",
        detail=f"claims {[(c['kind'], c['state']) for c in s.claims()]}",
    )


def _admin(s: Stage) -> AdminActor:
    """Someone of DawaLink's team. `Stage.admin` makes an admin without the authenticator
    secret the `users` table requires of one (`ck_users_admin_has_totp`), so the admin is
    made here, the same way plus an invented secret (harness gap, reported)."""
    if s._admin is None:
        admin_id = uuid.uuid4()
        with s.setup() as session:
            session.execute(
                insert(User),
                [
                    {
                        "id": admin_id,
                        "email": "admin@sim.dawalink.test",
                        "password_hash": world.NO_PASSWORD,
                        "role": "admin",
                        "full_name": "Sim Admin",
                        "email_verified_at": s.now,
                        "totp_secret": b"sim-invented-not-a-secret",
                    }
                ],
            )
        s._admin = AdminActor(s, admin_id)
    return s._admin


def _escalate_down(s: Stage) -> None:
    _alone(s, 5)
    s.fault.tool("escalate", times=None)
    first = s.client.say(
        {
            "en": "I want to talk to a person from DawaLink, please.",
            "az": "baddi ehke ma3 7ada men DawaLink please.",
            "ar": "بدي إحكي مع حدا من DawaLink من فضلك.",
        }
    )
    _fault_held([first], "escalate")
    expect.called(s, [first], "escalate", name="tries_to_hand_over")
    _ends_with_a_reply(s, first)
    s.fault.clear()
    again = s.client.say(
        {
            "en": "Please, I really need to talk to a person.",
            "az": "please, 3an jad baddi ehke ma3 7ada.",
            "ar": "من فضلك، عن جد بدي إحكي مع حدا.",
        }
    )
    cases = s.escalations()
    s.check(
        "hands_over_once_the_tool_is_back",
        bool(again.called("escalate")) and len(cases) == 1,
        level="end_to_end",
        family="reliability",
        detail=f"tools {again.tool_names()}; cases {[(c['reason'], c['state']) for c in cases]}",
    )
    if not cases:
        return
    console = _admin(s).escalations()
    s.check(
        "the_team_sees_the_case",
        any(str(case["id"]) == cases[0]["id"] for case in console),
        level="component",
        family="reliability",
        detail=f"console: {[case.get('id') for case in console]}",
    )
    before = len(s.client.turns)
    _admin(s).reply(
        cases[0]["id"],
        {
            "en": "Hello, this is the DawaLink team. How can we help?",
            "az": "marhaba, ma3ak fari2 DawaLink. kif fina nsa3dak?",
            "ar": "مرحبا، معك فريق DawaLink. كيف فينا نساعدك؟",
        },
    )
    s.client.catch_up()
    s.check(
        "the_client_reads_the_team",
        any(turn.team_said for turn in s.client.turns[before:]),
        level="end_to_end",
        family="task_success",
        detail=f"after the reply: {[(t.team_said, t.reply[:60]) for t in s.client.turns[before:]]}",
    )


# --- the model's provider fails --------------------------------------------------------------


def _model_once(s: Stage) -> None:
    _alone(s, 7)
    loratin = s.medicine("loratin", "10mg")
    notice_is(s, not_needed=(loratin,))
    near, second = s.nearest(2)
    s.stock(loratin, near, days=90)
    s.stock(loratin, second, days=70)
    s.fault.model(calls=1)

    turn = s.client.say(_everything_now(("Loratin 10", "loratin 10", "لوراتين 10"), 3))
    if s.fault._model.fail_next:
        raise StageError("The model's fault was never met: no model call was made.")
    _ends_with_a_reply(s, turn, name="answers_despite_the_failure")
    expect.searched(s, [turn], loratin, days_of_use=3, pickup_day=s.today)
    shown = cards_of([turn], ("reserve",))
    s.check(
        "shows_what_it_found",
        bool(shown),
        level="end_to_end",
        family="reliability",
        detail=f"cards {turn.kinds}",
    )
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, loratin, lasts_days=3, pickup_day=s.today)


def _model_down(s: Stage) -> None:
    _alone(s, 8)
    brufen = s.medicine("brufen", "600mg")
    notice_is(s, needed=(brufen,))
    near = s.nearest(1)[0]
    s.stock(brufen, near, days=90)
    chat = s.client.open_chat()
    s.fault.model(calls=10)

    words = s.t(_everything_now(("Brufen 600", "brufen 600", "بروفين 600"), 5))
    # Sent by hand to read the stream itself: a fallback answers 200 with an `error` event.
    stream = s.client.api(
        "POST",
        f"/conversations/{chat}/messages",
        json={"text": words, "client_message_id": str(uuid.uuid4())},
    )
    s.note("client", words, conversation=chat)
    news = [turn for turn in s.client.catch_up() if turn.conversation == chat]
    s.fault.clear()
    s.check(
        "says_the_assistant_is_unavailable",
        "ASSISTANT_UNAVAILABLE" in stream.text,
        level="component",
        family="reliability",
        detail=f"status {stream.status_code}; stream {stream.text[-300:]!r}",
    )
    s.check(
        "no_half_written_reply",
        not any(turn.reply for turn in news) and not cards_of(news),
        level="step",
        family="reliability",
        detail=f"after the failure: {[(t.outcomes, t.reply[:80], t.kinds) for t in news]}",
    )
    stored = s.stored_messages(chat)
    s.check(
        "the_message_is_kept",
        any(m["author"] == "client" for m in stored),
        level="component",
        family="reliability",
        detail=f"stored: {[(m['author'], m['kind']) for m in stored]}",
    )
    expect.nothing_changed(s, name="nothing_half_done")
    again = s.client.say(
        {
            "en": "Hello? I still need Brufen 600 for 5 days, from the nearest pharmacy, today.",
            "az": "alo? lessa baddi brufen 600 la 5 iyyem, mn a2rab saydaliyye, lyom.",
            "ar": "ألو؟ بعدني بدي بروفين 600 لـ5 أيام، من أقرب صيدلية، اليوم.",
        }
    )
    expect.searched(s, [again], brufen, days_of_use=5, pickup_day=s.today)
    shown = cards_of([again], ("reserve",))
    s.check(
        "works_again_once_the_model_is_back",
        again.answered and bool(shown),
        level="end_to_end",
        family="reliability",
        detail=f"status {again.status} {again.error}; outcomes {again.outcomes}; "
        f"cards {again.kinds}",
    )
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, brufen, lasts_days=5)


# --- the routing service is down -------------------------------------------------------------


def _routing_down_plan(s: Stage) -> None:
    _alone(s, 9)
    brufen, concor = s.medicine("brufen", "400mg"), s.medicine("concor", "10mg")
    notice_is(s, needed=(concor,), not_needed=(brufen,))
    near = s.nearest(1)[0]
    s.stock(brufen, near, days=90)
    s.stock(concor, near, days=90)
    with s.setup() as session:  # no time is known yet: every one must be asked for
        session.execute(delete(TravelTimeCache))

    turn = s.client.say(
        {
            "en": "I need Brufen 400 and Concor 10, one box of each, for 10 days, from the "
            "nearest pharmacy. I can go today.",
            "az": "baddi brufen 400 w concor 10, 3elbe men kel wa7de, la 10 iyyem, mn a2rab "
            "saydaliyye. fiyye ruu7 lyom.",
            "ar": "بدي بروفين 400 وكونكور 10، علبة من كل وحدة، لـ10 أيام، من أقرب صيدلية. "
            "فيني روح اليوم.",
        }
    )
    planned = [tool for tool in turn.called("plan_basket") if tool.ok]
    if any('"source": "road"' in tool.answer for tool in planned):
        raise StageError("A plan has road times: the travel cache still answered.")
    asked = getattr(s.agent.routing, "calls", 0)
    s.check(
        "plans_without_the_routing_service",
        bool(planned),
        level="step",
        family="reliability",
        detail=f"tools {[(t.name, t.ok) for t in turn.tools]}; routing asked {asked} times",
    )
    s.check(
        "times_are_estimates",
        bool(planned) and all('"source": "straight"' in tool.answer for tool in planned),
        level="component",
        family="reliability",
        detail=f"plan answers: {[tool.answer[:200] for tool in planned]}",
    )
    plan = cards_of([turn], ("reserve_group",))
    s.check(
        "shows_the_plan_card",
        bool(plan),
        level="step",
        family="output_quality",
        detail=f"cards {turn.kinds}",
    )
    _ends_with_a_reply(s, turn)
    for card in plan[:1]:
        s.client.tap(card)
    s.check(
        "both_reserved",
        bool(reserved_of(s, brufen)) and bool(reserved_of(s, concor)),
        level="end_to_end",
        family="task_success",
        detail=str([(o["medicine"], o["state"]) for o in s.orders()]),
    )


# --- a tool fails in a request's thread (a worker turn) ---------------------------------------


def _request_planner_down(s: Stage) -> None:
    _alone(s, 6)
    cipromax, rennie = s.medicine("cipromax", "500mg"), s.medicine("rennie")
    notice_is(s, needed=(cipromax,), not_needed=(rennie,))
    p1 = open_pharmacies(s, 1)[0]

    def stock_arrives() -> None:
        s.pharmacy(p1).add_stock(cipromax, days=100, qty=2)
        s.pharmacy(p1).add_stock(rennie, days=100, qty=2)
        s.fault.tool("plan_basket", times=None)  # only from now: the chat already planned

    ref, tap = start_request(
        s,
        find_them(
            "Cipromax 500 and Rennie, one box of each",
            "cipromax 500 w rennie, 3elbe men kel wa7de",
            "سيبروماكس 500 وحبوب ريني، علبة من كل وحدة",
            7,
        ),
        before_tap=stock_arrives,
    )
    if ref is None or tap is None:
        s.fault.clear()
        return
    first = in_thread(s, ref, tap.turns)
    _fault_held(first, "plan_basket")
    s.check(
        "ends_honestly_or_tries_later",
        bool(worked(first))
        and all(o in ("ok", "fallback") for t in first for o in t.outcomes)
        and any(t.reply for t in first),
        level="step",
        family="reliability",
        detail=f"outcomes {[t.outcomes for t in first]}; replies {[t.reply[:80] for t in first]}",
    )
    request = request_of(s, ref)
    consistent = request["state"] == "OPEN" and all(
        item["qty_secured"] == 0 and item["state"] != "SECURED" for item in request["items"]
    )
    s.check(
        "the_request_stays_consistent",
        consistent and not s.orders(),
        level="end_to_end",
        family="reliability",
        detail=f"{request['state']}; items {items_say(s, ref)}; orders {orders_say(s)}",
    )
    s.fault.clear()
    # The agent may already have found a way round (find_options, one medicine at a time)
    # and shown real cards: then there is nothing to try again.
    shown = [c for c in cards_of(first) if c.state == "open"]
    seen = (
        f"first turn: tools {[t.tool_names() for t in first]}, "
        f"cards {[c.kind for c in cards_of(first)]}"
    )
    if not shown:
        again = s.client.say(_TRY_AGAIN, in_request=ref)
        shown = cards_of([again])
        seen += f"; after 'try again': tools {again.tool_names()}, cards {again.kinds}"
    s.check(
        "reaches_a_card_to_reserve",
        bool(shown),
        level="end_to_end",
        family="reliability",
        detail=seen,
    )
    for card in shown[:1]:
        s.client.tap(card)
    s.check(
        "the_client_can_reserve_again",
        bool(reserved_of(s, cipromax) or reserved_of(s, rennie)),
        level="end_to_end",
        family="task_success",
        detail=str([(o["medicine"], o["state"]) for o in s.orders()]),
    )


def _request_turn_lost(s: Stage) -> None:
    own_client(s, 44)
    zyrtec, duphalac = s.medicine("zyrtec", "10mg"), s.medicine("duphalac")
    notice_is(s, needed=(zyrtec,), not_needed=(duphalac,))
    p1 = open_pharmacies(s, 1)[0]

    def stock_arrives() -> None:
        s.pharmacy(p1).add_stock(zyrtec, days=100, qty=2)
        s.pharmacy(p1).add_stock(duphalac, days=100, qty=2)
        s.fault.model(calls=10)  # only from now: the chat already answered

    ref, tap = start_request(
        s,
        find_them(
            "Zyrtec 10 and Duphalac, one box of each",
            "zyrtec 10 w duphalac, 3elbe men kel wa7de",
            "زيرتك 10 ودوفالاك، علبة من كل وحدة",
            10,
        ),
        before_tap=stock_arrives,
    )
    met = s.fault._model.failed
    s.fault.clear()  # after the thread's first turn, which the tap ran
    if ref is None or tap is None:
        return
    if not met:
        raise StageError("The model's fault was never met: the thread's turn made no call.")
    first = in_thread(s, ref, tap.turns)
    request = request_of(s, ref)
    s.check(
        "nothing_half_done_while_down",
        not cards_of(first)
        and not s.orders()
        and request["state"] == "OPEN"
        and all(item["state"] != "UNAVAILABLE" for item in request["items"]),
        level="end_to_end",
        family="reliability",
        detail=f"{request['state']}; items {items_say(s, ref)}; orders {orders_say(s)}; "
        f"replies {[t.reply[:80] for t in first]}",
    )
    # SM-12: a worker turn that failed is tried again after 1 minute.
    retried = in_thread(s, ref, s.advance(minutes=2))
    s.check(
        "tries_again_a_minute_later",
        bool(worked(retried)) and all(o == "ok" for t in retried for o in t.outcomes),
        level="trajectory",
        family="reliability",
        detail=f"after 2 minutes: {[(t.agent_turns, t.outcomes) for t in retried]}",
    )
    shown = cards_of(retried)
    s.check(
        "plans_on_the_retry",
        bool(shown),
        level="end_to_end",
        family="reliability",
        detail=f"cards {[c.says() for c in shown]}; tools {[t.tool_names() for t in retried]}",
    )
    for card in shown[:1]:
        s.client.tap(card)
    s.check(
        "both_reserved_in_the_end",
        bool(reserved_of(s, zyrtec)) and bool(reserved_of(s, duphalac)),
        level="end_to_end",
        family="task_success",
        detail=orders_say(s),
    )


_SCENARIOS = [
    Scenario(
        id="fail.find_once",
        kind="tool_failure",
        title="The search tool crashes once; the client said everything",
        expected=(
            "The client said everything, so the agent searches at once. The search fails "
            "once. The agent tries again, or says plainly that it couldn't search and will "
            "try again; it never invents a pharmacy, a price or an expiry date. In the end "
            "the client sees real options (reserve cards, one recommended with a reason, "
            "no prescription notice for this medicine) and reserves with their own tap."
        ),
        play=_find_once,
        prescription="not_needed",
        rules=("docs/07 §8", "R-AG7", "R-AG9", "FA-40"),
        facts=(
            "You need Brufen 400 mg, one box, for 5 days, from the nearest pharmacy, today.",
            "If the assistant says something went wrong, ask it to try again.",
        ),
    ),
    Scenario(
        id="fail.search_down",
        kind="tool_failure",
        title="Every search fails; then the tools come back",
        expected=(
            "Both search tools fail on every call. The agent shows no card, names no "
            "pharmacy, price or expiry date (no tool gave any), reserves and starts "
            "nothing, and doesn't pretend the medicine is unavailable: it says honestly "
            "that it couldn't search right now and that the Search page still works, or "
            "that it will try again. It doesn't loop on the failing tool. When the client "
            "asks again and the tools work, it searches with what the client said (7 days) "
            "and shows a reserve card with the prescription notice; the tap reserves it."
        ),
        play=_search_down,
        prescription="needed",
        rules=("docs/07 §8", "R-AG7", "R-AG10", "R-RQ4", "AF-19", "C15"),
    ),
    Scenario(
        id="fail.card_tool_down",
        kind="tool_failure",
        title="The search works but no reservation card can be made",
        expected=(
            "The search finds the medicine, but making the card fails every time. The "
            "reply never points to a card that isn't there ('the card below', 'tap "
            "Reserve'); it may say what was found and that the reservation card couldn't "
            "be made right now, and it offers to try again or points to the Search page. "
            "It starts no watch and no ask for a medicine that is listed. Once the tool "
            "works and the client asks again, it shows the reserve card and the tap "
            "reserves a box that lasts the 30 days."
        ),
        play=_card_tool_down,
        prescription="needed",
        rules=("FA-39", "FA-40", "R-AG7", "R-AG10", "R-RQ4"),
        facts=(
            "You need Crestor 20 mg, one box, for 30 days, from the nearest pharmacy, today.",
            "You want to reserve it.",
        ),
    ),
    Scenario(
        id="fail.watch_down",
        kind="tool_failure",
        title="A medicine listed nowhere, and the watch can't be started",
        expected=(
            "The medicine is listed nowhere, so the agent tries to start a watch on its "
            "own. The watch fails. The reply never claims that DawaLink is watching or "
            "that pharmacies were asked (R-AG10): it says that it couldn't start the watch "
            "right now and what the client can do. When the client asks it to try again "
            "and the tool works, it starts one watch and asks the open pharmacy that holds "
            "the medicine privately, then says so from the tools' results."
        ),
        play=_watch_down,
        prescription="needed",
        rules=("R-AG10", "R-RQ4", "R-W1", "R-E2", "BLD-D55"),
    ),
    Scenario(
        id="fail.ask_down",
        kind="tool_failure",
        title="The watch starts, but asking the pharmacies fails",
        expected=(
            "The medicine is listed nowhere. The agent starts the watch and tries to ask "
            "pharmacies; the ask fails. The reply says the watch is on (until when) and "
            "never claims that pharmacies were asked (R-AG10). When the client asks 'did "
            "you ask the pharmacies?' and the tool works, the agent answers honestly that "
            "the ask had failed, and asks them (best at once, as asking is its own act for "
            "a medicine listed nowhere, R-RQ4; or once the client says yes), using the "
            "watch it already started (never a second one), and answers from what the "
            "tool returned."
        ),
        play=_ask_down,
        prescription="not_needed",
        rules=("R-AG10", "R-RQ4", "R-W1", "R-E1", "BLD-D55", "BLD-D56"),
        facts=(
            "You need Finallerg 10 mg, one box, for 10 days, from the nearest pharmacy, today.",
            "If the assistant offers to ask the pharmacies again, say yes.",
        ),
    ),
    Scenario(
        id="fail.escalate_down",
        kind="tool_failure",
        title="The client asks for a person, and the hand-over fails",
        expected=(
            "The client asks for a person. The agent tries to hand over; the tool fails. "
            "The reply never says that a person was told or will reply (R-AG10): it says "
            "it couldn't reach the team right now. When the client asks again and the tool "
            "works, the agent hands over once and says a person was told and will reply in "
            "this chat. The admin sees the case in the console and replies, and the client "
            "reads the team's words in the chat."
        ),
        play=_escalate_down,
        prescription="none",
        rules=("R-AG10", "SM-9", "AF-21", "BLD-D52"),
    ),
    Scenario(
        id="fail.model_once",
        kind="tool_failure",
        title="The model's provider fails one call",
        expected=(
            "One call to the model fails and is retried (two retries with back-off). The "
            "client notices nothing: the agent searches at once with what the client said "
            "(3 days, today), shows reserve cards with one recommended, and the tap reserves "
            "it."
        ),
        play=_model_once,
        prescription="not_needed",
        rules=("docs/07 §8", "N-35", "N-36", "FX-1", "FX-3"),
    ),
    Scenario(
        id="fail.model_down",
        kind="tool_failure",
        title="The model's provider is down for a whole turn, then comes back",
        expected=(
            "The provider fails every call of the turn. The client gets no half-written "
            "reply and no card: the API answers that the assistant is unavailable (the "
            "website then shows 'Use Search'), the client's message is kept, and nothing "
            "was reserved or started. When the provider is back and the client writes "
            "again, the agent answers normally: it searches with what the client said and "
            "shows a reserve card with the prescription notice, which the tap reserves."
        ),
        play=_model_down,
        prescription="needed",
        rules=("FX-1", "docs/07 §8", "AF-19", "C15", "G9"),
    ),
    Scenario(
        id="fail.routing_down_plan",
        kind="tool_failure",
        title="Two medicines with the routing service down: the plan comes with estimates",
        expected=(
            "The client said everything for two medicines. The routing service doesn't "
            "answer, so travel times are straight-line estimates. The agent still plans "
            "both at once and shows the plan card; when it gives a travel time it says it "
            "is about (an estimate), never an exact road time. The tap reserves both."
        ),
        play=_routing_down_plan,
        prescription="both",
        rules=("FX-18", "R-RT1", "R-RQ5", "R-AG9"),
        routing="down",
    ),
    Scenario(
        id="fail.request_planner_down",
        kind="tool_failure",
        title="The planner fails in a request's thread (a worker turn)",
        expected=(
            "The request starts from the chat's [Start sourcing] card. In its thread the "
            "planner fails. The agent either finds another way with the tools that work "
            "(one medicine at a time) and shows real cards, or says plainly that it couldn't "
            "plan right now and will keep working; it never invents options, and nothing "
            "is reserved, secured or given up. The request stays open and consistent. When "
            "the client asks it to try again and the planner works, it plans and shows a "
            "card the client can reserve from."
        ),
        play=_request_planner_down,
        prescription="both",
        rules=("docs/07 §8", "SM-12", "R-RQ4", "R-RQ9", "INV-18"),
    ),
    Scenario(
        id="fail.request_turn_lost",
        kind="tool_failure",
        title="The model is down for a request's first worker turn; the turn is tried again",
        expected=(
            "The request starts from the chat's [Start sourcing] card. The model's provider "
            "fails every call of the thread's first turn (a worker turn). Nothing is half "
            "done: no half-written reply and no card in the thread, nothing reserved, the "
            "request stays open with its items still searched for. A minute later the "
            "worker tries the turn again; the provider is back, and the agent plans at once, "
            "asking nothing, with one card for the pharmacy that has both medicines. The "
            "client's tap reserves both."
        ),
        play=_request_turn_lost,
        prescription="both",
        rules=("SM-12", "RF-8", "FX-1", "docs/07 §8", "R-RQ9", "RF-1"),
    ),
]

# Which medicines carry the prescription notice (R-P1, R-C7), for the judge: a reply that
# says an OTC medicine needs a prescription is wrong, and only the expectation can say so.
_NOTICE = {
    "fail.find_once": (
        "Brufen 400 carries no prescription notice, and no reply may say it needs one."
    ),
    "fail.search_down": ("Augmentin carries the prescription notice."),
    "fail.card_tool_down": ("Crestor carries the prescription notice."),
    "fail.watch_down": ("Amaryl carries the prescription notice."),
    "fail.ask_down": (
        "Finallerg carries no prescription notice, and no reply may say it needs one."
    ),
    "fail.escalate_down": ("No medicine is involved."),
    "fail.model_once": (
        "Loratin carries no prescription notice, and no reply may say it needs one."
    ),
    "fail.model_down": ("Brufen 600 carries the prescription notice."),
    "fail.routing_down_plan": ("Concor carries the prescription notice; Brufen 400 does not."),
    "fail.request_planner_down": ("Cipromax carries the prescription notice; Rennie does not."),
    "fail.request_turn_lost": ("Zyrtec carries the prescription notice; Duphalac does not."),
}
SCENARIOS = [replace(one, expected=f"{one.expected} {_NOTICE[one.id]}") for one in _SCENARIOS]
