"""The simulated client (docs/08 §2.4): the same person whoever serves them.

A simulated client knows their own situation, like a real one: they have a car or not,
they are free at some hours, they can go from a given day on. Nobody else knows it unless
they say it. What they do never depends on the contender:

- an **offer** (a box held for them for two hours): they accept it if they can really go
  and pick it up, most of the time (`Params.accepts_offer`);
- a **card to reserve** (one box, or one pharmacy of a plan): they tap it if it works for
  them, most of the time (`Params.taps_card`). If it can't work, they don't tap, and they
  write why, once: "I don't have a car". A card that ignores what they already wrote is
  counted (`Sim.unusable_after_told`);
- **"tell you about other brands?"**: they tap it like any card. A higher budget: never,
  their budget is what they can pay;
- an **"another brand" card**: they say thanks and stop, or ask to reserve that brand, or
  ask to keep looking for their own medicine (decision log BLD-D17: the call to the
  pharmacist is not simulated).

What they write comes from a few fixed sentences per language, picked by the seed.
"""

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select

from dawalink.agent.chat import post_client_message
from dawalink.db.models import ChatMessage, InventoryItem, Order, Pharmacy, Product, Proposal
from dawalink.domain.pickup import pharmacy_pickup_days
from dawalink.domain.vocabulary import ProposalKind
from dawalink.services import events, orders, pharmacies, proposals, requests, travel
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.requests import RequestLine
from dawalink.sim import situation
from dawalink.sim.engine import Sim
from dawalink.sim.scenario import Need
from dawalink.sim.situation import Trip
from dawalink.sim.world import numbers_for

# What a client can write, by what it says and by language. "{brand}" is a product's name.
WORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "no_car": {
        "english": (
            "I don't have a car",
            "I'll be going on foot",
            "No car, so somewhere I can walk to please",
        ),
        "arabizi": (
            "ma 3ande siyyara",
            "ana meshe, ma fi siyyara",
            "bade shi 2arib rou7 3leh mashi",
        ),
        "arabic": ("ما عندي سيارة", "رح روح مشي", "بدي مكان قريب أوصله مشي"),
    },
    "after_18": {
        "english": (
            "I can only go after 6 pm",
            "I finish work at 6, so after that",
            "Evenings only for me",
        ),
        "arabizi": (
            "ma b2dar rou7 abel l se3a 6 l masa",
            "bkhalles sheghel 3al 6, ba3da b2dar",
            "bas bl masa b2dar",
        ),
        "arabic": (
            "ما بقدر روح قبل الساعة ٦ المسا",
            "بخلص شغل عالستة، بعدها بقدر",
            "بس بالمسا بقدر",
        ),
    },
    "before_14": {
        "english": (
            "I can only go before 2 pm",
            "Mornings only for me",
            "I'm busy from 2 pm on",
        ),
        "arabizi": (
            "bas abel l se3a 2 b2dar rou7",
            "bas l sobo7 b2dar",
            "mn l se3a 2 w tlou3 mashghoul",
        ),
        "arabic": ("بس قبل الساعة ٢ بقدر روح", "بس الصبح بقدر", "من الساعة ٢ وطلوع مشغول"),
    },
    "only_tomorrow": {
        "english": (
            "I can only go tomorrow",
            "Not today, tomorrow",
            "I can't make it today",
        ),
        "arabizi": (
            "ma b2dar rou7 lyom, bukra",
            "bas bukra b2dar",
            "lyom ma fiye",
        ),
        "arabic": ("ما بقدر روح اليوم، بكرا", "بس بكرا بقدر", "اليوم ما فيي"),
    },
    "cheapest": {
        "english": (
            "The cheapest please, even if it's two trips",
            "Cheapest option please",
            "I need to save as much as I can",
        ),
        "arabizi": (
            "l arkhas iza btrid",
            "bade l rkhis law b2ele mishwarein",
            "ma ma3e ktir, a2al se3er",
        ),
        "arabic": ("الأرخص إذا بتريد", "بدي الرخيص ولو بقلي مشوارين", "ما معي كتير، أقل سعر"),
    },
    "nearest": {
        "english": (
            "The closest pharmacy please",
            "Somewhere near me",
            "I don't want to go far",
        ),
        "arabizi": ("l a2rab iza btrid", "shi 2arib menne", "ma bade rou7 b3id"),
        "arabic": ("الأقرب إذا بتريد", "شي قريب مني", "ما بدي روح بعيد"),
    },
    "fewest_trips": {
        "english": (
            "One pharmacy for everything if possible",
            "I'd rather make one trip",
            "All from the same place please",
        ),
        "arabizi": (
            "kellon mn nafs l saydaliyye iza fi",
            "bade mishwar wa7ad",
            "ma bade lef 3a kaza saydaliyye",
        ),
        "arabic": ("كلن من نفس الصيدلية إذا في", "بدي مشوار واحد", "ما بدي لف على كذا صيدلية"),
    },
    # Answers to a question, when the plain truth is "no constraint" (decision log BLD-D27).
    "has_car": {
        "english": ("I have a car", "I'll be driving", "By car"),
        "arabizi": ("3ande siyyara", "bel siyyara", "ana jeye bel siyyara"),
        "arabic": ("عندي سيارة", "بالسيارة", "جاي بالسيارة"),
    },
    "today_ok": {
        "english": ("Today is fine", "I can go today", "Today"),
        "arabizi": ("lyom mni7", "b2dar rou7 lyom", "lyom"),
        "arabic": ("اليوم منيح", "بقدر روح اليوم", "اليوم"),
    },
    "any_time": {
        "english": ("Any time works", "I'm free all day"),
        "arabizi": ("ayya wa2et", "fadye kel l nhar"),
        "arabic": ("أي وقت", "فاضي كل النهار"),
    },
    "cant_go": {
        "english": ("I can't get there in time",),
        "arabizi": ("ma bel7a2 ousal",),
        "arabic": ("ما بلحق أوصل",),
    },
    "brand_thanks": {
        "english": ("Ok, thank you",),
        "arabizi": ("tamem, shukran",),
        "arabic": ("تمام، شكرا",),
    },
    "brand_reserve": {
        "english": ("I asked the pharmacist and it's fine. Please reserve {brand} for me",),
        "arabizi": ("7kit ma3 l saydale w 2al mashe l 7al. 7jezle {brand} iza btrid",),
        "arabic": ("حكيت مع الصيدلي وقال ماشي الحال. احجزلي {brand} إذا بتريد",),
    },
    "brand_keep_looking": {
        "english": ("No thanks, please keep looking for my medicine",),
        "arabizi": ("la2 shukran, dawwerle 3a dawaye nafso",),
        "arabic": ("لا شكرا، كمّل دور على دواي نفسه",),
    },
}


