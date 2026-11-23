"""What the reply guard lets through and what it stops, for the owner's findings of
2026-11-22 (docs/07 §7.2). Pure rules: no database.

- A plain search answer was replaced by "I can't advise on medicines or doses".
- A reply announced a hand-over that had failed.
"""

import pytest

from dawalink.agent.guards.clinical import clinical_reasons, without_names
from dawalink.agent.guards.output import _DOES_WHAT_THE_CARD_DOES, _SAYS_A_PERSON_HAS_IT


class TestLogisticsIsNotAdvice:
    @pytest.mark.parametrize(
        "text",
        [
            # Asking about the days of use, next to a product's strength.
            "For how many days will you take it? I found Zentrol 500 mg in 24 tablets.",
            "How many days do you take it? It is 500 mg, 20 tablets.",
            "You take it for 7 days, so this box lasts.",
            "Tell me the days you'll take it for. The 250 mg box holds 30 tablets.",
            # What a box holds and how long it lasts.
            "The box holds 24 tablets and lasts your 7 days.",
            "Zentrol 500 mg, 20 tablets, is at one pharmacy, open daily until 21:00.",
        ],
    )
    def test_a_question_or_a_fact_about_the_days_of_use_passes(self, text: str) -> None:
        assert clinical_reasons(text) == []

    @pytest.mark.parametrize(
        "text",
        [
            "Take it twice a day with food.",
            "Take 2 tablets every 8 hours.",
            "You should take 500 mg twice a day.",
            "Try it with food.",
            "khod 7abbten bil nhar",
            "It is safe to take during pregnancy.",
            "It is good for headache.",
            # Found by review on 2026-11-23: a first loosening let all of these through.
            "You take it with food.",
            "It's best to take it after meals.",
            "Try to take it on an empty stomach.",
            "Remember to take it after eating.",
            "Better to take it with meals.",
            "It is fine if you take it with food.",
            "You'll take 500 mg with food.",
            "We take it twice a day usually.",
            "Take 2 Zentrol 500mg now.",
            "Take two Zentrol 500 mg.",
            "It's fine for diabetics.",
            "It's okay for your stomach.",
            "Zentrol is fine for headaches.",
            "it's fine for your blood pressure",
            "Zentrol is fine for a 5 year old.",
            "That's ok for breastfeeding mothers.",
            "You take it for 7 days, twice a day.",
        ],
    )
    def test_real_advice_is_still_caught(self, text: str) -> None:
        assert clinical_reasons(text) != []

    @pytest.mark.parametrize(
        "text",
        [
            # Seen on 2026-11-23, on the real model: the assistant's own questions were
            # stopped, because it said that an open answer "is fine".
            '"Any" or "I don\'t know" is fine for the last two.',
            "Any day is fine for the pickup.",
            "Is tomorrow fine for you?",
            "Is that ok with you?",
            "Tuesday is fine with the pharmacy.",
        ],
    )
    def test_fine_and_ok_are_also_plain_words(self, text: str) -> None:
        assert clinical_reasons(text) == []

    @pytest.mark.parametrize(
        "text",
        [
            "It is fine to take it with the other one.",
            "It is ok with Zentrol.",
            "That is okay for children.",
            "It is safe to take during pregnancy.",
        ],
    )
    def test_a_claim_that_something_is_fine_to_take_is_still_caught(self, text: str) -> None:
        assert "safety_claim" in clinical_reasons(text)

    def test_a_product_named_with_dosing_shorthand_is_not_a_dose(self) -> None:
        """The Ministry writes some names with "BID" or "TID": with the strength beside
        it, the name read as "a dose with how often"."""
        text = "I found ZENTROL BID 1g and ZENTROL 156 mg. Which one is on your box?"
        assert clinical_reasons(text) != []  # the bare rule would stop it
        assert clinical_reasons(without_names(text, ["ZENTROL BID", "ZENTROL"])) == []

    def test_taking_the_names_out_never_hides_advice(self) -> None:
        text = "Take ZENTROL BID 1g twice a day."
        assert clinical_reasons(without_names(text, ["ZENTROL BID"])) != []

    def test_short_names_are_left_alone(self) -> None:
        """A two-letter "name" would take words apart."""
        assert without_names("Take it twice a day", ["it", ""]) == "Take it twice a day"


class TestSayingAPersonHasTheCase:
    @pytest.mark.parametrize(
        "text",
        [
            "I've passed your request to a person from DawaLink.",
            "I have sent this to the DawaLink team.",
            "I've told a person from DawaLink again.",
            "A person from DawaLink has been notified and will reply here.",
            "The DawaLink team has been told you want a person.",
            "Your request is with a person from DawaLink.",
            "I've passed this to a DawaLink person, who can help send it.",
            "A person from DawaLink was told at 10:30 and will reply in this chat.",
        ],
    )
    def test_it_is_recognised(self, text: str) -> None:
        assert _SAYS_A_PERSON_HAS_IT.search(text)

    @pytest.mark.parametrize(
        "text",
        [
            "I can pass this to a person from DawaLink if you want.",
            "Do you want to talk to a person?",
            "Only a person at the pharmacy can tell you that.",
            "I asked 2 pharmacies; they answer by 11:40.",
            # Found by review: the honest report of an ask to pharmacies was refused.
            "I've sent your request to 2 open pharmacies; if someone releases a box, you'll "
            "get an offer here.",
            "I sent the ask to 3 pharmacies, and DawaLink will tell you when one answers.",
            "I've told the pharmacies; someone will answer within 2 hours.",
            "As I told you, DawaLink only shows boxes that last your days.",
            "I've sent the card above; DawaLink holds it until 21:00.",
        ],
    )
    def test_an_offer_or_another_sentence_is_not(self, text: str) -> None:
        assert not _SAYS_A_PERSON_HAS_IT.search(text)


class TestAChipThatDoesWhatTheCardDoes:
    @pytest.mark.parametrize("chip", ["Reserve it", "Yes, reserve it for tomorrow", "E7jezo"])
    def test_reserving_is_the_cards_button(self, chip: str) -> None:
        assert _DOES_WHAT_THE_CARD_DOES.search(chip)

    @pytest.mark.parametrize(
        "chip", ["Show me other options", "No thanks", "Tomorrow", "24 tablets"]
    )
    def test_an_answer_is_kept(self, chip: str) -> None:
        assert not _DOES_WHAT_THE_CARD_DOES.search(chip)
