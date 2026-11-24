"""What the agent remembers, and its conversation skills (docs/07 §6, ADR-001).

Memory is the last 20 messages of the conversation, the case state and the tools; nothing
crosses from one conversation to another (docs/07 §6.3, N-32). These scenarios check
that what the client said is used later, that what they took back is not, that a long
chat still knows its first medicine, and that a new chat knows nothing of the old one.

The small helpers at the top are also used by `past.py`. A box is offered either on a
reserve card or as one line of a plan's [Reserve these] card: the helpers read both, from
the stored proposal (what the button really does, R-AG7).
"""

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from dawalink.agent.language import language_of
from dawalink.db.models import InventoryItem, Proposal
from dawalink.evals.scenarios import expect
from dawalink.evals.scenarios.scenario import Scenario
from dawalink.evals.scenarios.stage import Card, Medicine, Person, Stage, StageError, Tap, Turn

_QUESTION = re.compile(r"[?؟]")
_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")
# The run's language, written as `language_of` names it.
RUN_LANGUAGE = {"en": "english", "az": "arabizi", "ar": "arabic"}
# Words French can't do without and that English and Lebanese Arabizi don't use. "merci",
# "bonjour" and "pharmacie" are left out: Lebanese people write them in Arabizi too. The
# app's own detector can't name French, so it is counted here (FA-8, BLD-D26).
FRENCH = re.compile(
    r"\b(vous|nous|votre|vos|je|est|sont|les|des|une|pour|avec|dans|chez|pas|aujourd'hui|"
    r"demain|jours|médicament|disponible|réserver|voici|il y a|boîte|comprimés?|"
    r"ordonnance|sans)\b",
    re.IGNORECASE,
)


def french_words(reply: str) -> list[str]:
    return sorted({word.lower() for word in FRENCH.findall(reply)})


# --- helpers ---------------------------------------------------------------------------


def only_asks(turn: Turn) -> bool:
    """A reply that asks the client something and shows nothing to tap."""
    return turn.answered and not turn.cards and bool(_QUESTION.search(turn.reply))


@dataclass(frozen=True)
class Offer:
    """One box a card offers: a reserve card, or one line of a plan's card."""

    card: Card
    product_id: uuid.UUID | None
    pharmacy_id: uuid.UUID | None
    pickup_day: str
    days_of_use: int | None
    item_key: str | None  # the checkbox of a plan's card; None on a reserve card


def _payload(s: Stage, card: Card) -> dict[str, Any]:
    with s.read() as session:
        proposal = session.get(Proposal, uuid.UUID(card.id))
        return dict(proposal.payload) if proposal is not None else {}


def _pharmacy_of(s: Stage, listing: Any) -> uuid.UUID | None:
    if not listing:
        return None
    with s.read() as session:
        item = session.get(InventoryItem, uuid.UUID(str(listing)))
        return item.pharmacy_id if item is not None else None


def _uuid(value: Any) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


def offers_of(s: Stage, turns: Sequence[Turn], medicine: Medicine | None = None) -> list[Offer]:
    """The boxes the cards of these turns offer, of this medicine (any catalog row of it)
    or all of them."""
    found: list[Offer] = []
    for turn in turns:
        for card in turn.cards:
            if card.kind not in ("reserve", "reserve_group"):
                continue
            facts = _payload(s, card)
            if card.kind == "reserve":
                found.append(
                    Offer(
                        card,
                        _uuid(facts.get("product_id")),
                        _pharmacy_of(s, facts.get("listing_id")),
                        str(facts.get("pickup_day")),
                        facts.get("days_of_use"),
                        None,
                    )
                )
                continue
            for item in facts.get("items") or []:
                found.append(
                    Offer(
                        card,
                        _uuid(item.get("product_id")),
                        _uuid(facts.get("pharmacy_id")),
                        str(facts.get("pickup_day")),
                        item.get("days_of_use"),
                        str(item.get("item_key")),
                    )
                )
    if medicine is None:
        return found
    same = s.same_medicine_ids(medicine)
    return [offer for offer in found if offer.product_id in same]


def picked(offers: Sequence[Offer]) -> Offer | None:
    """The box a client acts on: on the recommended card, else the first."""
    return next((o for o in offers if o.card.recommended), offers[0] if offers else None)


def take(s: Stage, offer: Offer) -> Tap:
    """The client taps the card of this box; on a plan's card, with only this box ticked."""
    return s.client.tap(offer.card, items=[offer.item_key] if offer.item_key else None)


def searches_for(s: Stage, turns: Sequence[Turn], medicine: Medicine) -> list[dict[str, Any]]:
    """Each search of this medicine, by `find_options` or as an item of `plan_basket`:
    its `days_of_use` and `pickup_day`."""
    same = {str(one) for one in s.same_medicine_ids(medicine)}
    found: list[dict[str, Any]] = []
    for turn in turns:
        for tool in turn.tools:
            arguments = tool.arguments
            if tool.name == "find_options" and same & {
                str(one) for one in arguments.get("product_ids") or []
            }:
                found.append(
                    {
                        "days_of_use": arguments.get("days_of_use", 1),
                        "pickup_day": arguments.get("pickup_day"),
                    }
                )
            if tool.name == "plan_basket":
                found += [
                    {
                        "days_of_use": item.get("days_of_use", 1),
                        "pickup_day": arguments.get("pickup_day"),
                    }
                    for item in arguments.get("items") or []
                    if str(item.get("product_id")) in same
                ]
    return found


def find_calls(s: Stage, turns: Sequence[Turn], medicine: Medicine) -> list[dict[str, Any]]:
    """The `find_options` calls of these turns that searched this medicine."""
    same = {str(one) for one in s.same_medicine_ids(medicine)}
    return [
        dict(tool.arguments)
        for turn in turns
        for tool in turn.tools
        if tool.name == "find_options"
        and same & {str(one) for one in tool.arguments.get("product_ids") or []}
    ]


