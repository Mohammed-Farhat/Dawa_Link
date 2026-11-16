"""B1, the policy with no AI (docs/08 E2): the agent's own tools, driven by fixed rules.

For the agent's runtime this is a model like any other: it is given the same prompt, it
answers with tool calls, and its turns go through the same limits, guards and records
(`agent/turn.py`). So the comparison with the agent is about one thing only: what decides
the next tool call. Here it is a list of rules; in the agent it is a language model.

Everything it knows, it reads from the prompt: the request's facts, what the client wrote
and this turn's tool results. It keeps nothing between two calls.

The rules, in order:
1. the client asks to reserve a brand they were shown: look that brand up, make its card;
2. one hour is left (the window check), or the client just agreed to hear about other
   brands: show another brand for the first two medicines still missing. If the client
   never agreed, ask them first (one card);
3. otherwise: plan the medicines being searched, show the plan with the shortest drive
   (then the lowest price), start waiting for what no plan covers, and ask pharmacies to
   release private stock for every medicine that waits. When the client just wrote
   something, the medicines whose card they haven't tapped are planned again too.

What the client writes is read with keywords only ("cheap", "rkhis", "ma 3ande siyyara",
"bukra"): a keyword sets the plan's preference or the pickup day. Anything else the client
writes is not understood. That is the point of this contender.

These rules were frozen before the agent's first run, and stay as they are. A second
policy, `rules_asking`, adds one rule in front (decision log BLD-D28: the product asks
before it searches): 0. until the client has answered, ask the fixed question (car or on
foot, which day) and do nothing else. Its answer is read with the same keywords.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from dawalink.agent.llm import AssistantTurn, ModelReply, Prompt, ToolCall, ToolResults, UserText

NAME = "rules"
ASKING = "rules_asking"  # the same rules, behind one question (rule 0)
ANSWERED = "answered"  # its note, once the client has answered the question
CALLS_PER_TURN = 6  # the same limit as the agent's (docs/04 N-34)
BRANDS_PER_TURN = 2  # three tool calls each

# --- what the client's words mean, by keyword ----------------------------------------------
# A constraint (no car) beats a wish (cheap) when one message holds both.
PREFERENCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "walkable",
        (
            "no car",
            "have a car",  # "I don't have a car"
            "on foot",
            "walk",
            "ma 3ande siyyara",
            "ma 3andi siyyara",
            "mashi",
            "ما عندي سيارة",
            "مشي",
        ),
    ),
    ("cheapest", ("cheap", "rkhis", "arkhas", "رخيص", "أرخص", "ارخص")),
    ("nearest", ("near", "close", "2arib", "a2rab", "bas bi", "قريب", "أقرب", "اقرب")),
    (
        "fewest_trips",
        ("one trip", "one pharmacy", "same pharmacy", "mishwar wa7ad", "مشوار واحد"),
    ),
)
# The policy that asks hears "I have a car" as an answer, so "have a car" alone can no
# longer mean "no car". Nothing else differs.
PREFERENCES_WHEN_ASKING: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "walkable",
        (
            *(word for word in PREFERENCES[0][1] if word != "have a car"),
            "don't have a car",
            "dont have a car",
            "do not have a car",
        ),
    ),
    *PREFERENCES[1:],
)
TOMORROW = ("tomorrow", "bukra", "bokra", "بكرا", "بكرة")
RESERVE = ("reserve", "7jez", "e7jez", "احجز")

_SECTION = "## "
_LINE = re.compile(r"^\[(\d+)\] (client|you|event|system card|DawaLink team): ?(.*)$")
_DAY = re.compile(r"= (\d{4}-\d{2}-\d{2})")
_LBP = re.compile(r"^([\d,]+) LBP")
_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")

# The last line of the prompt says why the turn runs (`agent/context.py`).
TRIGGERS = {
    "The client wrote": "client_message",
    "The client just started": "request_submitted",
    "Something changed": "decision_event",
    "One hour is left": "window_check",
    "This is the follow-up": "followup",
}

TEXTS = {
    "found": (
        "I found some of your medicines. Each card below is one pharmacy: tap it to reserve.",
        "لقيت قسم من أدويتك. كل بطاقة تحت هي صيدلية: اضغط عليها للحجز.",
    ),
    "waiting": (
        "For what is missing, I'm watching for new stock.",
        "للأدوية الناقصة، عم راقب إذا بيوصل منها.",
    ),
    "asked": (
        "I also asked pharmacies that may have it.",
        "وسألت كمان صيدليات ممكن يكون عندها.",
    ),
    "ask_first": (
        "Before I search: do you have a car, or will you go on foot? And which day will you "
        "come: today or tomorrow?",
        "قبل ما دوّر: عندك سيارة أو بتروح مشي؟ وأي يوم بدك تجي: اليوم أو بكرا؟",
    ),
    "nothing_new": (
        "I'm still looking. Nothing new for now.",
        "بعدني عم دور. ما في شي جديد هلق.",
    ),
    "ask_brands": (
        "One hour is left and something is still missing. Do you want to hear about other "
        "brands of the same medicines? Tap the card to say yes.",
        "بقي ساعة وفي شي ناقص بعد. بدك تعرف عن ماركات تانية لنفس الأدوية؟ اضغط البطاقة لتوافق.",
    ),
    "brands": (
        "Your own medicine isn't available yet, but another brand of it is. The card shows "
        "where. Call the pharmacy and ask the pharmacist first.",
        "دواك نفسه مش متوفر بعد، بس في ماركة تانية منه. البطاقة بتبين وين. "
        "اتصل بالصيدلية واسأل الصيدلي أول شي.",
    ),
    "no_brands": (
        "I found no other brand either. I keep watching until the end of the request.",
        "ما لقيت ماركة تانية كمان. رح ضل راقب لآخر الطلب.",
    ),
    "brand_card": (
        "Here is the card to reserve the brand you asked for.",
        "هيدي البطاقة لحجز الماركة يلي طلبتها.",
    ),
    "brand_not_found": (
        "I couldn't find that brand available now.",
        "ما لقيت هالماركة متوفرة هلق.",
    ),
    "closed": (
        "This request is closed.",
        "هالطلب مسكّر.",
    ),
}


@dataclass(frozen=True)
class Done:
    """One tool call of this turn and what it returned."""

    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    ok: bool


@dataclass(frozen=True)
class View:
    """What the rules read from the prompt."""

    trigger: str
    days: tuple[str, ...]  # the upcoming days, today first
    remembered: dict[str, Any]
    request: dict[str, Any] | None
    client_lines: tuple[str, ...]  # everything the client wrote, oldest first
    fresh_client_lines: tuple[str, ...]  # since the last reply
    fresh_events: tuple[str, ...]
    done: tuple[Done, ...]
    # Only for the policy that asks first (`rules_asking`).
    asks_first: bool = False
    answered: bool = False  # the client wrote something after the question

    @property
    def calls_left(self) -> int:
        return CALLS_PER_TURN - len(self.done)

    def called(self, name: str) -> list[Done]:
        return [step for step in self.done if step.name == name]


def _sections(block: str) -> dict[str, str]:
    found: dict[str, str] = {}
    title = ""
    for line in block.splitlines():
        if line.startswith(_SECTION):
            title = line[len(_SECTION) :].strip()
            found[title] = ""
        elif title:
            found[title] += line + "\n"
    return found


def _json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text.strip() or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _answered(lines: list[tuple[str, ...]], remembered: dict[str, Any]) -> bool:
    """Has the client written anything after the question? The note covers a thread so long
    that the question is no longer among the messages shown."""
    if ANSWERED in (remembered.get("situation_notes") or []):
        return True
    questions = tuple(TEXTS["ask_first"])
    asked = next(
        (index for index, (_, who, text) in enumerate(lines) if who == "you" and text in questions),
        None,
    )
    return asked is not None and any(who == "client" for _, who, _ in lines[asked + 1 :])


def read(prompt: Prompt, *, asks_first: bool = False) -> View:
    """The facts of the turn, taken from the prompt alone."""
    first = prompt.messages[0]
    block = first.text if isinstance(first, UserText) else ""
    sections = _sections(block)
    what_now = sections.get("What to do now", "").strip()
    trigger = next(
        (name for start, name in TRIGGERS.items() if what_now.startswith(start)), "decision_event"
    )
    lines = [
        match.groups()
        for match in map(
            _LINE.match, sections.get("The conversation so far (oldest first)", "").splitlines()
        )
        if match
    ]
    last_reply = max((index for index, line in enumerate(lines) if line[1] == "you"), default=-1)
    fresh = lines[last_reply + 1 :]

    calls: dict[str, ToolCall] = {}
    done: list[Done] = []
    for message in prompt.messages[1:]:
        if isinstance(message, AssistantTurn):
            calls.update({call.id: call for call in message.reply.tool_calls})
        elif isinstance(message, ToolResults):
            for result in message.results:
                call = calls.get(result.call_id)
                if call is not None and call.name != "reply":
                    done.append(
                        Done(call.name, call.arguments, _json(result.content), not result.is_error)
                    )
    request = _json(sections.get("This request", ""))
    remembered = _json(sections.get("What you remember (case state)", ""))
    return View(
        trigger=trigger,
        days=tuple(_DAY.findall(sections.get("Now", ""))),
        remembered=remembered,
        asks_first=asks_first,
        answered=asks_first and _answered(lines, remembered),
        request=request or None,
        client_lines=tuple(text for _, who, text in lines if who == "client"),
        fresh_client_lines=tuple(text for _, who, text in fresh if who == "client"),
        fresh_events=tuple(text for _, who, text in fresh if who == "event"),
        done=tuple(done),
    )


# --- keywords -------------------------------------------------------------------------------


def _has(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(keyword in lowered for keyword in keywords)


def preference_of(view: View) -> str | None:
    """The newest thing the client wrote that a keyword recognises, else what was noted."""
    for line in reversed(view.client_lines):
        for preference, keywords in PREFERENCES_WHEN_ASKING if view.asks_first else PREFERENCES:
            if _has(line, keywords):
                return preference
    remembered = view.remembered.get("preference")
    return remembered if isinstance(remembered, str) else None


def pickup_day_of(view: View) -> str | None:
    if len(view.days) > 1 and any(_has(line, TOMORROW) for line in view.client_lines):
        return view.days[1]
    return None


def writes_arabic(view: View) -> bool:
    """The reply uses the script of the client's last message."""
    lines = view.fresh_client_lines or view.client_lines
    if not lines:
        return False
    text = lines[-1]
    return len(_ARABIC.findall(text)) > len(_LATIN.findall(text))


