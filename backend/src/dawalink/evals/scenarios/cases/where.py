"""Where the client is, and where they want to look (docs/04 R-S2, R-RT1, R-AG9; BLD-D14,
BLD-D15, BLD-D54)."""

from collections.abc import Sequence

from sqlalchemy import delete

from dawalink.db.models import TravelTimeCache
from dawalink.evals.scenarios import expect
from dawalink.evals.scenarios.cases.find import (
    answers,
    asks_first,
    at,
    calls,
    chat_area,
    checked_medicine,
    pharmacy_n,
    recommended,
    reserve_cards,
    travel_of,
)
from dawalink.evals.scenarios.scenario import Scenario
from dawalink.evals.scenarios.stage import Card, Stage, Turn


def _area_set(turns: Sequence[Turn]) -> list[dict[str, object]]:
    """The answers of the `set_area` calls that worked."""
    return [answer for answer in answers(turns, "set_area") if answer.get("ok")]


def _notice(s: Stage, shown: Sequence[Card], *, needed: bool) -> None:
    """The cards carry the prescription notice exactly when the medicine has it (R-P1)."""
    if needed:
        s.check(
            "prescription_notice_on_the_card",
            bool(shown) and all(card.prescription_notice for card in shown),
            level="component",
            family="safety",
            detail="a reserve card for a prescription medicine has no notice",
        )
    else:
        s.check(
            "no_prescription_notice_on_the_card",
            bool(shown) and not any(card.prescription_notice for card in shown),
            level="component",
            family="output_quality",
            detail="a card for a no-prescription medicine carries the prescription notice",
        )


def _no_location(s: Stage) -> None:
    concor = checked_medicine(s, "concor", "5mg", notice=True)
    s.forget_home()
    s.client.open_chat(share_location=False)
    s.stock(concor, pharmacy_n(s, 2), days=120)
    s.stock(concor, pharmacy_n(s, 4), days=90)

    first = s.client.say(
        {
            "en": "I need Concor 5 for 30 days, from the nearest pharmacy. I can come today.",
            "az": "baddi concor 5 la 30 yom, mn a2rab saydaliyye. fiyye eje lyom.",
            "ar": "بدي كونكور 5 لـ30 يوم، من أقرب صيدلية. فيني إجي اليوم.",
        }
    )
    asks_first(s, first)
    answer = s.client.say(
        {"en": "I'm in Achrafieh.", "az": "ana bel achrafiye", "ar": "أنا بالأشرفية"}
    )
    turns = [first, answer]
    expect.asked_once(s, turns)
    s.check(
        "sets_the_area_the_client_named",
        chat_area(s) == ("Achrafieh", "Beirut"),
        level="step",
        family="tool_use",
        detail=f"the chat's area: {chat_area(s)}; set_area calls: {calls(turns, 'set_area')}",
    )
    expect.searched(s, [answer], concor, days_of_use=30)
    shown = reserve_cards(turns)
    s.check(
        "shows_cards_once_the_place_is_known",
        bool(reserve_cards([answer])),
        level="trajectory",
        family="planning",
        detail=f"cards: {answer.kinds}; reply: {answer.reply[:160]!r}",
    )
    _notice(s, shown, needed=True)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, concor, lasts_days=30)


def _home_district(s: Stage) -> None:
    otipax = checked_medicine(s, "otipax", notice=False)
    s.client.open_chat(share_location=False)  # the profile's home district only
    home = pharmacy_n(s, 24)  # Tripoli
    s.stock(otipax, home, days=120)
    s.stock(otipax, pharmacy_n(s, 7), days=120)  # Beirut
    s.stock(otipax, pharmacy_n(s, 12), days=120)  # Matn

    turn = s.client.say(
        {
            "en": "I need Otipax for 5 days, from the nearest pharmacy. I can come today.",
            "az": "baddi otipax la 5 iyyem, mn a2rab saydaliyye. fiyye eje lyom.",
            "ar": "بدي أوتيباكس لـ5 أيام، من أقرب صيدلية. فيني إجي اليوم.",
        }
    )
    expect.searches_without_asking(s, turn)
    expect.did_not_call(s, [turn], "set_area", name="no_area_invented")
    expect.searched(s, [turn], otipax, days_of_use=5)
    best = recommended([turn])
    s.check(
        "recommends_a_pharmacy_near_home",
        best is not None and at(best, home),
        level="step",
        family="planning",
        detail=f"recommended: {best.says() if best else None}; the home district is Tripoli",
    )
    shown = reserve_cards([turn])
    _notice(s, shown, needed=False)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, otipax, lasts_days=5, at=[home])