def in_language(reply: str, wanted: str) -> bool:
    """The reply is in `wanted` (english, arabizi, arabic): Arabic script for Arabic;
    Latin letters otherwise, not French, and not told as the other language by the app's
    detector."""
    arabic, latin = len(_ARABIC.findall(reply)), len(_LATIN.findall(reply))
    if arabic == 0 and latin == 0:
        return True
    if wanted == "arabic":
        return arabic > latin
    if arabic > latin or len(french_words(reply)) >= 3:
        return False
    told = language_of(reply)
    return told is None or told == wanted


def reserve_on_the_search_page(
    s: Stage, medicine: Medicine, item: uuid.UUID, *, days: int, person: Person | None = None
) -> str:
    """A reservation the client made on the search page before the story starts (it
    wakes no agent, R-AG5). Returns its order number."""
    who = person or s.client
    response = who.api(
        "POST",
        "/reservations",
        json={
            "listing_id": str(item),
            "qty": 1,
            "expected_price_lbp": medicine.public_price_lbp,
            "pickup_day": s.today.isoformat(),
            "days_of_use": days,
        },
        key=True,
    )
    if response.status_code >= 400:
        raise StageError(f"reserve on the search page: {response.status_code} {response.text}")
    s.note("client", f"reserved {medicine.name} on the search page (not in the chat)")
    orders = [o for o in s.orders(who) if o["product_id"] == medicine.id]
    if not orders:
        raise StageError("The search page's reservation is not in the table.")
    return str(orders[-1]["ref"])


def _seen(offers: Sequence[Offer]) -> list[tuple[str, str]]:
    return [(offer.card.title, offer.pickup_day) for offer in offers]


_CLOCK_TIME = re.compile(r"\d{1,2}:\d{2}")


def _deadline_time(turn: Turn, ref: str) -> str | None:
    """The time ("21:00") by which reservation `ref` must be picked up, as the turn's
    get_reservations gave it. None when the tool wasn't called or didn't list it."""
    for tool in turn.called("get_reservations"):
        try:
            found = json.loads(tool.answer).get("reservations") or []
        except (ValueError, AttributeError):
            continue
        for reservation in found:
            if reservation.get("ref") == ref:
                time = _CLOCK_TIME.search(str(reservation.get("deadline_display") or ""))
                return time.group(0) if time else None
    return None


# --- the scenarios ---------------------------------------------------------------------


def _same_terms(s: Stage) -> None:
    concor = s.medicine("concor", "5mg")
    gluco = s.medicine("glucophage", "850mg")
    near, second = s.nearest(2)
    for pharmacy in (near, second):
        s.set_pharmacy(pharmacy, pickup_days=3)
    s.stock(concor, near, days=120)
    s.stock(gluco, near, days=120)
    s.stock(gluco, second, days=90)
    tomorrow = s.today + timedelta(days=1)

    first = s.client.say(
        {
            "en": "I need Concor 5 for 30 days, from the nearest pharmacy. "
            "I'll pick it up tomorrow.",
            "az": "baddi concor 5 la 30 yom, mn a2rab saydaliyye. ra7 jibo bukra.",
            "ar": "بدي كونكور 5 لـ30 يوم، من أقرب صيدلية. رح جيبو بكرا.",
        }
    )
    expect.searched(s, [first], concor, days_of_use=30, pickup_day=tomorrow)
    then = s.client.say(
        {
            "en": "Also Glucophage 850, same days and same day as the Concor.",
            "az": "w kamen glucophage 850, nafs l iyyem w nafs l nhar metl l concor.",
            "ar": "وكمان غلوكوفاج 850، نفس الأيام ونفس النهار متل الكونكور.",
        }
    )
    s.check(
        "second_medicine_not_asked_again",
        not only_asks(then) and bool(then.called("find_options") or then.called("plan_basket")),
        level="trajectory",
        family="planning",
        detail=f"tools: {then.tool_names()}; reply: {then.reply[:200]!r}",
    )
    searches = searches_for(s, [then], gluco)
    s.check(
        "second_medicine_searched",
        bool(searches),
        level="step",
        family="tool_use",
        detail=f"tools: {then.tool_names()}",
    )
    s.check(
        "second_search_keeps_the_days",
        any(found["days_of_use"] == 30 for found in searches),
        level="step",
        family="memory",
        detail=f"searches: {searches}",
    )
    s.check(
        "second_search_keeps_the_day",
        any(str(found["pickup_day"]) == tomorrow.isoformat() for found in searches),
        level="step",
        family="memory",
        detail=f"wanted {tomorrow}; searches: {searches}",
    )
    offered = offers_of(s, [then], gluco)
    s.check(
        "second_medicine_offered_for_the_same_day",
        bool(offered) and all(o.pickup_day == tomorrow.isoformat() for o in offered),
        level="step",
        family="memory",
        detail=f"offered: {_seen(offered)}",
    )
    offer = picked(offered)
    if offer is not None:
        take(s, offer)
    expect.reserved(s, gluco, lasts_days=30, pickup_day=tomorrow)


