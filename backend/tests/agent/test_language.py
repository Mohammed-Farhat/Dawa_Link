"""Which language a client wrote in, decided by code (the owner's finding, 2026-11-22:
"hello" was answered in Arabizi)."""

import pytest

from dawalink.agent.language import language_of, looks_arabizi


@pytest.mark.parametrize(
    "text",
    [
        "hello",
        "i want panadol",
        "any day i dont mind",
        "hello i need cataflam 50mg, for 3 days. I can pas anyday",
        "what are u tlaking i did not understand?",
        "i need it in Beirut, 7 days",
    ],
)
def test_plain_english_is_english(text: str) -> None:
    assert language_of(text) == "english"


@pytest.mark.parametrize(
    "text",
    [
        "baddi panadol",
        "3ande siyyara",
        "shu fi",
        "Marhaba",
        "ana bel hamra",  # two small words that English also has
        "ma3loum",  # a digit standing for a letter inside a word
        "Marhaba! Kifak? Shou fi bdak mn DawaLink lyom?",
    ],
)
def test_lebanese_arabic_in_latin_letters_is_arabizi(text: str) -> None:
    assert language_of(text) == "arabizi"


def test_arabic_script_is_arabic() -> None:
    assert language_of("بدي بنادول") == "arabic"
    assert language_of("بدي Panadol اليوم") == "arabic"


@pytest.mark.parametrize(
    "text",
    [
        "I need vitamin B12 and D3",  # a digit at the end of a medicine's name
        "omega3 500mg please",
        "3 boxes of 20 tablets",
    ],
)
def test_a_medicines_name_or_a_strength_is_never_read_as_arabizi(text: str) -> None:
    assert language_of(text) == "english"
    assert not looks_arabizi(text)


@pytest.mark.parametrize(
    "text",
    [
        # Found by review: these said "English" and flipped an Arabizi chat to English.
        "panadol",
        "concor 5",
        "Concor 5mg",
        "augmentin 1g",
        "hamra",
        "jbeil",
        "aya nhar",
        "tlet iyyam",
        "3 ayyem",
        "fi panadol?",
        "merci",
        "co2 and 7up",
    ],
)
def test_a_name_a_place_or_a_short_answer_says_nothing(text: str) -> None:
    """English needs evidence: otherwise the language noted earlier stands."""
    assert language_of(text) is None
    assert not looks_arabizi(text)


@pytest.mark.parametrize("text", ["tomorrow", "by car", "yes please", "no thanks", "hello"])
def test_a_short_english_answer_is_english(text: str) -> None:
    assert language_of(text) == "english"


@pytest.mark.parametrize("text", [None, "", "h", "ok", "12", "PANADOL", "?"])
def test_too_little_to_tell_is_left_open(text: str | None) -> None:
    """One or two letters, or a medicine's name alone: the note or English decides."""
    assert language_of(text) is None


def test_another_language_is_left_to_the_model() -> None:
    """D8: the agent answers in the client's own language; code only knows three."""
    assert language_of("bonjour je veux un medicament pour 7 jours") is None


def test_a_reply_is_judged_on_several_words_not_one() -> None:
    quoting = "You wrote 'bukra': I searched for tomorrow and found two pharmacies."
    assert not looks_arabizi(quoting, at_least=3)
    assert looks_arabizi("Marhaba! Kifak? Shou baddak lyom?", at_least=3)