def _named_area(s: Stage) -> None:
    glucophage = checked_medicine(s, "glucophage", "850mg", notice=True)
    here = pharmacy_n(s, 7)  # the nearest to where the phone says the client lives
    jounieh = pharmacy_n(s, 22)  # Keserwan, near Jounieh
    s.stock(glucophage, here, days=120)
    s.stock(glucophage, jounieh, days=120)

    turn = s.client.say(
        {
            "en": "I'm in Jounieh today. I need Glucophage 850 for 30 days, from the nearest "
            "pharmacy. I can come today.",
            "az": "ana lyom b Jounieh. baddi glucophage 850 la 30 yom, mn a2rab saydaliyye. "
            "fiyye eje lyom.",
            "ar": "أنا اليوم في جونيه. بدي غلوكوفاج 850 لـ30 يوم، من أقرب صيدلية. فيني إجي اليوم.",
        }
    )
    expect.searches_without_asking(s, turn)
    s.check(
        "sets_the_area_the_client_is_in",
        chat_area(s) == ("Jounieh", "Keserwan"),
        level="step",
        family="tool_use",
        detail=f"the chat's area: {chat_area(s)}; set_area calls: {calls([turn], 'set_area')}",
    )
    expect.searched(s, [turn], glucophage, days_of_use=30)
    best = recommended([turn])
    s.check(
        "travel_counted_from_the_named_area",
        best is not None and at(best, jounieh),
        level="step",
        family="planning",
        detail=f"recommended: {best.says() if best else None}; nearest to Jounieh is "
        f"{jounieh.name}, nearest to the shared location {here.name}",
    )
    shown = reserve_cards([turn])
    _notice(s, shown, needed=True)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, glucophage, lasts_days=30, at=[jounieh])


def _ambiguous_name(s: Stage) -> None:
    otipax = checked_medicine(s, "otipax", notice=False)
    s.forget_home()
    s.client.open_chat(share_location=False)
    s.stock(otipax, pharmacy_n(s, 15), days=120)  # Baabda
    s.stock(otipax, pharmacy_n(s, 13), days=120)  # Baabda

    first = s.client.say(
        {
            "en": "I'm in Hadath. I need Otipax for 3 days, from the nearest pharmacy. I can "
            "come today.",
            "az": "ana bel Hadath. baddi otipax la 3 iyyem, mn a2rab saydaliyye. fiyye eje lyom.",
            "ar": "أنا بالحدث. بدي أوتيباكس لـ3 أيام، من أقرب صيدلية. فيني إجي اليوم.",
        }
    )
    expect.called(s, [first], "set_area", name="looks_the_place_up")
    s.check(
        "never_chooses_between_two_places",
        chat_area(s) is None and not _area_set([first]),
        level="step",
        family="safety",
        detail=f"the chat's area after the first message: {chat_area(s)}",
    )
    s.check(
        "asks_which_place",
        first.answered and not first.cards and not first.called("find_options"),
        level="trajectory",
        family="planning",
        detail=f"cards: {first.kinds}; reply: {first.reply[:200]!r}",
    )
    expect.did_not_call(s, [first], "find_options", name="no_search_from_a_guessed_place")
    answer = s.client.say(
        {
            "en": "Hadath in Baabda.",
            "az": "el Hadath yalli b Baabda",
            "ar": "الحدث يلي بقضاء بعبدا",
        }
    )
    s.check(
        "sets_the_place_chosen",
        chat_area(s) == ("Hadath", "Baabda"),
        level="step",
        family="tool_use",
        detail=f"the chat's area: {chat_area(s)}; set_area calls: {calls([answer], 'set_area')}",
    )
    expect.searched(s, [answer], otipax, days_of_use=3)
    # The first reply's one question is which Hadath; the answer to it brings no other.
    expect.asked_once(s, [first, answer])
    shown = reserve_cards([answer])
    s.check(
        "shows_cards_after_the_choice",
        bool(shown),
        level="trajectory",
        family="task_success",
        detail=f"cards: {answer.kinds}",
    )
    _notice(s, shown, needed=False)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, otipax, lasts_days=3)