# What a question is about, as the agent may word it in English, Arabic or Arabizi. The
# client doesn't understand language: these few words are how it knows what was asked.
# A sentence that asks: what stands before a question mark, back to the sentence's start.
QUESTION = re.compile(r"[^.!?؟\n]+[?؟]")
ASKS_THE_DAY = re.compile(
    r"which day|what day|when (?:will|can|do|would) you|pick ?up day|pick (?:it|them) up|"
    r"today or|today,|come today|tomorrow|"
    r"[ae]yy?a? (?:yom|nhar)|emta|aymta|lyom|bukra|bokra|"
    r"أي يوم|اي يوم|أي نهار|اي نهار|إمتى|امتى|ايمتى|إيمتى|متى|اليوم|بكرا|بكرة",
    re.IGNORECASE,
)
ASKS_THE_TRANSPORT = re.compile(
    r"\bcar\b|on foot|\bwalk|\bdriv|s[aie]yy?ar|mashi|mesh[ei]|2ejr|سيارة|سيّارة|مشي|"
    r"إجري|اجري",
    re.IGNORECASE,
)
ASKS_THE_HOURS = re.compile(
    r"what time|which hours?|when are you free|ayy?a? se3a|أي ساعة|اي ساعة", re.IGNORECASE
)
MAX_ANSWERS = 4  # a client doesn't answer the same assistant for ever


def answers_to(text: str, need: Need) -> list[str]:
    """What this client answers to a message of the agent: the truth about what was asked
    (their day, how they get there, when they are free). Nothing when it asks nothing, or
    something else."""
    # Only the sentences that ask count: "It is reserved for today." asks nothing.
    asked = " ".join(QUESTION.findall(text))
    client, facts = need.client, []
    if ASKS_THE_DAY.search(asked):
        facts.append("only_tomorrow" if need.pickup_in_days else "today_ok")
    if ASKS_THE_TRANSPORT.search(asked):
        facts.append("has_car" if client.has_car else "no_car")
    if ASKS_THE_HOURS.search(asked):
        facts.append(client.free if client.free != "any" else "any_time")
    return facts