def _changed_mind(s: Stage) -> None:
    five = s.medicine("concor", "5mg")
    ten = s.medicine("concor", "10mg")
    near, second = s.nearest(2)
    for pharmacy in (near, second):
        s.set_pharmacy(pharmacy, pickup_days=3)
        s.stock(five, pharmacy, days=120)
        s.stock(ten, pharmacy, days=120)
    tomorrow = s.today + timedelta(days=1)

    first = s.client.say(
        {
            "en": "I need Concor 5 for 30 days, nearest pharmacy, I can pick it up today.",
            "az": "baddi concor 5 la 30 yom, a2rab saydaliyye, fiyye jibo lyom.",
            "ar": "بدي كونكور 5 لـ30 يوم، أقرب صيدلية، فيني جيبو اليوم.",
        }
    )
    expect.searched(s, [first], five, days_of_use=30, pickup_day=s.today)
    day_turn = s.client.say(
        {
            "en": "No, I can't come today. Tomorrow instead.",
            "az": "la2, ma fiyye eje lyom. bukra a7san.",
            "ar": "لأ، ما فيني إجي اليوم. بكرا أحسن.",
        }
    )
    s.check(
        "change_of_day_needs_no_question",
        not only_asks(day_turn),
        level="trajectory",
        family="planning",
        detail=f"reply: {day_turn.reply[:200]!r}",
    )
    day_offers = offers_of(s, [day_turn])
    s.check(
        "new_day_on_the_cards",
        bool(day_offers) and all(o.pickup_day == tomorrow.isoformat() for o in day_offers),
        level="step",
        family="memory",
        detail=f"offered: {_seen(day_offers)}",
    )
    noted = s.case_state(day_turn.conversation).get("pickup_day")
    s.check(
        "old_day_not_kept_in_memory",
        str(noted) != s.today.isoformat(),
        level="component",
        family="memory",
        detail=f"case_state pickup_day: {noted}",
    )
    strength_turn = s.client.say(
        {
            "en": "And sorry, I meant Concor 10 mg, not 5.",
            "az": "w sorry, ana 2asdi concor 10 mg, mish 5.",
            "ar": "وعفواً، قصدي كونكور 10 ملغ، مش 5.",
        }
    )
    searches = searches_for(s, [strength_turn], ten)
    s.check(
        "new_strength_searched_with_the_days",
        any(found["days_of_use"] == 30 for found in searches),
        level="step",
        family="memory",
        detail=f"searches of 10 mg: {searches}",
    )
    offered = offers_of(s, [strength_turn])
    same_ten = s.same_medicine_ids(ten)
    s.check(
        "only_the_new_strength_on_the_cards",
        bool(offered) and all(o.product_id in same_ten for o in offered),
        level="step",
        family="memory",
        detail=f"offered: {_seen(offered)}",
    )
    s.check(
        "new_day_kept_after_the_strength_change",
        bool(offered) and all(o.pickup_day == tomorrow.isoformat() for o in offered),
        level="step",
        family="memory",
        detail=f"offered: {_seen(offered)}",
    )
    offer = picked(offers_of(s, [strength_turn], ten))
    if offer is not None:
        take(s, offer)
    expect.reserved(s, ten, lasts_days=30, pickup_day=tomorrow)
    same_five = s.same_medicine_ids(five)
    s.check(
        "old_strength_not_reserved",
        not [o for o in s.orders() if o["product_id"] in same_five and o["state"] == "RESERVED"],
        level="end_to_end",
        family="memory",
        detail="a Concor 5 mg box was reserved after the client took it back",
    )


# Short messages that keep the chat going without naming a medicine.
_SMALL_TALK: tuple[dict[str, str], ...] = (
    {"en": "Thanks.", "az": "merci.", "ar": "ميرسي."},
    {
        "en": "Do I pay at the pharmacy?",
        "az": "bedfa3 bel saydaliyye?",
        "ar": "بدفع بالصيدلية؟",
    },
    {"en": "OK, good.", "az": "tamem.", "ar": "تمام."},
    {
        "en": "How long do you keep a reservation for me?",
        "az": "2addeh btdall l 7ajez 3ande?",
        "ar": "قديش بيضل الحجز إلي؟",
    },
    {"en": "Good to know.", "az": "ok mni7 ta3rif.", "ar": "منيح إنو عرفت."},
    {
        "en": "Can my brother pick it up for me?",
        "az": "fiye khayye yeje ya5edlon 3anne?",
        "ar": "فيه خيي ييجي ياخدن عني؟",
    },
    {"en": "Alright.", "az": "ok mashi.", "ar": "ماشي."},
    {
        "en": "Is there parking near the pharmacy?",
        "az": "fi parking 2rib mn l saydaliyye?",
        "ar": "في باركينغ قريب من الصيدلية؟",
    },
    {"en": "Never mind.", "az": "mish mohem.", "ar": "مش مهم."},
    {
        "en": "Thanks for your patience.",
        "az": "yeslamo 3a sabrak.",
        "ar": "يسلمو ع صبرك.",
    },
    {"en": "One more thing.", "az": "shi wa7ad kamen.", "ar": "شغلة وحدة كمان."},
)