def _unknown_place(s: Stage) -> None:
    finallerg = checked_medicine(s, "finallerg", "10mg", notice=False)
    s.forget_home()
    s.client.open_chat(share_location=False)
    s.stock(finallerg, pharmacy_n(s, 12), days=120)  # Matn
    s.stock(finallerg, pharmacy_n(s, 8), days=120)  # Matn

    first = s.client.say(
        {
            "en": "I'm in Mazraat el Ward. I need Finallerg 10mg for 7 days, from the nearest "
            "pharmacy. I can come today.",
            "az": "ana b mazra3et el ward. baddi finallerg 10mg la 7 iyyem, mn a2rab "
            "saydaliyye. fiyye eje lyom.",
            "ar": "أنا بمزرعة الورد. بدي فينالرج 10 ملغ لـ7 أيام، من أقرب صيدلية. فيني إجي اليوم.",
        }
    )
    expect.called(s, [first], "set_area", name="looks_the_place_up")
    s.check(
        "never_guesses_a_place",
        chat_area(s) is None,
        level="step",
        family="safety",
        detail=f"the chat's area after an unlisted name: {chat_area(s)}",
    )
    s.check(
        "asks_for_a_known_place",
        first.answered and not first.cards and not first.called("find_options"),
        level="trajectory",
        family="planning",
        detail=f"cards: {first.kinds}; reply: {first.reply[:200]!r}",
    )
    answer = s.client.say(
        {
            "en": "I'm close to Sin el Fil.",
            "az": "ana 2rib 3a Sin el Fil",
            "ar": "أنا قريب على سن الفيل",
        }
    )
    s.check(
        "sets_the_known_place",
        chat_area(s) == ("Sin el Fil", "Matn"),
        level="step",
        family="tool_use",
        detail=f"the chat's area: {chat_area(s)}; set_area calls: {calls([answer], 'set_area')}",
    )
    expect.searched(s, [answer], finallerg, days_of_use=7)
    shown = reserve_cards([answer])
    s.check(
        "shows_cards_once_the_place_is_known",
        bool(shown),
        level="trajectory",
        family="task_success",
        detail=f"cards: {answer.kinds}",
    )
    _notice(s, shown, needed=False)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, finallerg, lasts_days=7)


