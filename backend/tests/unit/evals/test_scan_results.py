"""The scan of the saved results for personal data (docs/09 FS-13, FS-18; docs/10 TH-50)."""

from pathlib import Path

from dawalink.evals.scan_results import scan, scan_text

SAVED_ROW = (
    '{"request_id":"14114a17-2630-4642-afae-df2b01054845","price_lbp_shown":76719000,'
    '"output":"{\\"plan_id\\": \\"plan-78016607-1\\", \\"total_lbp\\": 3735000}",'
    '"notes":"Proposed showing other brands (card 07895765).",'
    '"reply":"Hamra Pharmacy has it for 219,046 LBP (about $2.45), 12 min by car."}'
)


def test_ids_prices_and_plain_numbers_are_not_personal() -> None:
    assert scan_text(SAVED_ROW) == []


def test_an_email_a_phone_number_and_coordinates_are_found() -> None:
    found = scan_text(
        'client: "call me on 70 123 456 or write to rami@example.org, I am at 33.8961, 35.4832"'
    )

    assert [(what, text) for what, text, _ in found] == [
        ("an email address", "rami@example.org"),
        ("a phone number", "70 123 456"),
        ("coordinates", "33.8961, 35.4832"),
    ]


def test_a_number_written_inside_a_reply_is_still_found() -> None:
    """A phone number is not hidden by standing in a saved row full of IDs."""
    found = scan_text(SAVED_ROW.replace("12 min by car.", "call 03 123 456."))

    assert [(what, text) for what, text, _ in found] == [("a phone number", "03 123 456")]


def test_every_saved_file_is_read_and_a_finding_names_its_file(tmp_path: Path) -> None:
    clean = tmp_path / "2026-11-15_run" / "turns.jsonl"
    dirty = tmp_path / "2026-11-16_run" / "threads.jsonl"
    for path, text in ((clean, SAVED_ROW), (dirty, '{"text":"my number is +961 70 555 123"}')):
        path.parent.mkdir()
        path.write_text(text + "\n", encoding="utf-8")
    (tmp_path / "2026-11-16_run" / "chart.png").write_bytes(b"\x89PNG")

    read, found = scan(tmp_path)

    assert read == 2
    assert [(one.file, one.what) for one in found] == [(dirty, "a phone number")]
