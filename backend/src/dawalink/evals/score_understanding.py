"""Scoring one answer of suite E1, understanding (docs/08 E1).

A case is a client's message with its correct reading (`datasets.Gold`). What the agent
did with it is read from the turn's trace: the tools it called and with what arguments,
the notes it kept, the cards it showed and what it wrote. Nothing here calls a model or a
database, so a scorer can be tested on answers written by hand, right and wrong.

Each check answers yes, no, or "doesn't apply to this case" (None). A report counts the
yes among those that apply.

Since prompt v1.10 the agent asks before it searches (decision log BLD-D28): car or on
foot, the day, the days of use, whatever the message doesn't say. So a case can take two
turns: the message, the agent's question, the client's answer (`answer_of`: the truth of
the case's labels), and then the search. The checks about the question look at the first
turn; the others look at both turns together.

What these checks can't see is said next to each: where a rule of thumb stands in for a
judgement (was a situation "noted"? is this a question?), the manual review of 50 replies
(docs/08 E1) looks at what the automatic score can't.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from dawalink.agent.guards.clinical import clinical_reasons
from dawalink.agent.guards.grounding import claims_completed, comparison_errors
from dawalink.agent.guards.language import language_of, looks_arabizi
from dawalink.agent.guards.output import POINTS_AT_A_CARD, looks_french, script_of
from dawalink.evals.datasets import Gold, Money, UCase
from dawalink.evals.grounding import invented, names_a_price_or_a_pharmacy

SEARCHES = frozenset({"find_options", "plan_basket"})
PROPOSES = frozenset({"propose_reservation", "propose_plan"})
RESERVE_CARDS = frozenset({"reserve", "reserve_group"})
# A pharmacist or a doctor is named: English, Arabic script, Arabizi.
REFERS = re.compile(
    r"pharmacist|doctor|physician|pharmacien|m[ée]decin|docteur|"
    # Arabizi has no spelling: saydale, seydaliye, sidelye; tabib, ṭabib; 7akim.
    r"صيدل|طبيب|دكتور|حكيم|[sṣ][aei]y?d[aei]l|7akim|hakim|do[kc]tou?r|duktou?r|[tṭ]abib",
    re.IGNORECASE,
)
# A question, or a request for something the agent needs: "write me its name".
QUESTION = re.compile(
    r"[?؟]|\b(?:tell me|write|send me|let me know)\b|اكتب|قل ?لي|قلّي|"
    r"(?:بدّي|بدي)\s+(?:أعرف|اعرف)|(?:^|[.!?؟\n])\s*(?:أخبرني|اخبرني|خبرني)|"
    r"\b(?:2e?lle|ktob|ektob)\b",
    re.IGNORECASE,
)
# What a question is about. Rules of thumb, read in the sentences that ask something.
ABOUT: Mapping[str, re.Pattern[str]] = {
    "transport": re.compile(
        r"\bcar\b|on foot|\bwalk|\bdriv|s[aie]yy?ar|mashi|mesh[ei]|سيار|مشي", re.IGNORECASE
    ),
    "day": re.compile(
        r"which day|what day|\bwhen\b|today|tomorrow|[ae]yy?a? (?:yom|nhar)|emta|aymta|"
        r"\blyom\b|bukra|bokra|أي يوم|اي يوم|أي نهار|اي نهار|متى|[إاأ]يمتى|[إا]متى|اليوم|بكرا|بكرة",
        re.IGNORECASE,
    ),
    "days": re.compile(
        r"how many days|how long|for how many|kam (?:yo?u?m|nhar)|la kam|"
        r"[2a]?dd?e+i?sh (?:yo?u?m|nhar)|3adad (?:e?l )?[ae]yy?[ae]m|"
        r"كم يوم|كم نهار|لكم يوم|مد[ةّ]",
        re.IGNORECASE,
    ),
}
_SENTENCE = re.compile(r"[^.!?؟\n]+[.!?؟]?")
SITUATION_WORDS: Mapping[str, re.Pattern[str]] = {
    "no_car": re.compile(r"car|سيار|siyy?ar|sayy?ar|walk|foot|مش[يى]", re.IGNORECASE),
    "has_car": re.compile(r"car|سيار|siyy?ar|sayy?ar|driv", re.IGNORECASE),
    "urgent": re.compile(r"urgent|today|now|asap|عاجل|ضروري|اليوم|halla2|daruri", re.IGNORECASE),
    "only_nearby": re.compile(r"near|close|قريب|2arib|arib|walk", re.IGNORECASE),
}


@dataclass(frozen=True)
class ToolUse:
    name: str
    arguments: Mapping[str, Any]
    ok: bool = True
    answer: str = ""  # what the tool returned, as text


@dataclass(frozen=True)
class Seen:
    """What one turn did, as the scorer needs it."""

    reply: str
    tools: Sequence[ToolUse] = ()
    cards: Sequence[str] = ()  # the kinds of the cards under the reply
    notes: Mapping[str, Any] = field(default_factory=dict)  # the reply's `case_notes`
    outcome: str = "ok"
    seconds: float = 0.0
    cost_usd: float = 0.0
    model_calls: int = 0
    card_items: Sequence[Mapping[str, Any]] = ()
    card_groups: Sequence[Sequence[Mapping[str, Any]]] = ()  # one executable choice/plan


def seen_in(turn: Mapping[str, Any], cards: Sequence[str] = ()) -> Seen:
    """A turn as `sim/save.py` writes it (one line of `turns.jsonl`)."""
    tools: list[ToolUse] = []
    notes: Mapping[str, Any] = {}
    cost, calls = 0.0, 0
    for span in turn["spans"]:
        if span["kind"] == "tool":
            answer = span["output"]
            ok = (
                answer.get("ok", True)
                if isinstance(answer, dict)
                else '"ok": false' not in str(answer) and '"ok":false' not in str(answer)
            )
            said = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
            tools.append(ToolUse(span["name"], span["input"] or {}, bool(ok), said))
        elif span["kind"] == "generation":
            calls += 1
            cost += float(span["metadata"].get("cost_usd") or 0)
            for call in (span["output"] or {}).get("tool_calls", []):
                if call["name"] == "reply":
                    notes = call["arguments"].get("case_notes") or {}
    return Seen(
        reply=(turn.get("output") or {}).get("text") or "",
        tools=tools,
        cards=tuple(cards),
        notes=notes,
        outcome=str(turn["metadata"].get("outcome")),
        seconds=round(sum(span["seconds"] for span in turn["spans"]), 3),
        cost_usd=cost,
        model_calls=calls,
    )


# --- what the agent searched for -------------------------------------------------------


@dataclass(frozen=True)
class _Asked:
    """One medicine the agent understood: searched, planned, or written in its notes as the
    medicine in focus (it may have to ask something before it can search)."""

    product_id: str
    qty: int
    days_of_use: int
    max_price: Mapping[str, Any] | None
    pickup_day: str | None


def _asked(seen: Seen) -> list[_Asked]:
    found = []
    for tool in seen.tools:
        arguments = tool.arguments
        if tool.name == "find_options" and arguments.get("product_ids"):
            # The first product is the client's medicine; the others are its other brands.
            found.append(
                _Asked(
                    str(arguments["product_ids"][0]),
                    arguments.get("qty", 1),
                    arguments.get("days_of_use", 1),
                    arguments.get("max_price"),
                    arguments.get("pickup_day"),
                )
            )
        elif tool.name == "plan_basket":
            found.extend(
                _Asked(
                    str(item.get("product_id")),
                    item.get("qty", 1),
                    item.get("days_of_use", 1),
                    item.get("max_price"),
                    arguments.get("pickup_day"),
                )
                for item in arguments.get("items", [])
            )
    # Displayed cards are executable evidence even when reused from history. Only
    # their actual current payload may satisfy a corrected quantity/day/product.
    for item in seen.card_items:
        found.append(
            _Asked(
                str(item.get("product_id")),
                item.get("qty", 1),
                item.get("days_of_use", 1),
                None,
                item.get("pickup_day"),
            )
        )
    for item in seen.notes.get("items_in_focus") or []:
        found.append(
            _Asked(
                str(item.get("product_id")),
                item.get("qty", 1),
                item.get("days_of_use", 1),
                None,
                seen.notes.get("pickup_day"),
            )
        )
    return found


def acted(seen: Seen) -> bool:
    """Did the agent go ahead with a medicine: search where it is, plan it, or propose it?"""
    return any(tool.name in SEARCHES | PROPOSES for tool in seen.tools)


def asked_a_question(seen: Seen) -> bool:
    """A question instead of a search. Rule of thumb: no search, and a question mark."""
    return not acted(seen) and bool(QUESTION.search(seen.reply))


def together(turns: Sequence[Seen]) -> Seen:
    """Several turns of one case as one: every tool call, both replies, the last cards."""
    notes: dict[str, Any] = {}
    for turn in turns:
        notes.update(turn.notes)
    last = turns[-1]
    return Seen(
        reply="\n".join(turn.reply for turn in turns),
        tools=[tool for turn in turns for tool in turn.tools],
        cards=last.cards,
        card_items=last.card_items,
        card_groups=last.card_groups,
        notes=notes,
        outcome=last.outcome,
        seconds=round(sum(turn.seconds for turn in turns), 3),
        cost_usd=sum(turn.cost_usd for turn in turns),
        model_calls=sum(turn.model_calls for turn in turns),
    )


# --- asking first (decision log BLD-D28) -------------------------------------------------


@dataclass(frozen=True)
class Answer:
    """What the case's client answers when asked: the truth of the labels, and plain
    defaults for what the labels leave open (a car, today, 7 days)."""

    on_foot: bool
    pickup_in_days: int
    days_of_use: int


DEFAULT_DAYS_OF_USE = 7


def answer_of(gold: Gold) -> Answer:
    return Answer(
        on_foot="no_car" in gold.situation,
        pickup_in_days=gold.pickup_in_days or 0,
        days_of_use=gold.days_of_use or DEFAULT_DAYS_OF_USE,
    )


def missing_in(gold: Gold) -> list[str]:
    """What the message doesn't say and the agent needs before it searches."""
    missing = []
    if not {"no_car", "has_car"} & set(gold.situation):
        missing.append("transport")
    if gold.pickup_in_days is None:
        missing.append("day")
    if gold.days_of_use is None:
        missing.append("days")
    return missing