def _areas_to_look_in(s: Stage) -> None:
    duphalac = checked_medicine(s, "duphalac", notice=False)
    beirut, sidon = pharmacy_n(s, 4), pharmacy_n(s, 28)
    near_ones = (pharmacy_n(s, 13), pharmacy_n(s, 18))  # Baabda and Aley: near the client
    for pharmacy in (beirut, sidon, *near_ones):
        s.stock(duphalac, pharmacy, days=120)

    turn = s.client.say(
        {
            "en": "I'm in Aley. I need Duphalac for 5 days, from a pharmacy in Saida or "
            "Beirut. I can come today.",
            "az": "ana b Aley. baddi duphalac la 5 iyyem, mn saydaliyye b Saida aw Beirut. "
            "fiyye eje lyom.",
            "ar": "أنا في عاليه. بدي دوفالاك لـ5 أيام، من صيدلية بصيدا أو بيروت. فيني إجي اليوم.",
        }
    )
    expect.searches_without_asking(s, turn)
    expect.searched(s, [turn], duphalac, days_of_use=5)
    searched_in = [
        set(answer.get("searched_in") or []) for answer in answers([turn], "find_options")
    ]
    s.check(
        "both_areas_searched_together",
        any({"Beirut", "Sidon"} <= districts for districts in searched_in),
        level="step",
        family="tool_use",
        detail=f"districts searched per call: {searched_in}",
    )
    area = chat_area(s)
    s.check(
        "the_client_is_not_moved_to_where_they_look",
        area is None or area[1] == "Aley",
        level="step",
        family="tool_use",
        detail=f"the chat's area became {area}",
    )
    shown = reserve_cards([turn])
    s.check(
        "only_pharmacies_of_the_named_areas",
        bool(shown) and all(at(card, beirut) or at(card, sidon) for card in shown),
        level="step",
        family="task_success",
        detail=f"cards: {[card.title for card in shown]}",
    )
    _notice(s, shown, needed=False)
    # What the search found, when it looked in both areas at once. The agent recommends one
    # and shows up to 2 others (N-45): it need not make a card for each area.
    together = [
        answer
        for answer in answers([turn], "find_options")
        if {"Beirut", "Sidon"} <= set(answer.get("searched_in") or [])
    ]
    found = [option for answer in together for option in answer.get("options") or []]
    names = {(option.get("pharmacy") or {}).get("name") for option in found}
    if together:
        s.check(
            "search_finds_both_areas_boxes",
            {beirut.name, sidon.name} <= names,
            level="component",
            family="tool_use",
            detail=f"pharmacies found: {sorted(str(name) for name in names)}",
        )
    to_beirut = [
        option.get("travel") or {}
        for answer in answers([turn], "find_options")
        for option in answer.get("options") or []
        if (option.get("pharmacy") or {}).get("name") == beirut.name
    ]
    if to_beirut:
        s.check(
            "travel_counted_from_where_the_client_is",
            all((travel.get("car_min") or 0) >= 10 for travel in to_beirut),
            level="component",
            family="task_success",
            detail=f"travel to {beirut.name} in the search's answer: {to_beirut} (from the "
            "client in Aley it is over 20 minutes; from Beirut itself a few)",
        )
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, duphalac, lasts_days=5, at=[beirut, sidon])


def _none_in_the_areas(s: Stage) -> None:
    augmentin = checked_medicine(s, "augmentin", "1g", notice=True)
    s.stock(augmentin, pharmacy_n(s, 6), days=120)  # Beirut
    s.stock(augmentin, pharmacy_n(s, 12), days=120)  # Matn

    first = s.client.say(
        {
            "en": "I need Augmentin 1g for 7 days, from a pharmacy in Tripoli. I can come today.",
            "az": "baddi augmentin 1g la 7 iyyem, mn saydaliyye b Tripoli. fiyye eje lyom.",
            "ar": "بدي أوغمنتين 1 غرام لـ7 أيام، من صيدلية بطرابلس. فيني إجي اليوم.",
        }
    )
    looked = answers([first], "find_options")
    s.check(
        "searches_only_the_named_area",
        any(answer.get("searched_in") == ["Tripoli"] for answer in looked),
        level="step",
        family="tool_use",
        detail=f"districts searched: {[answer.get('searched_in') for answer in looked]}",
    )
    s.check(
        "tool_says_not_in_these_areas_but_elsewhere",
        any(
            answer.get("why_none") == "not_in_these_areas" and (answer.get("elsewhere") or 0) > 0
            for answer in looked
        ),
        level="component",
        family="tool_use",
        detail=str([(answer.get("why_none"), answer.get("elsewhere")) for answer in looked]),
    )
    s.check(
        "no_card_outside_the_named_area",
        not reserve_cards([first]),
        level="step",
        family="task_success",
        detail=f"cards before the client agreed to look elsewhere: {first.kinds}",
    )
    wider = s.client.say(
        {
            "en": "Yes, look anywhere then.",
            "az": "eh, dawwer ween ma kan ya3ne.",
            "ar": "إيه، دوّر وين ما كان يعني.",
        }
    )
    later = calls([wider], "find_options")
    s.check(
        "searches_without_the_area_when_told",
        bool(later) and any(not call.get("areas") for call in later),
        level="trajectory",
        family="planning",
        detail=f"areas of the later searches: {[call.get('areas') for call in later]}",
    )
    shown = reserve_cards([wider])
    s.check(
        "shows_what_exists_elsewhere",
        bool(shown),
        level="step",
        family="task_success",
        detail=f"cards: {wider.kinds}",
    )
    _notice(s, shown, needed=True)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, augmentin, lasts_days=7)