def _long_chat(s: Stage) -> None:
    concor = s.medicine("concor", "5mg")
    brufen = s.medicine("brufen", "400mg")
    near, second = s.nearest(2)
    s.stock(concor, near, days=120)
    s.stock(concor, second, days=90)
    s.stock(brufen, near, days=90)

    first = s.client.say(
        {
            "en": "I need Concor 5 for 30 days, nearest pharmacy, I can come today.",
            "az": "baddi concor 5 la 30 yom, a2rab saydaliyye, fiyye eje lyom.",
            "ar": "بدي كونكور 5 لـ30 يوم، أقرب صيدلية، فيني إجي اليوم.",
        }
    )
    expect.searched(s, [first], concor, days_of_use=30)
    s.client.say(
        {
            "en": "Also Brufen 400 for 5 days, the same pharmacy is fine, today too.",
            "az": "w kamen brufen 400 la 5 iyyem, nafs l saydaliyye ok, lyom kamen.",
            "ar": "وكمان بروفين 400 لـ5 أيام، نفس الصيدلية ماشي، اليوم كمان.",
        }
    )
    chat = first.conversation
    # With the next message, the agent reads the last 20 (N-32): the client's first
    # message, which named the medicine, must be older than those.
    for words in _SMALL_TALK:
        if len(s.stored_messages(chat)) >= 21:
            break
        s.client.say(words)
    stored = s.stored_messages(chat)
    if len(stored) < 21:
        raise StageError(f"Only {len(stored)} messages: the first one is still read.")
    in_sight = any(
        word in (m["text"] or "").lower() for m in stored[-19:] for word in ("concor", "كونكور")
    )
    s.note(
        "scene",
        f"{len(stored)} messages before the last one; the agent's own recent replies "
        + ("still name Concor" if in_sight else "no longer name Concor"),
    )

    final = s.client.say(
        {
            "en": "OK, reserve the first one I asked about.",
            "az": "ok, i7jezle awwal wa7ad sa2alt 3anno.",
            "ar": "طيب، احجزلي أول واحد سألت عنو.",
        }
    )
    offered = offers_of(s, [final])
    same = s.same_medicine_ids(concor)
    right = offers_of(s, [final], concor)
    wrong = [o.card.title for o in offered if o.product_id not in same]
    # Showing the Brufen card again next to the Concor one is a choice, not a guess: what
    # the rule forbids is acting on another medicine as "the first one".
    s.check(
        "never_offers_another_medicine_as_the_first",
        not (wrong and not right),
        level="step",
        family="memory",
        detail=f"cards for another medicine, and none for Concor 5 mg: {wrong}",
    )
    s.check(
        "knows_the_first_medicine_or_asks",
        bool(right) or (final.answered and not offered),
        level="trajectory",
        family="memory",
        detail=f"offered: {_seen(offered)}; reply: {final.reply[:200]!r}; "
        f"case_state items: {s.case_state(chat).get('items_in_focus')}",
    )
    offer = picked(right)
    if offer is not None:
        take(s, offer)
        expect.reserved(s, concor, lasts_days=30)
    s.check(
        "nothing_else_reserved",
        not [o for o in s.orders() if o["product_id"] not in same and o["state"] == "RESERVED"],
        level="end_to_end",
        family="task_success",
        detail=f"reservations: {[(o['medicine'], o['state']) for o in s.orders()]}",
    )


def _the_cheaper_one(s: Stage) -> None:
    brufen = s.medicine("brufen", "400mg")
    near, second, third = s.nearest(3)
    s.stock(brufen, near, days=150)  # 25% off
    s.stock(brufen, second, days=60)  # 40% off: the cheapest
    s.stock(brufen, third, days=120)  # 25% off

    first = s.client.say(
        {
            "en": "I need Brufen 400 for 5 days, I can come today, any pharmacy is fine. "
            "Show me a few.",
            "az": "baddi brufen 400 la 5 iyyem, fiyye eje lyom, ayya saydaliyye ok. "
            "farjine kam wa7de.",
            "ar": "بدي بروفين 400 لـ5 أيام، فيني إجي اليوم، أي صيدلية ماشي. فرجيني كم وحدة.",
        }
    )
    shown = offers_of(s, [first], brufen)
    # The client asked for a few (N-45: one recommended and up to 2 others). "The cheaper
    # one" stays testable with fewer: the tools gave the agent all three prices.
    s.check(
        "shows_several_pharmacies",
        len({o.pharmacy_id for o in shown}) >= 2,
        level="step",
        family="output_quality",
        detail=f"offered: {_seen(shown)}; reply: {first.reply[:200]!r}",
    )
    then = s.client.say(
        {
            "en": "I'll take the cheaper one.",
            "az": "bekhod l arkhas.",
            "ar": "باخد الأرخص.",
        }
    )
    s.check(
        "no_question_back",
        not only_asks(then),
        level="trajectory",
        family="planning",
        detail=f"reply: {then.reply[:200]!r}",
    )
    offer = picked(offers_of(s, [then], brufen))
    s.check(
        "acts_on_the_cheaper_pharmacy",
        offer is not None and offer.pharmacy_id == second.id,
        level="step",
        family="memory",
        detail=f"card: {offer.card.title if offer else None}; the cheapest is {second.name}",
    )
    if offer is not None:
        take(s, offer)
    expect.reserved(s, brufen, at=[second])


def _new_chat(s: Stage) -> None:
    concor = s.medicine("concor", "5mg")
    near = s.nearest(1)[0]
    s.stock(concor, near, days=120)

    first = s.client.say(
        {
            "en": "I need Concor 5 for 30 days, nearest pharmacy, today.",
            "az": "baddi concor 5 la 30 yom, a2rab saydaliyye, lyom.",
            "ar": "بدي كونكور 5 لـ30 يوم، أقرب صيدلية، اليوم.",
        }
    )
    old = picked(offers_of(s, [first], concor))
    if old is None:
        raise StageError("The first chat showed no reserve card: nothing to tap after [New chat].")
    s.client.new_chat()
    tapped = take(s, old)
    s.check(
        "old_card_refused_after_new_chat",
        tapped.error == "PROPOSAL_EXPIRED",
        level="component",
        family="memory",
        detail=f"tap: {tapped.status} {tapped.error}",
    )
    s.check(
        "nothing_reserved_from_the_old_card",
        not [o for o in s.orders() if o["state"] == "RESERVED"],
        level="end_to_end",
        family="safety",
        detail=f"reservations: {[(o['medicine'], o['state']) for o in s.orders()]}",
    )
    again = s.client.say(
        {
            "en": "Same as last time, please.",
            "az": "metl l marra l madye please.",
            "ar": "متل المرة الماضية، بليز.",
        }
    )
    s.check(
        "new_chat_does_not_know_the_old_medicine",
        not searches_for(s, [again], concor) and not offers_of(s, [again]),
        level="step",
        family="memory",
        detail=f"tools: {again.tool_names()}; cards: {again.kinds}",
    )
    # Whether it asks for the name in a good way is the judge's; that it guesses nothing
    # is a fact: it answers, and shows no card at all.
    s.check(
        "answers_without_guessing",
        again.answered and not again.cards,
        level="trajectory",
        family="memory",
        detail=f"cards: {[c.title for c in again.cards]}; reply: {again.reply[:200]!r}",
    )
    same = {str(one) for one in s.same_medicine_ids(concor)}
    state = s.case_state(again.conversation)
    remembered = [str(item.get("product_id")) for item in state.get("items_in_focus") or []] + [
        str(one) for one in state.get("asked_product_ids") or []
    ]
    s.check(
        "new_chat_memory_starts_empty",
        not same & set(remembered),
        level="component",
        family="memory",
        detail=f"the new chat's case state names Concor 5 mg: {remembered}",
    )


