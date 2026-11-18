"""The check that a reply invents no price and no pharmacy (docs/09 FA-9)."""

from dawalink.evals.grounding import invented, names_a_price_or_a_pharmacy

ANSWER = (
    '{"ok": true, "options": [{"pharmacy": "Hamra Pharmacy", "area": "Hamra", '
    '"price": "600,000 LBP (about $6.70)", "public_price": "1,000,000 LBP", "car_min": 12}]}'
)


def test_what_a_tool_said_is_not_invented() -> None:
    reply = (
        "Hamra Pharmacy has it for 600,000 LBP (about $6.70) instead of 1,000,000 LBP, "
        "12 minutes by car."
    )

    assert names_a_price_or_a_pharmacy(reply)
    assert invented(reply, [ANSWER]) == []


def test_a_price_no_tool_gave_is_found() -> None:
    reply = "Hamra Pharmacy has it for 450,000 LBP, or about $5."

    assert invented(reply, [ANSWER]) == ["450,000 LBP", "$5"]


def test_a_pharmacy_no_tool_named_is_found() -> None:
    reply = "Verdun Pharmacy also has it for 600,000 LBP. Pharmacie du Cedre is closed."

    assert invented(reply, [ANSWER]) == ["Verdun Pharmacy", "Pharmacie du Cedre"]


def test_the_words_of_the_sentence_before_a_name_are_not_part_of_it() -> None:
    """In Arabizi the word before the name is often capitalised: "Ou Hamra Pharmacy"."""
    reply = "Nensa7 Hamra Pharmacy: 12 da2i2 bel siyyara. Ou Hamra Pharmacy btsakker 21:00."

    assert invented(reply, [ANSWER]) == []


def test_a_clock_time_before_a_price_is_not_part_of_the_price() -> None:
    assert invented("It is open until 17:00, 600,000 LBP.", [ANSWER]) == []


def test_the_clients_own_budget_is_theirs() -> None:
    reply = "No box within your 500,000 LBP budget. The lowest is 600,000 LBP."

    assert invented(reply, [ANSWER], client_said=["baddi concor, ma3e 500,000 LBP"]) == []
    assert invented(reply, [ANSWER]) == ["500,000 LBP"]


def test_the_same_number_written_another_way_is_the_same_number() -> None:
    assert invented("It costs 600000 LBP.", [ANSWER]) == []
    assert invented("It costs 600.000 LBP.", [ANSWER]) == []


def test_words_about_pharmacies_in_general_are_not_names() -> None:
    reply = "Ask the pharmacist at the pharmacy. Which pharmacy do you prefer? No price yet."

    assert not names_a_price_or_a_pharmacy(reply)
    assert invented(reply, []) == []


def test_a_name_in_arabic_script() -> None:
    answer = '{"pharmacy": "صيدلية الحمرا", "price": "600,000 LBP"}'

    assert invented("صيدلية الحمرا عندها الدواء بـ 600,000 ليرة", [answer]) == []
    assert invented("صيدلية الأمل عندها الدواء", [answer]) == ["صيدلية الأمل"]
    # "A suitable pharmacy", "the nearest pharmacy": no name.
    assert invented("لأبحث لك عن صيدلية مناسبة أو صيدلية الأقرب", [answer]) == []


def test_arabic_digits_are_the_same_numbers() -> None:
    """A reply in Arabic writes the tool's price with its own digits."""
    reply = "السعر " + "٦٠٠,٠٠٠" + " ل.ل. (حوالي " + "٦.٧٠" + " دولار)"  # noqa: RUF001

    assert names_a_price_or_a_pharmacy(reply)
    assert invented(reply, [ANSWER]) == []
    assert invented(reply.replace("٦٠٠", "٤٥٠"), [ANSWER]) != []


def test_the_pharmacy_as_a_word_is_no_name() -> None:
    assert invented("The Pharmacy closes at five. This Pharmacy is the nearest.", [ANSWER]) == []