def words(sim: Sim, need: Need, what: str, **names: str) -> str:
    """The sentence this client writes for this: the same in every run of the seed."""
    language = need.client.language
    if language not in ("english", "arabizi", "arabic"):
        # "mixed": mostly Arabizi, sometimes English.
        mixed = numbers_for(sim.seed, "mixed", need.n, what).random()
        language = "arabizi" if mixed < 0.6 else "english"
    choices = WORDS[what][language]
    return numbers_for(sim.seed, "words", need.n, what).choice(choices).format(**names)


# --- offers: the same for every contender ---------------------------------------------------


def day_that_suits(sim: Sim, tx: Tx, need: Need, order: Order) -> date | None:
    """The first day this pharmacy allows on which the client can really go."""
    pharmacy = tx.session.get_one(Pharmacy, order.pharmacy_id)
    hours = pharmacies.weekly_hours(tx, [pharmacy.id])[pharmacy.id]
    way = travel.travel_to(tx, sim.location_of(need.client), [pharmacy.id])[pharmacy.id]
    trip = Trip(way.car_min, way.walk_min)
    for day in pharmacy_pickup_days(hours, pharmacy.pickup_days, tx.now):
        if sim.works_for(need, pharmacy.id, trip, day):
            return day
    return None


def answer_offer(sim: Sim, need: Need, order_id: uuid.UUID) -> None:
    """Accepts the offer if the client can go and wants it; otherwise gives the box back."""
    client = need.client
    with sim.tx() as tx:
        order = tx.session.get_one(Order, order_id)
        if order.state != "OFFERED":
            return
        day = day_that_suits(sim, tx, need, order)
        wants = sim.chance("accepts", need.n, *sim.box(order)) < sim.params.accepts_offer
    sim.taps[need.n] += 1
    if day is not None and wants:
        sim.attempt(lambda tx: orders.accept_offer(tx, client.id, order_id, day))
    else:
        sim.attempt(lambda tx: orders.end_offer(tx, order_id, declined_by=client.id))


def new_offers(sim: Sim, seen: set[uuid.UUID]) -> list[tuple[Need, Order]]:
    """Offers no client has looked at yet. Each is returned once."""
    with sim.tx() as tx:
        rows = tx.session.execute(select(Order).where(Order.state == "OFFERED")).scalars()
        found = [
            (sim.need_of[order.client_id], order)
            for order in rows
            if order.client_id in sim.need_of and order.id not in seen
        ]
    seen.update(order.id for _, order in found)
    return found


def answer_offers_later(sim: Sim, seen: set[uuid.UUID]) -> None:
    for need, order in new_offers(sim, seen):
        sim.after(
            sim.client_waits("offer", need.n, *sim.box(order)),
            lambda need=need, order=order: answer_offer(sim, need, order.id),  # type: ignore[misc]
        )


# --- a client with a sourcing request ----------------------------------------------------