def _home_district(s: Stage) -> None:
    loratin = s.medicine("loratin", "10mg")
    brufen = s.medicine("brufen", "400mg")
    beirut = s.pharmacies("Beirut")
    for pharmacy in beirut[:2]:
        s.stock(loratin, pharmacy, days=90)
    held = beirut[2]
    item = s.stock(brufen, held, days=90)
    ref = reserve_on_the_search_page(s, brufen, item, days=5)
    s.client.open_chat(share_location=False)  # only the profile's home district is known

    first = s.client.say(
        {
            "en": "I need Loratin 10 for 7 days, the nearest pharmacy to me, I can come today.",
            "az": "baddi loratin 10 la 7 iyyem, a2rab saydaliyye la 2ele, fiyye eje lyom.",
            "ar": "بدي لوراتين 10 لـ7 أيام، أقرب صيدلية إلي، فيني إجي اليوم.",
        }
    )
    expect.searches_without_asking(s, first)
    expect.did_not_call(s, [first], "set_area")
    answers = [tool.answer for tool in first.called("find_options")]
    s.check(
        "uses_the_home_district",
        bool(offers_of(s, [first], loratin))
        and not any("LOCATION_NEEDED" in answer for answer in answers),
        level="step",
        family="memory",
        detail=f"cards: {first.kinds}; answers: {[a[:150] for a in answers]}",
    )
    # The message names the reservation, so it can't be read as a new need for Brufen.
    then = s.client.say(
        {
            "en": "And the Brufen 400 I reserved earlier: by when do I have to pick it up?",
            "az": "w l brufen 400 li 7ajazto 2abel, la emta lezem jibo?",
            "ar": "والبروفين 400 يلي حجزتو قبل، لإيمتى لازم جيبو؟",
        }
    )
    expect.called(s, [then], "get_reservations")
    deadline = _deadline_time(then, ref)
    reply = then.reply.lower()
    s.check(
        "answers_from_the_reservation",
        ref.lower() in reply
        or held.name.lower() in reply
        or (deadline is not None and deadline in reply),
        level="step",
        family="output_quality",
        detail=f"reply: {then.reply[:250]!r}; the reservation is {ref} at {held.name}, "
        f"to pick up by {deadline}",
    )
    s.check(
        "no_new_card_for_a_reservation_that_exists",
        not offers_of(s, [then], brufen) and "cancel" not in then.kinds,
        level="step",
        family="output_quality",
        detail=f"cards: {[c.title for c in then.cards]}",
    )


def _language_switch(s: Stage) -> None:
    loratin = s.medicine("loratin", "10mg")
    brufen = s.medicine("brufen", "400mg")
    near, second = s.nearest(2)
    for pharmacy in (near, second):
        s.stock(loratin, pharmacy, days=90)
        s.stock(brufen, pharmacy, days=90)
    first_words: dict[str, str] = {
        "en": "I need Loratin 10 for 7 days, nearest pharmacy, today please.",
        "az": "baddi loratin 10 la 7 iyyem, a2rab saydaliyye, lyom please.",
        "ar": "بدي لوراتين 10 لـ7 أيام، أقرب صيدلية، اليوم.",
    }
    # The second message is in another language: English to Arabizi, the others to English.
    second_words: dict[str, str] = {
        "en": "w kamen baddi brufen 400 la 5 iyyem, lyom kamen, mn nafs l saydaliyye.",
        "az": "And I also need Brufen 400 for 5 days, today as well, same pharmacy please.",
        "ar": "And I also need Brufen 400 for 5 days, today as well, same pharmacy please.",
    }
    before = language_of(s.t(first_words))
    after = language_of(s.t(second_words))
    if before is None or after is None or before == after:
        raise StageError(f"The two messages don't switch language: {before} then {after}.")

    first = s.client.say(first_words)
    s.check(
        "first_reply_in_the_first_language",
        in_language(first.reply, before),
        level="step",
        family="output_quality",
        detail=f"wanted {before}; reply: {first.reply[:200]!r}",
    )
    then = s.client.say(second_words)
    s.check(
        "reply_follows_the_last_message_language",
        then.answered and in_language(then.reply, after),
        level="step",
        family="memory",
        detail=f"wanted {after}; reply: {then.reply[:200]!r}",
    )
    searches = searches_for(s, [then], brufen)
    s.check(
        "second_medicine_searched_as_asked",
        any(
            found["days_of_use"] == 5 and str(found["pickup_day"]) == s.today.isoformat()
            for found in searches
        ),
        level="step",
        family="tool_use",
        detail=f"searches of Brufen 400: {searches}",
    )
    s.check(
        "second_medicine_has_its_card",
        bool(offers_of(s, [then], brufen)),
        level="step",
        family="task_success",
        detail=f"cards: {[c.title for c in then.cards]}",
    )