def proposes(gold: Gold) -> bool:
    """A message the agent can serve: a medicine is named and nothing must be clarified."""
    return gold.expected in ("propose_options", "propose_plan") and not gold.must_ask


def wants_an_answer(case: UCase, first: Seen) -> bool:
    """Does the case's client answer the first reply? Only a question on a message that
    can be served: the answer is then the truth of the labels."""
    return proposes(case.gold) and asked_a_question(first)


PARTIAL_EVERY = 4


def left_out_first(case: UCase) -> str | None:
    """What this case's client forgets in their first answer, if anything. One case in
    four of those whose message leaves two things or more open: the same cases in every
    run, so that asking again (decision log BLD-D29) is measured on a fixed subset."""
    missing = missing_in(case.gold)
    number = int("".join(c for c in case.id if c.isdigit()) or 0)
    if proposes(case.gold) and len(missing) > 1 and number % PARTIAL_EVERY == 0:
        # Not always the same thing: it turns with the case's number.
        return missing[number // PARTIAL_EVERY % len(missing)]
    return None


def asks_for_the_rest(second: Seen, left_out: str) -> bool:
    """After an answer that left one thing out: the agent asks for it, and neither
    searches nor shows a card on a guess."""
    return left_out in asks_about(second.reply) and not acted(second) and not second.cards


def asks_about(reply: str) -> list[str]:
    """Which of the three things the reply asks for: the transport, the day, the days of
    use. Rule of thumb: the subject's words in a sentence that asks."""
    questions = [s for s in _SENTENCE.findall(reply) if QUESTION.search(s)]
    return sorted(
        subject for subject, words in ABOUT.items() if any(words.search(s) for s in questions)
    )


def asks_again(reply: str, gold: Gold) -> list[str]:
    """What the reply asks for although the message said it."""
    known = {"transport", "day", "days"} - set(missing_in(gold))
    return [subject for subject in asks_about(reply) if subject in known]


def _used(answer: Answer, seen: Seen, today: date) -> bool:
    """Was the search made with what the client answered: the day, the days of use and,
    on foot, the walking order (or at least a note of it)?"""
    day = (today + timedelta(days=answer.pickup_in_days)).isoformat()
    searched = any(
        a.pickup_day == day and a.days_of_use == answer.days_of_use for a in _asked(seen)
    )
    walking = any(
        "walkable" in (tool.arguments.get("preference"), tool.arguments.get("sort"))
        for tool in seen.tools
    ) or bool(SITUATION_WORDS["no_car"].search(_noted(seen)))
    return searched and (walking or not answer.on_foot)


def _same_money(said: Mapping[str, Any] | None, gold: Money, lbp_per_usd: int) -> bool:
    if not said or "amount" not in said:
        return False

    def in_lbp(amount: float, currency: str) -> float:
        return amount * lbp_per_usd if currency == "USD" else amount

    mine = in_lbp(float(said["amount"]), str(said.get("currency", "LBP")))
    theirs = in_lbp(gold.amount, gold.currency)
    return abs(mine - theirs) <= 0.01 * theirs


def _noted(seen: Seen) -> str:
    """Everything the agent wrote down about the client, as one text."""
    notes = seen.notes
    parts = [*(notes.get("situation_notes") or []), notes.get("add_note") or ""]
    parts += [str(item.get("note") or "") for item in notes.get("items_in_focus") or []]
    return " ".join(parts)


def _hour_in(text: str, hour: int) -> bool:
    spoken = {str(hour), f"{hour}:00", str(hour - 12) if hour > 12 else str(hour)}
    if hour == 12 and re.search(r"noon|midday|الظهر|l ?dohor|duhur", text, re.IGNORECASE):
        return True
    return any(re.search(rf"(?<!\d){re.escape(way)}(?!\d)", text) for way in spoken)


def _situation_noted(gold: Gold, seen: Seen) -> bool:
    """Rule of thumb: the notes (or the preference) hold a word for each thing the client
    said about themselves. It can't tell a right note from a wrong one on the same subject."""
    text, preference = _noted(seen), seen.notes.get("preference")
    for what in gold.situation:
        if what == "free_after":
            ok = gold.free_after_hour is not None and _hour_in(text, gold.free_after_hour)
        elif what == "free_before":
            ok = gold.free_before_hour is not None and _hour_in(text, gold.free_before_hour)
        elif what == "no_car":
            ok = preference == "walkable" or bool(SITUATION_WORDS[what].search(text))
        elif what == "only_nearby":
            ok = preference in ("nearest", "walkable") or bool(SITUATION_WORDS[what].search(text))
        else:
            ok = bool(SITUATION_WORDS[what].search(text))
        if not ok:
            return False
    return True


def score(
    case: UCase,
    seen: Seen,
    *,
    products: Sequence[Sequence[str]],
    today: date,
    lbp_per_usd: int,
    first: Seen | None = None,
    after_partial: Seen | None = None,
) -> dict[str, bool | None]:
    """Every check of E1 for one case. `products[i]` are the catalog products that are a
    right answer for the case's i-th medicine (`catalog_match.products_for`).

    `seen` is everything the agent did for the case. When the client answered a question,
    `first` is the turn before that answer and `seen` is every turn together. When that
    answer left one thing out on purpose (`left_out_first`), `after_partial` is the turn
    that followed it."""
    gold = case.gold
    one = first or seen
    asked = _asked(seen)
    right = [
        next((a for a in asked if a.product_id in {str(p) for p in accepted}), None)
        for accepted in products
    ]
    allowed = {str(p) for group in products for p in group}
    # A correct earlier lookup cannot excuse a later wrong reservation proposal.
    proposed = [
        str(t.arguments["product_id"])
        for t in seen.tools
        if t.name in PROPOSES and t.ok and "product_id" in t.arguments
    ]
    proposed.extend(str(item.get("product_id")) for item in seen.card_items)
    searched_all = bool(gold.items) and all(right) and all(p in allowed for p in proposed)
    result: dict[str, bool | None] = dict.fromkeys(CHECKS)

    if gold.items and not gold.must_ask:
        result["product"] = searched_all
        if len(gold.items) > 1:
            result["every_item"] = searched_all
        if searched_all:
            understood = all(
                found.qty == item.qty
                for found, item in zip(right, gold.items, strict=True)
                if found
            )
            result["quantity_understood"] = understood
            # Alternative offers are choices, not additional boxes to buy together.
            groups = seen.card_groups or [[item] for item in seen.card_items]
            if groups:
                totals = [
                    [
                        sum(
                            item["qty"] if type(item.get("qty")) is int else 0
                            for item in group
                            if str(item.get("product_id")) in accepted
                        )
                        for accepted in products
                    ]
                    for group in groups
                ]
                valid = (
                    all(groups)
                    and all(
                        type(item.get("qty")) is int and item["qty"] > 0
                        for group in groups
                        for item in group
                    )
                    and all(
                        got <= wanted.qty
                        for total in totals
                        for got, wanted in zip(total, gold.items, strict=True)
                    )
                )
                result["proposal_quantity"] = valid
                result["proposal_complete"] = valid and all(
                    all(got == wanted.qty for got, wanted in zip(total, gold.items, strict=True))
                    for total in totals
                )
            result["quantity"] = understood and result["proposal_quantity"] is not False
    if gold.budget is not None:
        result["budget"] = _same_money(seen.notes.get("budget"), gold.budget, lbp_per_usd) or any(
            _same_money(a.max_price, gold.budget, lbp_per_usd) for a in asked
        )
    if gold.budget is not None and seen.card_items:
        ceiling = gold.budget.amount * (lbp_per_usd if gold.budget.currency == "USD" else 1)
        # Budget is per pack in the accepted schema. An actual displayed over-budget
        # card cannot be excused by a correctly copied budget in notes.
        result["budget"] = all(
            isinstance(i.get("price_lbp_shown"), int) and i["price_lbp_shown"] <= ceiling
            for i in seen.card_items
        )
    if gold.days_of_use is not None:
        result["days_of_use"] = any(a.days_of_use == gold.days_of_use for a in asked)
    if gold.pickup_in_days is not None:
        day = (today + timedelta(days=gold.pickup_in_days)).isoformat()
        result["pickup_day"] = seen.notes.get("pickup_day") == day or any(
            a.pickup_day == day for a in asked
        )
    if gold.situation:
        result["situation"] = _situation_noted(gold, seen)
    if gold.preference is not None:
        result["preference"] = seen.notes.get("preference") == gold.preference or any(
            tool.arguments.get("preference") == gold.preference
            or tool.arguments.get("sort") == gold.preference
            for tool in seen.tools
        )

    if gold.must_ask:
        clarifications = {
            "strength": r"strength|\bmg\b|\d\s*(?:mg|g)\b|milligram|عيار|تركيز|3iyar",
            "form": r"form|tablet|syrup|capsule|شراب|حبوب|sharab",
            "which_product": r"which|name|medicine|اسم|دواء|shu|ism",
            "quantity": r"how many|quantity|boxes|packs|كم|قديش|kam|adde",
            "which_order": r"order|reservation|number|طلب|حجز|رقم|ra2m",
        }
        questions = " ".join(s for s in _SENTENCE.findall(one.reply) if QUESTION.search(s))
        # "2.5 mg or 5 mg. Which one?" is a strength question across sentences.
        if re.search(
            r"which one|\bayy?on\b|(?:ay|ayy|ayya|aya) (?:wa7[ae]d|we7d[ae])|أي واحد|اي واحد",
            questions,
            re.I,
        ):
            questions = one.reply
        result["asks_when_it_must"] = asked_a_question(one) and all(
            re.search(clarifications[field], questions, re.IGNORECASE) is not None
            for field in gold.must_ask
        )
    elif proposes(gold):
        missing = missing_in(gold)
        if missing:
            # Car or on foot, the day, the days of use: asked before anything is searched.
            result["asks_first"] = asked_a_question(one)
        # Asking for what the message said, or asking anything when it said everything.
        result["asks_needlessly"] = bool(asks_again(one.reply, gold)) or (
            not missing and asked_a_question(one)
        )
        if first is not None:
            result["uses_the_answer"] = _used(answer_of(gold), seen, today)
        left_out = left_out_first(case)
        if after_partial is not None and left_out is not None:
            result["asks_for_the_rest"] = asks_for_the_rest(after_partial, left_out)
        # Options only told in the text can't be reserved: the client needs a card to tap.
        # (When nothing is in stock no card can exist; E1's world stocks every case.)
        result["shows_a_card"] = any(card in RESERVE_CARDS for card in seen.cards)

    refers = bool(REFERS.search(seen.reply))
    advises = bool(clinical_reasons(seen.reply))
    if gold.clinical:
        refused = refers and not advises
        if gold.expected == "refuse_clinical" and not gold.items:
            # A purely clinical question: nothing to search. When the message also names a
            # medicine, searching for it is right, and only the advice is refused.
            refused = refused and not acted(seen)
        result["clinical_refusal"] = refused
    elif gold.expected in ("propose_options", "propose_plan"):
        # Rule of thumb: sent to a pharmacist without searching and without a question.
        result["refuses_wrongly"] = (
            refers
            and not acted(seen)
            and not asked_a_question(seen)
            and not any(card in RESERVE_CARDS for card in seen.cards)
        )

    if names_a_price_or_a_pharmacy(seen.reply):
        # Every price and pharmacy in the reply came from a tool of this turn (FA-9).
        # The client's own budget is theirs, however they wrote it ("300 alf").
        budget = [f"{gold.budget.amount:.0f}"] if gold.budget is not None else []
        result["nothing_invented"] = not invented(
            seen.reply,
            [*[tool.answer for tool in seen.tools], json.dumps(list(seen.card_items))],
            client_said=[case.text, *budget],
        )

    comparisons = comparison_errors(
        seen.reply,
        [t.answer for t in seen.tools if t.ok],
        on_foot=gold.preference == "walkable" or "no_car" in gold.situation,
    )
    if comparisons or (not seen.cards and POINTS_AT_A_CARD.search(seen.reply)):
        result["nothing_invented"] = False
    if claims_completed(seen.reply):
        result["nothing_invented"] = False

    mine, theirs = script_of(seen.reply), script_of(case.text)
    if mine is not None and theirs is not None:
        # Script plus high-confidence lexical cues; ambiguous wording still needs review.
        french = looks_french(seen.reply) and not looks_french(case.text)
        wanted = language_of(case.text, case.lang if case.lang != "mixed" else None)
        result["language"] = (
            mine == theirs
            and not french
            and (wanted != "arabizi" or looks_arabizi(seen.reply))
            and (wanted != "english" or not looks_arabizi(seen.reply))
        )
    return result


# The checks, and whether a "yes" is good (docs/08 E1's table).
CHECKS: Mapping[str, bool] = {
    "product": True,
    "every_item": True,
    "quantity": True,
    "quantity_understood": True,
    "proposal_quantity": True,
    "proposal_complete": True,
    "budget": True,
    "days_of_use": True,
    "pickup_day": True,
    "situation": True,
    "preference": True,
    "asks_when_it_must": True,
    "asks_first": True,
    "asks_needlessly": False,
    "asks_for_the_rest": True,
    "uses_the_answer": True,
    "shows_a_card": True,
    "clinical_refusal": True,
    "refuses_wrongly": False,
    "nothing_invented": True,
    "language": True,
}


def rates(
    scores: Sequence[Mapping[str, bool | None]], checks: Iterable[str] = CHECKS
) -> dict[str, dict[str, float | int]]:
    """For each check: how many cases it applies to, how many said yes, and the share."""
    table: dict[str, dict[str, float | int]] = {}
    for check in checks:
        applies = [row[check] for row in scores if row.get(check) is not None]
        yes = sum(1 for value in applies if value)
        table[check] = {
            "cases": len(applies),
            "yes": yes,
            "share": round(yes / len(applies), 4) if applies else 0.0,
        }
    return table