@dataclass
class RequestClient:
    """The clients of a day, each with one sourcing request (the no-AI policy and the agent)."""

    thread_of: dict[int, uuid.UUID] = field(default_factory=dict)  # by need
    request_of: dict[int, uuid.UUID] = field(default_factory=dict)
    need_of_thread: dict[uuid.UUID, Need] = field(default_factory=dict)
    seen_offers: set[uuid.UUID] = field(default_factory=set)
    seen_cards: set[uuid.UUID] = field(default_factory=set)
    read_up_to: int = 0  # the newest agent message looked at
    # What each client has written so far, and when: (need, what) -> message number.
    said: dict[tuple[int, str], int] = field(default_factory=dict)
    cards_of: Counter[int] = field(default_factory=Counter)
    answers: Counter[int] = field(default_factory=Counter)  # questions answered, by need
    tries: Counter[tuple[object, ...]] = field(default_factory=Counter)

    def arrive(self, sim: Sim, need: Need) -> None:
        """The client fills the request form, and may add a sentence about themselves."""
        client = need.client

        def start(tx: Tx) -> None:
            request = requests.create_request(
                tx,
                client_id=client.id,
                lines=[
                    RequestLine(line.product_id, line.qty, line.days_of_use, sim.budget_lbp(line))
                    for line in need.lines
                ],
                location=sim.location_of(client),
                alternatives_ok=need.hears_other_brands,
                idempotency_key=f"sim-request-{need.n}",
            )
            thread = events.thread_of_request(tx, request.id)
            assert thread is not None
            self.request_of[need.n], self.thread_of[need.n] = request.id, thread
            self.need_of_thread[thread] = need

        sim.taps[need.n] += 1
        if not sim.attempt(start):
            return
        if need.says is not None:
            self.say(sim, need, need.says)
        if need.later is not None:
            minutes, what = need.later
            sim.at(
                need.at + timedelta(minutes=minutes),
                lambda: self.say(sim, need, what),
            )

    def say(self, sim: Sim, need: Need, what: str, *, about: str = "", **names: str) -> None:
        """Writes one thing in the request's thread. The same thing is written once."""
        self._post(sim, need, what + about, words(sim, need, what, **names))

    def _post(self, sim: Sim, need: Need, name: str, text: str) -> int | None:
        """One message in the request's thread, once per name. Its place in the thread, or
        None when it was already written or couldn't be."""
        key = (need.n, name)
        thread = self.thread_of.get(need.n)
        if key in self.said or thread is None:
            return None
        message_id = uuid.uuid5(uuid.NAMESPACE_OID, f"{sim.seed}-{need.n}-{name}")
        posted: list[int] = []

        def write(tx: Tx) -> None:
            posted.append(
                post_client_message(
                    tx,
                    client_id=need.client.id,
                    conversation_id=thread,
                    text=text,
                    client_message_id=message_id,
                ).seq
            )

        if not sim.attempt(write):
            return None
        self.said[key] = posted[0]
        sim.messages[need.n] += 1
        return posted[0]

    def react(self, sim: Sim) -> None:
        """New offers and new cards: the client deals with each a little later."""
        answer_offers_later(sim, self.seen_offers)
        if not self.need_of_thread:
            return
        with sim.tx() as tx:
            rows = tx.session.execute(
                select(
                    ChatMessage.id,
                    ChatMessage.conversation_id,
                    ChatMessage.seq,
                    ChatMessage.cards,
                    ChatMessage.text_redacted,
                )
                .where(
                    ChatMessage.id > self.read_up_to,
                    ChatMessage.author == "agent",
                    ChatMessage.conversation_id.in_(list(self.need_of_thread)),
                )
                .order_by(ChatMessage.id)
            ).all()
        for message_id, thread, seq, cards, text in rows:
            self.read_up_to = max(self.read_up_to, message_id)
            need = self.need_of_thread[thread]
            asked = answers_to(text or "", need)
            if asked and self.answers[need.n] < MAX_ANSWERS:
                # A question about their request gets an answer (the owner, Q24).
                self.answers[need.n] += 1
                sim.after(
                    sim.client_answers("answer", need.n, self.answers[need.n]),
                    lambda need=need, asked=asked, seq=seq: self._answer(sim, need, asked, seq),  # type: ignore[misc]
                )
            for card in cards or []:
                try:
                    proposal_id = uuid.UUID(str(card))
                except ValueError:
                    continue
                if proposal_id in self.seen_cards:
                    continue
                self.seen_cards.add(proposal_id)
                self.cards_of[need.n] += 1
                sim.after(
                    sim.client_waits("card", need.n, self.cards_of[need.n]),
                    lambda need=need, proposal_id=proposal_id, seq=seq: self._answer_card(  # type: ignore[misc]
                        sim, need, proposal_id, seq
                    ),
                )

    def _answer(self, sim: Sim, need: Need, asked: list[str], question: int) -> None:
        """Answers a question in one message: each thing asked, also when they had said it
        before. One message, so the agent reads the whole answer in one turn."""
        text = ". ".join(words(sim, need, what) for what in asked)
        place = self._post(sim, need, f"answer@{question}", text)
        if place is not None:
            for what in asked:
                # From now on the agent has been told: a card that ignores it counts.
                self.said.setdefault((need.n, what), place)

    # --- cards ----------------------------------------------------------------------------

    def _answer_card(self, sim: Sim, need: Need, proposal_id: uuid.UUID, shown_at: int) -> None:
        with sim.tx() as tx:
            proposal = tx.session.get(Proposal, proposal_id)
            if proposal is None or proposals.state_of(tx, proposal) != "open":
                return
            kind, payload = ProposalKind(proposal.kind), dict(proposal.payload)
            if kind in (ProposalKind.RESERVE, ProposalKind.RESERVE_GROUP):
                where = self._where(sim, tx, need, kind, payload)
            elif kind is ProposalKind.OTHER_BRAND:
                brand = tx.session.get_one(Product, uuid.UUID(payload["product_id"])).moph_name
        if kind in (ProposalKind.RESERVE, ProposalKind.RESERVE_GROUP):
            self._reserve_card(sim, need, proposal_id, where, shown_at)
        elif kind is ProposalKind.CONSTRAINT_CHANGE:
            # Hearing about other brands costs nothing. A higher budget isn't theirs to give.
            if payload.get("alternatives_ok") and self._taps(sim, need, "other-brands"):
                self._tap(sim, need, proposal_id)
        elif kind is ProposalKind.OTHER_BRAND:
            self._other_brand(sim, need, payload, brand)

    def _where(
        self, sim: Sim, tx: Tx, need: Need, kind: ProposalKind, payload: dict[str, object]
    ) -> tuple[uuid.UUID, Trip, date, tuple[object, ...]]:
        """The pharmacy of a card, the trip to it, its pickup day and its medicines."""
        if kind is ProposalKind.RESERVE:
            item = tx.session.get_one(InventoryItem, uuid.UUID(str(payload["listing_id"])))
            pharmacy_id, products = item.pharmacy_id, [item.product_id]
        else:
            pharmacy_id = uuid.UUID(str(payload["pharmacy_id"]))
            items: list[dict[str, str]] = payload["items"]  # type: ignore[assignment]
            products = [uuid.UUID(item["product_id"]) for item in items]
        way = travel.travel_to(tx, sim.location_of(need.client), [pharmacy_id])[pharmacy_id]
        codes = tuple(sorted(str(sim.code_of.get(product, product)) for product in products))
        return (
            pharmacy_id,
            Trip(way.car_min, way.walk_min),
            date.fromisoformat(str(payload["pickup_day"])),
            (sim.pharmacy_of[pharmacy_id].n, *codes),
        )

    def _problem(
        self, sim: Sim, need: Need, pharmacy_id: uuid.UUID, trip: Trip, day: date
    ) -> str | None:
        """Why this client can't pick up there on that day, in their own words. None: they can."""
        client, pharmacy = need.client, sim.pharmacy_of[pharmacy_id]
        if day < sim.pickup_day(need):
            return "only_tomorrow"
        if not situation.can_reach(client, trip):
            return "no_car"
        if not situation.can_go(client, pharmacy, trip, day, sim.now):
            return client.free if client.free != "any" else "cant_go"
        return None

    def _reserve_card(
        self,
        sim: Sim,
        need: Need,
        proposal_id: uuid.UUID,
        where: tuple[uuid.UUID, Trip, date, tuple[object, ...]],
        shown_at: int,
    ) -> None:
        pharmacy_id, trip, day, what = where
        problem = self._problem(sim, need, pharmacy_id, trip, day)
        if problem is not None:
            sim.unusable_cards[need.n] += 1
            told = self.said.get((need.n, problem))
            if told is not None and told < shown_at:
                sim.unusable_after_told[need.n] += 1
            self.say(sim, need, problem)
            return
        if self._taps(sim, need, "card", *what, day.isoformat()):
            self._tap(sim, need, proposal_id)

    def _taps(self, sim: Sim, need: Need, *what: object) -> bool:
        """Does the client tap this? A second card for the same thing is a new draw."""
        key = (need.n, *what)
        self.tries[key] += 1
        return sim.chance("taps", *key, self.tries[key]) < sim.params.taps_card

    def _tap(self, sim: Sim, need: Need, proposal_id: uuid.UUID) -> None:
        client_id = need.client.id
        sim.taps[need.n] += 1
        try:
            with sim.tx() as tx:
                proposals.execute(tx, client_id=client_id, proposal_id=proposal_id)
        except ServiceError as error:
            sim.refusals[error.code.value] += 1
            if error.code is Code.GROUP_ITEM_FAILED:
                # As the API does: the agent is told in a transaction of its own.
                with sim.tx() as tx:
                    proposals.report_failed_group(
                        tx, client_id=client_id, proposal_id=proposal_id, error=error
                    )

    def _other_brand(self, sim: Sim, need: Need, payload: dict[str, object], brand: str) -> None:
        asked = uuid.UUID(str(payload["instead_of_product_id"]))
        code = str(sim.code_of.get(asked, asked))
        if (need.n, "brand" + code) in self.said:  # a second card for the same medicine
            return
        self.said[(need.n, "brand" + code)] = 0
        draw = sim.chance("other-brand", need.n, code)
        params = sim.params
        if draw < params.other_brand_reserve:
            self.say(sim, need, "brand_reserve", about=code, brand=brand)
        elif draw < params.other_brand_reserve + params.other_brand_keep_looking:
            self.say(sim, need, "brand_keep_looking", about=code)
        else:
            self.say(sim, need, "brand_thanks", about=code)