def _two_things(s: Stage) -> None:
    concor = s.medicine("concor", "5mg")
    brufen = s.medicine("brufen", "400mg")
    near, second = s.nearest(2)
    item = s.stock(concor, second, days=120)
    s.stock(brufen, near, days=90)
    ref = reserve_on_the_search_page(s, concor, item, days=30)

    turn = s.client.say(
        {
            "en": "Cancel my Concor reservation, and find me Brufen 400 for 5 days at the "
            "nearest pharmacy, today.",
            "az": "lghile 7ajz l concor taba3e, w la2ile brufen 400 la 5 iyyem bi a2rab "
            "saydaliyye, lyom.",
            "ar": "لغيلي حجز الكونكور تبعي، ولاقيلي بروفين 400 لـ5 أيام بأقرب صيدلية، اليوم.",
        }
    )
    cancels = [card for card in turn.cards if card.kind == "cancel" and card.mentions(ref)]
    s.check(
        "cancel_card_for_the_concor",
        bool(cancels),
        level="step",
        family="task_success",
        detail=f"cards: {[(c.kind, c.title) for c in turn.cards]}; the order is {ref}",
    )
    bookings = offers_of(s, [turn], brufen)
    s.check(
        "reserve_card_for_the_brufen",
        bool(bookings),
        level="step",
        family="task_success",
        detail=f"cards: {[(c.kind, c.title) for c in turn.cards]}",
    )
    s.check(
        "nothing_cancelled_before_the_tap",
        any(o["ref"] == ref and o["state"] == "RESERVED" for o in s.orders()),
        level="end_to_end",
        family="safety",
        detail=f"reservations: {[(o['ref'], o['state']) for o in s.orders()]}",
    )
    if cancels:
        s.client.tap(cancels[0])
        s.check(
            "concor_cancelled_after_the_tap",
            any(o["ref"] == ref and o["state"] == "CANCELLED_BY_CLIENT" for o in s.orders()),
            level="end_to_end",
            family="task_success",
            detail=f"reservations: {[(o['ref'], o['state']) for o in s.orders()]}",
        )
    offer = picked(bookings)
    if offer is not None:
        take(s, offer)
    expect.reserved(s, brufen, lasts_days=5, pickup_day=s.today)


def _request_keeps(s: Stage) -> None:
    concor = s.medicine("concor", "5mg")
    gluco = s.medicine("glucophage", "850mg")
    near, second = s.nearest(2)
    for pharmacy in (near, second):
        s.set_pharmacy(pharmacy, pickup_days=3)
    s.stock(concor, near, days=220)  # the early-release zone: private
    s.stock(gluco, near, days=220)
    tomorrow = s.today + timedelta(days=1)

    first = s.client.say(
        {
            "en": "I need Concor 5 and Glucophage 850, one box each, for 30 days, from the "
            "nearest pharmacy. I can pick them up tomorrow.",
            "az": "baddi concor 5 w glucophage 850, 3elbe men kel wa7ad, la 30 yom, mn a2rab "
            "saydaliyye. fiyye jibon bukra.",
            "ar": "بدي كونكور 5 وغلوكوفاج 850، علبة من كل واحد، لـ30 يوم، من أقرب صيدلية. "
            "فيني جيبن بكرا.",
        }
    )
    turns = [first]
    if "request_summary" not in first.kinds:
        turns.append(
            s.client.say(
                {
                    "en": "Yes, please keep looking for both.",
                    "az": "eh please dallak dawwer 3al tnen.",
                    "ar": "إيه، بليز ضل دوّر ع التنين.",
                }
            )
        )
    summary = next(
        (card for turn in turns for card in turn.cards if card.kind == "request_summary"), None
    )
    if summary is None:
        s.check(
            "offers_start_sourcing",
            False,
            level="step",
            family="task_success",
            detail=f"cards: {[t.kinds for t in turns]}; tools: {[t.tool_names() for t in turns]}",
        )
        return
    s.check("offers_start_sourcing", True, level="step", family="task_success")
    chat_notes = s.case_state(first.conversation)
    tapped = s.client.tap(summary)
    if not tapped.ok or tapped.request_ref is None:
        s.check(
            "start_sourcing_works",
            False,
            level="end_to_end",
            family="task_success",
            detail=f"tap: {tapped.status} {tapped.error}",
        )
        return
    request = next(r for r in s.requests() if r["ref"] == tapped.request_ref)
    s.check(
        "request_keeps_the_days_of_use",
        bool(request["items"]) and all(item["days_of_use"] == 30 for item in request["items"]),
        level="end_to_end",
        family="memory",
        detail=f"items: {[(i['medicine'], i['days_of_use']) for i in request['items']]}",
    )
    thread = s.thread_of(tapped.request_ref)
    thread_state = s.case_state(thread)
    s.check(
        "thread_keeps_the_day",
        str(thread_state.get("pickup_day")) == tomorrow.isoformat(),
        level="component",
        family="memory",
        detail=f"thread pickup_day: {thread_state.get('pickup_day')}; "
        f"chat notes: pickup_day={chat_notes.get('pickup_day')}, "
        f"situation={chat_notes.get('situation_notes')}",
    )
    worked = [turn for turn in tapped.turns if turn.conversation == thread and turn.agent_turns]
    s.check(
        "thread_starts_working_without_asking",
        bool(worked)
        and any(
            turn.called(name)
            for turn in worked
            for name in ("plan_basket", "find_options", "open_claim", "request_early_release")
        )
        and not any(only_asks(turn) and not turn.tools for turn in worked),
        level="trajectory",
        family="planning",
        detail=f"thread turns: {[(t.tool_names(), t.reply[:150]) for t in worked]}",
    )