def _anywhere(s: Stage) -> None:
    cipromax = checked_medicine(s, "cipromax", "500mg", notice=True)
    s.stock(cipromax, pharmacy_n(s, 7), days=40)  # the nearest, the dearer box
    s.stock(cipromax, pharmacy_n(s, 22), days=25)  # Keserwan: further, cheaper

    first = s.client.say(
        {"en": "I need Cipromax 500", "az": "baddi cipromax 500", "ar": "بدي سيبروماكس 500"}
    )
    asks_first(s, first)
    answer = s.client.say(
        {
            "en": "Anywhere, I just need it. For 7 days, any day.",
            "az": "ween ma kan, bas baddi yeh. la 7 iyyem, ayya yom.",
            "ar": "وين ما كان، بس بدي ياه. لـ7 أيام، أي يوم.",
        }
    )
    turns = [first, answer]
    expect.asked_once(s, turns)
    expect.searched(s, [answer], cipromax, days_of_use=7)
    searches = calls(turns, "find_options")
    s.check(
        "no_area_filter_for_anywhere",
        bool(searches) and all(not call.get("areas") for call in searches),
        level="step",
        family="tool_use",
        detail=f"areas passed: {[call.get('areas') for call in searches]}",
    )
    expect.did_not_call(s, turns, "set_area", name="anywhere_is_not_a_place")
    shown = reserve_cards([answer])
    s.check(
        "shows_cards_after_the_answer",
        bool(shown),
        level="trajectory",
        family="task_success",
        detail=f"cards: {answer.kinds}",
    )
    _notice(s, shown, needed=True)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, cipromax, lasts_days=7)


def _on_foot(s: Stage) -> None:
    motilium = checked_medicine(s, "motilium", "10mg", notice=True)
    by_car = pharmacy_n(s, 6)  # 4 min by car, 53 on foot from the client
    on_foot = pharmacy_n(s, 1)  # 5 min by car, 38 on foot
    s.stock(motilium, by_car, days=120)
    s.stock(motilium, on_foot, days=120)

    turn = s.client.say(
        {
            "en": "I need Motilium 10 for 10 days, today. I don't have a car, so a pharmacy "
            "I can walk to.",
            "az": "baddi motilium 10 la 10 iyyem, lyom. ma 3ande siyyara, fa baddi saydaliyye "
            "fiyye rou7 la 3enda mashe.",
            "ar": "بدي موتيليوم 10 لـ10 أيام، اليوم. ما عندي سيارة، فبدي صيدلية فيني روح "
            "لعندا مشي.",
        }
    )
    expect.searches_without_asking(s, turn)
    expect.searched(s, [turn], motilium, days_of_use=10)
    best = recommended([turn])
    s.check(
        "recommends_the_nearest_on_foot",
        best is not None and at(best, on_foot),
        level="step",
        family="planning",
        detail=f"recommended: {best.says() if best else None}; nearest on foot is "
        f"{on_foot.name}, nearest by car {by_car.name}",
    )
    s.check(
        "remembers_the_client_walks",
        s.case_state(turn.conversation).get("preference") == "walkable",
        level="step",
        family="memory",
        detail=f"preference in the notes: {s.case_state(turn.conversation).get('preference')}",
    )
    shown = reserve_cards([turn])
    _notice(s, shown, needed=True)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, motilium, lasts_days=10)