# --- the request's items ----------------------------------------------------------------------


def _money(shown: str | None) -> dict[str, Any] | None:
    """A budget as the prompt shows it ("716,000 LBP (about $8.00)"), as a tool takes it."""
    match = _LBP.match(shown or "")
    if match is None:
        return None
    return {"amount": int(match.group(1).replace(",", "")), "currency": "LBP"}


def _lbp(shown: str) -> int:
    money = _money(shown)
    return int(money["amount"]) if money else 0


def _left(item: dict[str, Any]) -> int:
    return int(item["qty"]) - int(item["qty_secured"])


def _unsecured(view: View, *, with_a_card: bool = False) -> list[dict[str, Any]]:
    """The medicines still missing. Those with a card waiting for the client's tap are left
    out, unless `with_a_card`."""
    assert view.request is not None
    states = ("SEARCHING", "WAITING", "PROPOSED") if with_a_card else ("SEARCHING", "WAITING")
    return [item for item in view.request["items"] if item["state"] in states and _left(item) > 0]


def _basket_item(item: dict[str, Any]) -> dict[str, Any]:
    line = {
        "product_id": item["product_id"],
        "qty": min(_left(item), 3),
        "days_of_use": item["days_of_use"],
    }
    budget = _money(item.get("max_price"))
    if budget is not None:
        line["max_price"] = budget
    return line