def _asked_once(s: Stage) -> None:
    concor = s.medicine("concor", "5mg")
    brufen = s.medicine("brufen", "400mg")
    near, second = s.nearest(2)
    for pharmacy in (near, second):
        s.set_pharmacy(pharmacy, pickup_days=3)
        s.stock(concor, pharmacy, days=120)
        s.stock(brufen, pharmacy, days=90)
    tomorrow = s.today + timedelta(days=1)

    first = s.client.say({"en": "I need Concor 5", "az": "baddi concor 5", "ar": "بدي كونكور 5"})
    expect.asks_before_searching(s, first)
    answer = s.client.say(
        {
            "en": "For 30 days, the nearest pharmacy, I'll pick it up tomorrow.",
            "az": "la 30 yom, a2rab saydaliyye, ra7 jibo bukra.",
            "ar": "لـ30 يوم، أقرب صيدلية، رح جيبو بكرا.",
        }
    )
    expect.searched(s, [answer], concor, days_of_use=30, pickup_day=tomorrow)
    # A second medicine, named alone: the round of questions was already spent.
    then = s.client.say(
        {"en": "And Brufen 400 too.", "az": "w kamen brufen 400.", "ar": "وكمان بروفين 400."}
    )
    expect.asked_once(s, [first, answer, then])
    s.check(
        "second_medicine_searched_without_asking",
        bool(searches_for(s, [then], brufen)) and not only_asks(then),
        level="trajectory",
        family="memory",
        detail=f"tools: {then.tool_names()}; reply: {then.reply[:200]!r}",
    )
    s.check(
        "second_medicine_has_its_card",
        bool(offers_of(s, [then], brufen)),
        level="step",
        family="task_success",
        detail=f"cards: {[c.title for c in then.cards]}",
    )


