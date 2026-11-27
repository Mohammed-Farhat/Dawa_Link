import json

import pytest

from dawalink.agent.guards.grounding import pharmacy_contact_errors


def contact_counts(new: int, existing: int) -> str:
    return json.dumps({"asked": new + existing, "newly_asked": new, "already_asked": existing})


@pytest.mark.parametrize(
    "text",
    [
        "I asked 3 more pharmacies to release stock.",
        "I've contacted three additional pharmacies.",
        "Three new pharmacies were notified.",
        "I contacted another pharmacy.",
        "I asked the pharmacies again.",
        "I contacted them again.",
        "تواصلت مع ٣ صيدليات إضافية",
        "سألت الصيدليات مرة ثانية",
        "sa2alt 3 saydaliyyet zyede",
    ],
)
def test_reused_requests_do_not_support_claims_of_new_contacts(text: str) -> None:
    assert pharmacy_contact_errors(text, [contact_counts(0, 3)])
    assert pharmacy_contact_errors(text, [])


@pytest.mark.parametrize(
    "text",
    [
        "The same 3 pharmacies have already been asked.",
        "No additional pharmacies were contacted.",
        "I have not contacted any more pharmacies.",
        "I can ask more pharmacies later.",
        "Have you contacted more pharmacies?",
        "هل تواصلت مع صيدليات إضافية؟",
        "لم أتواصل مع صيدليات إضافية",
        "ما سألت صيدليات جديدة",
    ],
)
def test_existing_contacts_negations_and_future_possibilities_are_not_new_claims(text: str) -> None:
    assert not pharmacy_contact_errors(text, [contact_counts(0, 3)])


def test_new_contact_count_excludes_replays_and_cannot_be_inflated() -> None:
    answers = [contact_counts(3, 0), contact_counts(0, 3)]
    assert not pharmacy_contact_errors("I asked three more pharmacies.", answers)
    assert pharmacy_contact_errors("I asked six more pharmacies.", answers)
    assert pharmacy_contact_errors("I asked 3 more pharmacies.", [contact_counts(1, 0)])


def test_missing_or_invalid_contact_counts_cannot_prove_a_new_contact() -> None:
    for answer in ("invalid JSON", "[]", '{"asked": 3}', contact_counts(-1, 4)):
        assert pharmacy_contact_errors("I contacted more pharmacies.", [answer])