# --- the rules --------------------------------------------------------------------------------

Step = tuple[str, dict[str, Any]]  # a tool's name and its arguments


def _reply(view: View, *texts: str, cards: list[str] | None = None) -> Step:
    column = 1 if writes_arabic(view) else 0
    arguments: dict[str, Any] = {"text": " ".join(TEXTS[text][column] for text in texts)}
    if cards:
        arguments["proposal_ids"] = cards[:5]
    notes: dict[str, Any] = {
        "preference": preference_of(view),
        "pickup_day": pickup_day_of(view),
        # The notes have fixed fields (`agent/state.py`): this one holds free words.
        "situation_notes": [ANSWERED] if view.answered else None,
    }
    if any(notes.values()):
        arguments["case_notes"] = {key: value for key, value in notes.items() if value}
    return ("reply", arguments)


def _cards(view: View) -> list[str]:
    """The cards this turn's tools made."""
    cards: list[str] = []
    for step in view.done:
        if not step.ok:
            continue
        if step.name == "propose_plan":
            cards += [card["proposal_id"] for card in step.result.get("proposals", [])]
        elif "proposal_id" in step.result:
            cards.append(step.result["proposal_id"])
    return cards


def _best_plan(view: View, plans: list[dict[str, Any]]) -> dict[str, Any]:
    """With a stated preference: the planner's own first plan. Without one: the fixed score
    of docs/08: what covers most, then the shortest drive, then the lowest price."""
    if preference_of(view) is not None:
        return plans[0]
    return min(
        plans,
        key=lambda plan: (
            sum(gap["qty_missing"] for gap in plan["missing"]),
            plan["route"]["total_car_min"],
            _lbp(plan["total"]),
        ),
    )