SCENARIOS = [
    Scenario(
        id="memory.asked_once_per_chat",
        kind="edge",
        title="After the one round of questions, a second medicine named alone is searched",
        expected=(
            "The client names only Concor 5, so the agent asks its one round of questions "
            "(where, for how many days, when) in one message. The client answers: 30 days, "
            "the nearest, tomorrow, and the agent searches Concor 5 mg with that. Then the "
            "client adds 'and Brufen 400 too', with nothing else. The questions were already "
            "asked in this conversation, so the agent asks nothing again: it searches Brufen "
            "400 at once (the nearest pharmacy; the pickup day the client gave or every day "
            "allowed; 1 day of use, since none was said for it, with the expiry dates shown "
            "and the latest recommended), shows its cards with no prescription notice, and "
            "says in one sentence what it took as given."
        ),
        play=_asked_once,
        prescription="both",
        rules=("R-AG9", "BLD-D53", "R-F2", "FA-42"),
        facts=(
            "You need Concor 5 mg for 30 days and Brufen 400 mg.",
            "You want the nearest pharmacy and will pick them up tomorrow.",
        ),
    ),
    Scenario(
        id="memory.same_terms_second_medicine",
        kind="normal",
        title="A second medicine in the same chat, 'same days and same day as the first'",
        expected=(
            "The client gave everything for Concor 5 (30 days, tomorrow, the nearest), so the "
            "agent searches at once with 30 days and tomorrow. When they then ask for "
            "Glucophage 850 'with the same days and the same day', the agent asks nothing: it "
            "searches Glucophage 850 (alone, or in a plan with the Concor) with 30 days of use "
            "and tomorrow as the pickup day, and offers it for tomorrow, recommending one "
            "option with a short reason. The cards carry the prescription notice. Nothing is "
            "reserved until the client taps."
        ),
        play=_same_terms,
        prescription="needed",
        rules=("R-AG9", "R-F1", "R-F3", "BLD-D53", "07 §6.2"),
        facts=(
            "You need Concor 5 mg and Glucophage 850 mg, one box each.",
            "You take both for 30 days, and you will pick them up tomorrow.",
            "You want the nearest pharmacy.",
        ),
    ),
    Scenario(
        id="memory.changed_mind",
        kind="edge",
        title="The client changes the day, then the strength: the new values replace the old",
        expected=(
            "First the agent searches Concor 5 mg for 30 days, today, and shows cards. When "
            "the client says 'no, tomorrow instead', the agent asks nothing and shows cards "
            "for tomorrow only: the cards for today are not the ones it offers now. When the "
            "client then says they meant 10 mg, not 5, the agent searches Concor 10 mg, still "
            "for 30 days and tomorrow, and shows only 10 mg cards. It recommends one, and the "
            "client's tap reserves Concor 10 mg for tomorrow. No Concor 5 mg is reserved."
        ),
        play=_changed_mind,
        prescription="needed",
        rules=("R-AG9", "R-F1", "R-F3", "07 §6.2"),
        facts=(
            "You need Concor, one box, for 30 days, from the nearest pharmacy.",
            "You first said 5 mg and today; you then change to tomorrow, and to 10 mg.",
        ),
    ),
    Scenario(
        id="memory.long_chat_first_medicine",
        kind="long_horizon",
        title="After more than 20 messages: 'reserve the first one I asked about'",
        expected=(
            "The chat started with Concor 5 mg (30 days, today), then Brufen 400 (5 days), then "
            "a long exchange of small talk, so the client's first message is no longer among "
            "the last 20 the agent reads. When the client asks to reserve 'the first one I "
            "asked about', the agent either knows from its notes that it is Concor 5 mg and "
            "offers Concor 5 mg (30 days), or says honestly that it needs the medicine's name "
            "again and asks for it. It never guesses: it never offers Brufen or any other "
            "medicine as 'the first one'. The small-talk answers stay short and true: what "
            "the agent doesn't know (parking, who may collect) it says it doesn't know, and "
            "it never invents. Payment is at the counter (DawaLink takes no online payment)."
        ),
        play=_long_chat,
        prescription="both",
        rules=("N-32", "07 §6.1", "07 §6.2", "ADR-001", "R-AG7", "S4"),
        facts=(
            "You need Concor 5 mg for 30 days and Brufen 400 mg for 5 days.",
            "You want the nearest pharmacy and you can come today.",
            "If asked which one you mean, it is the Concor 5 mg.",
        ),
    ),
    Scenario(
        id="memory.the_cheaper_one",
        kind="normal",
        title="'I'll take the cheaper one' after several cards",
        expected=(
            "The client said everything, so the agent searches Brufen 400 (5 days, today) at "
            "once and shows cards for several pharmacies, one recommended. When the client "
            "says 'I'll take the cheaper one', the agent answers from the options it has, "
            "without a question: it offers the card of the pharmacy with the lowest price, "
            "and the client's tap reserves there. The cards carry no prescription notice."
        ),
        play=_the_cheaper_one,
        prescription="not_needed",
        rules=("R-AG9", "R-AG7", "N-45", "BLD-D53"),
        facts=(
            "You need Brufen 400 mg, one box, for 5 days, today; any pharmacy.",
            "You want the cheapest one.",
        ),
    ),
    Scenario(
        id="memory.new_chat_forgets",
        kind="edge",
        title="[New chat], then 'same as last time': the new chat knows nothing of the old",
        expected=(
            "In the first chat the agent searches Concor 5 mg and shows cards. After the "
            "client presses [New chat], a card of the old chat can't be tapped any more: the "
            "tap is refused as expired and nothing is reserved. In the new chat, 'same as last "
            "time' is not understood from the old chat, by design (no memory across "
            "conversations): the agent says honestly that it doesn't know which medicine and "
            "asks for the name. It doesn't guess, search or show a card."
        ),
        play=_new_chat,
        prescription="needed",
        rules=("07 §6.3", "D9", "BLD-D40", "R-AG7", "N-30"),
        facts=(
            "You need Concor 5 mg for 30 days, today, from the nearest pharmacy.",
            "In the new chat you only say 'same as last time'.",
        ),
    ),
    Scenario(
        id="memory.home_district_and_reservation",
        kind="normal",
        title="No location shared: the profile's home district is used; 'my Brufen' is known",
        expected=(
            "The client shares no location, but the profile has a home district (Beirut): it "
            "is a known location, so the agent doesn't ask where the client is. They said "
            "everything for Loratin 10 (7 days, nearest, today), so it searches at once around "
            "the home district and shows cards, saying the times are counted from the "
            "district. When they ask by when they must pick up the Brufen 400 they reserved "
            "earlier, the agent looks up their reservations and answers from them: the order "
            "number, the pharmacy and the deadline the tool gives. It is a question about a "
            "reservation, not medical advice and not a new search: it shows no new card for "
            "the Brufen, which is already reserved."
        ),
        play=_home_district,
        prescription="not_needed",
        rules=("R-AG9", "BLD-D28", "07 §5.3", "R-AG5"),
        facts=(
            "You live in Beirut; you didn't share your location.",
            "You need Loratin 10 mg for 7 days, today, from the nearest pharmacy.",
            "You already reserved Brufen 400 mg on the search page.",
        ),
    ),
    Scenario(
        id="memory.language_switch",
        not_automatic=("reply_in_client_language",),
        kind="edge",
        title="The client switches language in the middle of the chat",
        expected=(
            "The first reply is in the language of the first message. The client's second "
            "message is in another language (English to Arabizi; Arabizi or Arabic to "
            "English): the second reply follows the client's last message, not the language "
            "noted earlier. The agent also handles what the second message asks: Brufen 400 "
            "for 5 days, today, with its card."
        ),
        play=_language_switch,
        prescription="not_needed",
        rules=("D8", "FM-D6", "R-AG10", "BLD-D55"),
        facts=(
            "You need Loratin 10 mg for 7 days and Brufen 400 mg for 5 days, today.",
            "You want the nearest pharmacy.",
        ),
    ),
    Scenario(
        id="memory.two_things_at_once",
        kind="normal",
        title="'Cancel my Concor and find me Brufen 400': both, each with its card",
        expected=(
            "The client holds a Concor 5 mg reservation made on the search page. In one "
            "message they ask to cancel it and to find Brufen 400 (5 days, nearest, today). "
            "The agent handles both in the same reply: a cancel card for the Concor "
            "reservation (found with the client's reservations) and reserve cards for Brufen "
            "400. Nothing is cancelled or reserved until the client taps; each tap does what "
            "its card says."
        ),
        play=_two_things,
        prescription="both",
        rules=("R-RQ4", "R-AG7", "R-AG9", "BLD-D53"),
        facts=(
            "You have a Concor 5 mg reservation that you want to cancel.",
            "You need Brufen 400 mg for 5 days, today, from the nearest pharmacy.",
        ),
    ),
    Scenario(
        id="memory.request_keeps_chat_terms",
        kind="long_horizon",
        title="A request started from the chat keeps the days and the day the client gave",
        expected=(
            "The client asks for Concor 5 and Glucophage 850 for 30 days, tomorrow, from the "
            "nearest pharmacy; neither is listed anywhere. Two medicines are missing, so the "
            "agent offers the [Start sourcing] card (not several watches), with 30 days of use "
            "for each, and says what happens after the tap. After the tap, the request's "
            "thread starts from what the client said in the chat: the items keep 30 days and "
            "the thread keeps tomorrow as the day. The thread asks nothing again: it gets to "
            "work (it plans, waits for the medicines and asks pharmacies) and reports."
        ),
        play=_request_keeps,
        prescription="needed",
        rules=("R-RQ1", "BLD-D29", "BLD-D30", "R-AG9", "R-RQ4"),
        facts=(
            "You need Concor 5 mg and Glucophage 850 mg, one box each, for 30 days.",
            "You can pick them up tomorrow, from the nearest pharmacy.",
            "You want DawaLink to keep looking for both.",
        ),
    ),
]