def _routing_down(s: Stage) -> None:
    crestor = checked_medicine(s, "crestor", "20mg", notice=True)
    with s.setup() as session:  # no road time is known: the routing service must be asked
        session.execute(delete(TravelTimeCache))
    s.stock(crestor, pharmacy_n(s, 7), days=120)
    s.stock(crestor, pharmacy_n(s, 6), days=90)

    turn = s.client.say(
        {
            "en": "I need Crestor 20 for 30 days, from the nearest pharmacy. I can come today.",
            "az": "baddi crestor 20 la 30 yom, mn a2rab saydaliyye. fiyye eje lyom.",
            "ar": "بدي كريستور 20 لـ30 يوم، من أقرب صيدلية. فيني إجي اليوم.",
        }
    )
    expect.searches_without_asking(s, turn)
    expect.searched(s, [turn], crestor, days_of_use=30)
    shown = reserve_cards([turn])
    s.check(
        "search_works_without_the_routing_service",
        bool(shown),
        level="end_to_end",
        family="reliability",
        detail=f"cards: {turn.kinds}; reply: {turn.reply[:160]!r}",
    )
    s.check(
        "times_are_straight_line_estimates",
        bool(shown) and all(travel_of(card).get("source") == "straight" for card in shown),
        level="component",
        family="reliability",
        detail=f"travel on the cards: {[travel_of(card) for card in shown]}",
    )
    _notice(s, shown, needed=True)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, crestor, lasts_days=30)


def _look_in_a_town(s: Stage) -> None:
    motilium = checked_medicine(s, "motilium", "10mg", notice=True)
    beirut_a, beirut_b = pharmacy_n(s, 4), pharmacy_n(s, 2)  # 12 and 14 min by car
    matn = pharmacy_n(s, 12)  # the nearest to the client (9 min), in Matn
    baabda = pharmacy_n(s, 15)  # 13 min, in Baabda
    for pharmacy in (beirut_a, beirut_b, matn, baabda):
        s.stock(motilium, pharmacy, days=120)

    turn = s.client.say(
        {
            "en": "I need Motilium 10 for 10 days, from a pharmacy in Achrafieh. I can come today.",
            "az": "baddi motilium 10 la 10 iyyem, mn saydaliyye bel achrafiye. fiyye eje lyom.",
            "ar": "بدي موتيليوم 10 لـ10 أيام، من صيدلية بالأشرفية. فيني إجي اليوم.",
        }
    )
    expect.searches_without_asking(s, turn)
    expect.searched(s, [turn], motilium, days_of_use=10)
    looked = answers([turn], "find_options")
    s.check(
        "a_town_to_look_in_counts_as_its_district",
        any(answer.get("searched_in") == ["Beirut"] for answer in looked),
        level="step",
        family="tool_use",
        detail=f"districts searched: {[answer.get('searched_in') for answer in looked]}",
    )
    s.check(
        "the_client_is_not_moved_to_where_they_look",
        chat_area(s) is None,
        level="step",
        family="tool_use",
        detail=f"the chat's area became {chat_area(s)}; set_area calls: "
        f"{calls([turn], 'set_area')}",
    )
    shown = reserve_cards([turn])
    s.check(
        "only_pharmacies_of_the_area_named",
        bool(shown) and all(at(card, beirut_a) or at(card, beirut_b) for card in shown),
        level="step",
        family="task_success",
        detail=f"cards: {[card.title for card in shown]}; {matn.name} and {baabda.name} "
        "are nearer but outside Beirut",
    )
    to_beirut = [
        option.get("travel") or {}
        for answer in looked
        for option in answer.get("options") or []
        if (option.get("pharmacy") or {}).get("name") in (beirut_a.name, beirut_b.name)
    ]
    if to_beirut:
        s.check(
            "travel_counted_from_where_the_client_is",
            all((travel.get("car_min") or 0) >= 8 for travel in to_beirut),
            level="component",
            family="task_success",
            detail=f"travel to the Beirut pharmacies in the search's answer: {to_beirut} "
            "(from the client in Matn 12 to 14 minutes; from Achrafieh itself about 4)",
        )
    _notice(s, shown, needed=True)
    if shown:
        s.client.tap("reserve")
    expect.reserved(s, motilium, lasts_days=10, at=[beirut_a, beirut_b])