def _source(view: View) -> Step:
    """Rule 3: plan, propose, wait for the rest, ask pharmacies."""
    assert view.request is not None
    # A medicine with a card waiting for the client's tap is left alone, unless the client
    # just wrote: then the card may not suit them, and everything not secured is planned again.
    again = ("SEARCHING", "PROPOSED") if view.fresh_client_lines else ("SEARCHING",)
    searching = [
        item for item in view.request["items"] if item["state"] in again and _left(item) > 0
    ]
    planned = view.called("plan_basket")
    if searching and not planned and view.calls_left > 0:
        arguments: dict[str, Any] = {"items": [_basket_item(item) for item in searching[:5]]}
        if pickup_day_of(view):
            arguments["pickup_day"] = pickup_day_of(view)
        if preference_of(view):
            arguments["preference"] = preference_of(view)
        return ("plan_basket", arguments)

    found = planned[0].result if planned and planned[0].ok else {}
    plans = [plan for plan in found.get("plans", []) if plan["groups"]]
    chosen = _best_plan(view, plans) if plans else None
    if chosen is not None and not view.called("propose_plan") and view.calls_left > 0:
        return ("propose_plan", {"plan_id": chosen["plan_id"]})

    # What no plan covers waits for new stock, in the client's turn (first come, first served).
    if chosen is not None:
        gaps = {gap["product_id"] for gap in chosen["missing"]}
    else:
        gaps = {item["product_id"] for item in searching}
    gaps |= {gap["product_id"] for gap in found.get("unplannable", [])}
    opened = {step.arguments["request_item_id"] for step in view.called("open_claim")}
    to_open = [
        item["item_id"]
        for item in searching
        if item["product_id"] in gaps
        and item["waiting"].get("claim_id") is None
        and item["item_id"] not in opened
    ]
    # Every medicine that waits and has no ask running: ask pharmacies for private stock.
    claims = [
        step.result["claim_id"] for step in view.called("open_claim") if "claim_id" in step.result
    ] + [
        item["waiting"]["claim_id"]
        for item in _unsecured(view)
        if item["waiting"].get("claim_id")
        and not item["waiting"]["asked_pharmacies"]
        and not item["waiting"]["open_offer_count"]
    ]
    asked = {step.arguments["claim_id"] for step in view.called("request_early_release")}
    to_ask = [claim for claim in claims if claim not in asked]

    work_left = len(to_open) + len(to_ask)
    if (
        work_left > view.calls_left
        and view.calls_left == 1
        and not view.called("schedule_followup")
    ):
        # More to do than this turn may: come back in a quarter of an hour.
        return ("schedule_followup", {"in_minutes": 15})
    if to_open and view.calls_left > 0:
        return ("open_claim", {"request_item_id": to_open[0]})
    if to_ask and view.calls_left > 0:
        return ("request_early_release", {"claim_id": to_ask[0]})

    cards = _cards(view)
    texts = ["found"] if cards else []
    if view.called("open_claim") or any(item["state"] == "WAITING" for item in _unsecured(view)):
        texts.append("waiting")
    if any(step.ok and step.result.get("asked") for step in view.called("request_early_release")):
        texts.append("asked")
    return _reply(view, *(texts or ["nothing_new"]), cards=cards)


