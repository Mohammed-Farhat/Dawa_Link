"""A medicine's name as people really write it: with its form ("Adol 500 caplets",
"Concor 5 tablets").

Found while the other families were written: five scenarios that named "Adol 500 caplets"
failed at the name itself in Arabizi and Arabic, before reaching what they were about. A
probe of the catalog search showed one cause in the tool: a query that carries a form word
returns no product at all, only "did you mean". Those five scenarios now name a medicine
with one form; the name problem is measured here, alone, with a prescription medicine and
a no-prescription one.
"""

from dawalink.evals.scenarios import expect
from dawalink.evals.scenarios.scenario import Scenario
from dawalink.evals.scenarios.stage import Stage, Turn

SEARCHES = ("find_options", "plan_basket")


def _name_lookups(turn: Turn) -> list[str]:
    return [str(used.arguments.get("query")) for used in turn.called("search_catalog")]


def _with_its_form(s: Stage, turn: Turn, medicine_id: str) -> None:
    """The client wrote the name, the strength, the form and everything else: the agent
    looks the name up, finds the medicine and shows where it is, with no question."""
    lookups = turn.called("search_catalog")
    found = [used for used in lookups if medicine_id in used.answer]
    s.check(
        "looks_the_name_up",
        bool(lookups),
        level="step",
        family="tool_use",
        detail=f"tools: {turn.tool_names()}; reply: {turn.reply[:200]!r}",
    )
    s.check(
        "the_catalog_search_finds_it",
        bool(found),
        level="component",
        family="tool_use",
        detail="search_catalog queries: "
        + " // ".join(
            f"{used.arguments.get('query')!r} -> {used.answer[:120]}" for used in lookups
        ),
    )
    s.check(
        "found_at_the_first_lookup",
        bool(lookups) and medicine_id in lookups[0].answer,
        level="trajectory",
        family="efficiency",
        detail=f"queries in order: {_name_lookups(turn)}",
    )
    s.check(
        "no_other_medicine_taken_instead",
        all(
            medicine_id in {str(one) for one in used.arguments.get("product_ids") or []}
            or not used.ok
            for name in SEARCHES
            for used in turn.called(name)
        ),
        level="step",
        family="safety",
        detail="searched: "
        + str([used.arguments.get("product_ids") for used in turn.called("find_options")]),
    )
    expect.searches_without_asking(s, turn)


def _otc_with_form(s: Stage) -> None:
    adol = s.medicine("adol", "500mg", "caplet")
    near, second = s.nearest(2)
    s.stock(adol, near, days=90)
    s.stock(adol, second, days=60)
    turn = s.client.say(
        {
            "en": "I need Adol 500 caplets for 3 days, the nearest pharmacy, I can come today.",
            "az": "baddi adol 500 caplets la 3 iyyem, a2rab saydaliyye, fiyye eje lyom.",
            "ar": "بدي أدول 500 كابليت لـ3 أيام، أقرب صيدلية، فيني إجي اليوم.",
        }
    )
    _with_its_form(s, turn, str(adol.id))
    expect.searched(s, [turn], adol, days_of_use=3, pickup_day=s.today)
    if turn.card("reserve") is not None:
        s.client.tap("reserve")
    expect.reserved(s, adol, lasts_days=3, pickup_day=s.today)


def _rx_with_form(s: Stage) -> None:
    concor = s.medicine("concor", "5mg")
    near, second = s.nearest(2)
    s.stock(concor, near, days=120)
    s.stock(concor, second, days=90)
    turn = s.client.say(
        {
            "en": "I need Concor 5 mg tablets for 30 days, the nearest pharmacy, I can come today.",
            "az": "baddi concor 5 mg 7boub la 30 yom, a2rab saydaliyye, fiyye eje lyom.",
            "ar": "بدي كونكور 5 ملغ حبوب لـ30 يوم، أقرب صيدلية، فيني إجي اليوم.",
        }
    )
    _with_its_form(s, turn, str(concor.id))
    expect.searched(s, [turn], concor, days_of_use=30, pickup_day=s.today)
    shown = [card for card in turn.cards if card.kind == "reserve"]
    s.check(
        "prescription_notice_on_the_card",
        bool(shown) and all(card.prescription_notice for card in shown),
        level="component",
        family="output_quality",
        detail=f"cards: {[(card.title, card.prescription_notice) for card in shown]}",
    )
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, concor, lasts_days=30, pickup_day=s.today)