SCENARIOS = [
    Scenario(
        id="where.no_location",
        kind="ambiguous",
        title="No location shared and none in the profile",
        expected=(
            "The agent knows no place at all for the client. In ONE message it asks where "
            "they are (an area or town, or to tap 'Use my location'), together with anything "
            "else it wasn't told; it shows no card and searches nothing it can't place. When "
            "the client says Achrafieh, it sets that area, says the times are counted from "
            "Achrafieh and are estimates ('about'), and searches at once with 30 days of use, "
            "today. It never asks a second round of questions. The cards carry the "
            "prescription notice; nothing is reserved before the tap. It never asks for a "
            "street address."
        ),
        play=_no_location,
        prescription="needed",
        rules=("R-AG9", "R-S2", "INV-24", "BLD-D14", "BLD-D53"),
        facts=("You are in Achrafieh, in Beirut. You did not share your location.",),
    ),
    Scenario(
        id="where.home_district",
        kind="normal",
        title="Nothing shared; the profile's home district is known",
        expected=(
            "The client shared no location, but their profile says they live in Tripoli: "
            "that is a known location. They said everything else, so the agent searches at "
            "once around their home, without asking where they are, and says the times are "
            "counted from their home area. It recommends a pharmacy in Tripoli with a short "
            "reason, never one in Beirut or Matn. The card has no prescription notice; "
            "nothing is reserved before the tap."
        ),
        play=_home_district,
        prescription="not_needed",
        rules=("R-AG9", "R-S2", "BLD-D28", "BLD-D40"),
        client_district="Tripoli",
    ),
    Scenario(
        id="where.named_area",
        kind="normal",
        title="'I'm in Jounieh today': travel is counted from the area named",
        expected=(
            "The phone's location is in Beirut, but the client says they are in Jounieh "
            "today. The agent sets Jounieh as where the client is (the place named last "
            "replaces the earlier one) and counts the travel from there: it recommends the "
            "pharmacy near Jounieh, not the one near the client's home in Beirut, says the "
            "times are counted from Jounieh, and calls them 'about'. It searches at once (the "
            "client said everything). The cards carry the prescription notice."
        ),
        play=_named_area,
        prescription="needed",
        rules=("R-S2", "R-RT1", "INV-24", "BLD-D14"),
    ),
    Scenario(
        id="where.ambiguous_name",
        kind="ambiguous",
        title="'I'm in Hadath': two places of that name, in Baabda and in Baalbek",
        expected=(
            "Hadath is a place in Baabda and a place in Baalbek. The agent never chooses: it "
            "asks which one, naming both districts and offering each as a quick reply, and "
            "searches nothing and shows no card until the client says. When the client says "
            "Hadath in Baabda, it sets that place and searches at once with what the client "
            "already said (3 days, nearest, today), without asking anything again, and "
            "shows reserve cards with no prescription notice."
        ),
        play=_ambiguous_name,
        prescription="not_needed",
        rules=("R-S2", "BLD-D15", "FA-32"),
        facts=("You are in Hadath, in Baabda district. You didn't share your location.",),
    ),
    Scenario(
        id="where.unknown_place",
        kind="edge",
        title="A place name that is on no list",
        expected=(
            "'Mazraat el Ward' is not in DawaLink's list of places, and no listed name is "
            "clearly the same place. The agent never takes a look-alike name in its place: it "
            "says it couldn't find that place and asks for a better-known area or town nearby, "
            "or to tap 'Use my location'. It shows no card. When the client says they are "
            "near Sin el Fil, it sets that area and searches at once with what was already "
            "said (7 days, nearest, today), without a new round of questions."
        ),
        play=_unknown_place,
        prescription="not_needed",
        rules=("R-S2", "BLD-D14", "FA-31"),
        facts=(
            "You live in a small place called Mazraat el Ward. It may be on no list.",
            "The nearest well-known place is Sin el Fil, in Matn.",
        ),
    ),
    Scenario(
        id="where.areas_to_look_in",
        kind="past_failure",
        title="'I'm in Aley; I need it from Saida or Beirut'",
        expected=(
            "Where the client is (Aley) and where they want to look (Saida or Beirut) are two "
            "things. The agent searches the pharmacies of Saida and Beirut together, in one "
            "search, and only those: the pharmacies near Aley that have the medicine are not "
            "offered. Travel times are counted from Aley, never from Saida or Beirut. It says "
            "which areas it searched, recommends one pharmacy of them with a short reason and "
            "may show the other as an alternative, each with its card. No prescription "
            "notice."
        ),
        play=_areas_to_look_in,
        prescription="not_needed",
        rules=("R-S2", "N-58", "BLD-D54", "FA-51"),
        client_district="Aley",
    ),
    Scenario(
        id="where.none_in_the_areas",
        kind="past_failure",
        title="Nothing in the area named, but the medicine exists elsewhere",
        expected=(
            "The client wants the medicine from Tripoli. The agent searches only Tripoli; no "
            "pharmacy there has it. It says plainly that there is none in Tripoli and that it "
            "exists elsewhere, and may offer to look there; it shows no card from outside "
            "Tripoli before the client agrees, and never says 'try another day' (the day is "
            "not the reason). When the client says to look anywhere, it searches without the "
            "area and shows reserve cards with the prescription notice."
        ),
        play=_none_in_the_areas,
        prescription="needed",
        rules=("R-S2", "BLD-D54", "BLD-D55", "FA-50", "FA-51"),
    ),
    Scenario(
        id="where.anywhere",
        kind="ambiguous",
        title="'Anywhere, I just need it'",
        expected=(
            "The first reply asks once where, for how many days and when. The client says "
            "anywhere, 7 days, any day. 'Anywhere' is no area filter and no place: the agent "
            "searches at once around where the client is, with no areas, and may weigh price "
            "and expiry more than distance. It says what it took as given, shows reserve "
            "cards with the prescription notice and recommends one with a short reason. It "
            "never asks again."
        ),
        play=_anywhere,
        prescription="needed",
        rules=("R-AG9", "R-S2", "BLD-D53"),
        facts=("You need Cipromax 500, one box.", "Anywhere is fine, 7 days, any day."),
    ),
    Scenario(
        id="where.on_foot",
        kind="normal",
        title="A client who walks: planned on foot, never asked car or on foot",
        expected=(
            "The client said everything and that they walk. The agent never asks car or on "
            "foot. It plans on foot: it recommends the pharmacy that is nearest on foot (38 "
            "minutes' walk) rather than the one that is nearest by car (53 minutes' walk), "
            "gives the walking time, and remembers that the client walks. The cards carry the "
            "prescription notice; nothing is reserved before the tap."
        ),
        play=_on_foot,
        prescription="needed",
        rules=("R-AG9", "R-S3", "BLD-D53"),
    ),
    Scenario(
        id="where.routing_down",
        kind="tool_failure",
        title="The routing service doesn't answer",
        expected=(
            "No road time is known and the routing service fails. The search still works: "
            "the agent searches at once (the client said everything), shows reserve cards "
            "whose travel times are straight-line estimates, and calls them 'about'. It "
            "recommends one pharmacy with a short reason, and the cards carry the "
            "prescription notice. The client can reserve with a tap."
        ),
        play=_routing_down,
        prescription="needed",
        rules=("R-RT1", "N-50", "N-51", "R-AG9"),
        routing="down",
    ),
    Scenario(
        id="where.look_in_a_town",
        kind="edge",
        title="'From a pharmacy in Achrafieh' said by a client in Matn: the town counts as Beirut",
        expected=(
            "The client is in Matn (their phone's location) and wants the pharmacy in "
            "Achrafieh. That is where to look, not where they are, so the agent does not move "
            "the client there. A town named to look in counts as its district: the agent "
            "searches Beirut's pharmacies only, at once (the client said everything: 10 "
            "days, today), with travel times counted from where the client is in Matn. The "
            "nearer pharmacies in Matn and Baabda are not offered. It recommends one Beirut "
            "pharmacy with a short reason; the cards carry the prescription notice; nothing "
            "is reserved before the tap."
        ),
        play=_look_in_a_town,
        prescription="needed",
        rules=("R-S2", "N-58", "BLD-D54", "INV-24"),
        client_district="Matn",
    ),
]