def _brand_steps(view: View, item: dict[str, Any]) -> Step | list[dict[str, Any]]:
    """Looks up the other brands of one medicine. A step to take, or the options found."""
    product = item["product_id"]
    looked = [
        step for step in view.called("get_equivalents") if step.arguments["product_id"] == product
    ]
    if not looked:
        return ("get_equivalents", {"product_id": product})
    others = [other["id"] for other in looked[0].result.get("products", [])] if looked[0].ok else []
    if not others:
        return []
    searched = [
        step for step in view.called("find_options") if step.arguments["product_ids"][0] == product
    ]
    if not searched:
        arguments: dict[str, Any] = {
            "product_ids": [product, *others][:10],
            "qty": min(_left(item), 3),
            "days_of_use": item["days_of_use"],
            "limit": 10,
        }
        budget = _money(item.get("max_price"))
        if budget is not None:
            arguments["max_price"] = budget
        return ("find_options", arguments)
    options = searched[0].result.get("options", []) if searched[0].ok else []
    return [option for option in options if option["is_alternative"]]


def _show_brands(view: View) -> Step:
    """Rule 2: another brand for the first medicines still missing."""
    assert view.request is not None
    if not view.request["alternatives_ok"]:
        if view.called("propose_constraint_change"):
            return _reply(view, "ask_brands", cards=_cards(view))
        return (
            "propose_constraint_change",
            {"request_id": view.request["request_id"], "show_other_brands": True},
        )
    # One hour is left: a card nobody tapped didn't help, so its medicine counts as missing.
    for item in _unsecured(view, with_a_card=True)[:BRANDS_PER_TURN]:
        shown = [
            step
            for step in view.called("show_other_brand")
            if step.arguments["instead_of_product_id"] == item["product_id"]
        ]
        if shown:
            continue
        found = _brand_steps(view, item)
        if isinstance(found, tuple):
            return found if view.calls_left > 0 else _reply(view, "nothing_new")
        if found and view.calls_left > 0:
            return (
                "show_other_brand",
                {
                    "listing_id": found[0]["listing_id"],
                    "instead_of_product_id": item["product_id"],
                    "days_of_use": item["days_of_use"],
                },
            )
    cards = _cards(view)
    return _reply(view, "brands" if cards else "no_brands", cards=cards)


def _reserve_brand(view: View) -> Step:
    """Rule 1: the client asks, in a message of their own, to reserve a brand they name."""
    message = view.fresh_client_lines[-1].casefold()
    if view.called("propose_reservation"):
        cards = _cards(view)
        return _reply(view, "brand_card" if cards else "brand_not_found", cards=cards)
    for item in _unsecured(view, with_a_card=True)[:BRANDS_PER_TURN]:
        found = _brand_steps(view, item)
        if isinstance(found, tuple):
            return found if view.calls_left > 0 else _reply(view, "brand_not_found")
        named = [option for option in found if option["product"].casefold() in message]
        if named and named[0]["pickup_days_allowed"] and view.calls_left > 0:
            return (
                "propose_reservation",
                {
                    "listing_id": named[0]["listing_id"],
                    "qty": min(_left(item), named[0]["available"], 3),
                    "pickup_day": pickup_day_of(view)
                    if pickup_day_of(view) in named[0]["pickup_days_allowed"]
                    else named[0]["pickup_days_allowed"][0],
                    "days_of_use": item["days_of_use"],
                    "client_asked_for_this_brand": True,
                },
            )
    return _reply(view, "brand_not_found")


def next_step(view: View) -> Step:
    """The rules, in order."""
    if view.request is None or view.request.get("state") != "OPEN":
        return _reply(view, "closed")
    if view.asks_first and not view.answered:
        # Rule 0 of `rules_asking`: nothing is searched before the client has answered.
        return _reply(view, "ask_first")
    if view.fresh_client_lines and _has(view.fresh_client_lines[-1], RESERVE):
        return _reserve_brand(view)
    agreed_now = any(
        event.startswith("constraints_changed") and "other brands" in event
        for event in view.fresh_events
    )
    if view.trigger == "window_check" or agreed_now:
        return _show_brands(view)
    return _source(view)


class RulesModel:
    """The rules, behind the interface of a model (`agent/llm`)."""

    def __init__(self, *, asks_first: bool = False) -> None:
        self.calls = 0
        self.asks_first = asks_first
        self.name = ASKING if asks_first else NAME

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        self.calls += 1
        name, arguments = next_step(read(prompt, asks_first=self.asks_first))
        return ModelReply(text="", tool_calls=(ToolCall(f"rules-{self.calls}", name, arguments),))