def _form_asked(s: Stage) -> None:
    caplet = s.medicine("adol", "500mg", "caplet")
    suppository = s.medicine("adol", "500mg", "suppository")
    near = s.nearest(1)[0]
    s.stock(caplet, near, days=90)
    s.stock(suppository, near, days=90)
    first = s.client.say(
        {
            "en": "I need Adol 500 for 3 days, the nearest pharmacy, I can come today.",
            "az": "baddi adol 500 la 3 iyyem, a2rab saydaliyye, fiyye eje lyom.",
            "ar": "بدي أدول 500 لـ3 أيام، أقرب صيدلية، فيني إجي اليوم.",
        }
    )
    s.check(
        "looks_the_name_up",
        bool(first.called("search_catalog")),
        level="step",
        family="tool_use",
        detail=f"tools: {first.tool_names()}; reply: {first.reply[:200]!r}",
    )
    s.check(
        "the_catalog_search_finds_it",
        any(str(caplet.id) in used.answer for used in first.called("search_catalog")),
        level="component",
        family="tool_use",
        detail=f"queries: {_name_lookups(first)}",
    )
    forms = [
        str(one)
        for used in first.called("find_options")
        if used.ok
        for one in used.arguments.get("product_ids") or []
    ]
    s.check(
        "never_picks_a_form_itself",
        not ({str(caplet.id), str(suppository.id)} & set(forms)) or len(set(forms)) > 1,
        level="step",
        family="planning",
        detail=f"searched {forms} before the client named a form",
    )
    then = s.client.say(
        {
            "en": "The caplets.",
            "az": "l caplets, l 7boub.",
            "ar": "الكابليت، الحبوب.",
        }
    )
    expect.searched(s, [first, then], caplet, days_of_use=3)
    s.check(
        "never_asks_again_what_was_said",
        bool(then.called("find_options")) and bool(then.cards),
        level="trajectory",
        family="memory",
        detail=f"tools: {then.tool_names()}; cards: {then.kinds}; reply: {then.reply[:200]!r}",
    )
    if then.card("reserve") is not None:
        s.client.tap("reserve")
    expect.reserved(s, caplet, lasts_days=3)
    s.check(
        "never_reserves_the_other_form",
        not [o for o in s.orders() if o["product_id"] == suppository.id],
        level="end_to_end",
        family="safety",
        detail=str([(o["medicine"], o["state"]) for o in s.orders()]),
    )


SCENARIOS = [
    Scenario(
        id="names.otc_with_its_form",
        kind="edge",
        title="'Adol 500 caplets', everything said: a no-prescription name written with its form",
        expected=(
            "The client gave the name, the strength, the form (caplets), 3 days of use, the "
            "nearest pharmacy and today. The agent finds Adol 500 mg caplets in the catalog, "
            "searches at once with no question, and shows reserve cards for that medicine, "
            "the nearest pharmacy recommended. It never takes Panadol or another medicine "
            "for it, never asks for the name again, and the cards carry no prescription "
            "notice. Nothing is reserved until the client taps."
        ),
        play=_otc_with_form,
        prescription="not_needed",
        rules=("R-AG9", "R-S4", "R-C10", "BLD-D53"),
    ),
    Scenario(
        id="names.rx_with_its_form",
        kind="edge",
        title="'Concor 5 mg tablets', everything said: a prescription name written with its form",
        expected=(
            "The client gave the name, the strength, the form (tablets), 30 days of use, the "
            "nearest pharmacy and today. The agent finds Concor 5 mg in the catalog, searches "
            "at once with no question, and shows reserve cards with the prescription notice, "
            "the nearest pharmacy recommended. It never takes Concor AM or another strength "
            "for it. Nothing is reserved until the client taps."
        ),
        play=_rx_with_form,
        prescription="needed",
        rules=("R-AG9", "R-S4", "R-C7", "BLD-D53"),
    ),
    Scenario(
        id="names.form_asked",
        kind="ambiguous",
        title="'Adol 500' comes as caplets and as suppositories: the form is asked, not chosen",
        expected=(
            "Adol 500 mg exists as caplets and as suppositories. The client said everything "
            "except the form. The agent looks the name up and asks only which form (it may "
            "show both), without choosing one itself and without asking again for the days, "
            "the place or the day, which the client gave. After 'the caplets' it searches for "
            "3 days and shows reserve cards for the caplets only."
        ),
        play=_form_asked,
        prescription="both",
        rules=("R-AG9", "BLD-D53"),
    ),
]
