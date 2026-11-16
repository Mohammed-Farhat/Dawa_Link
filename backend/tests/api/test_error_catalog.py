"""The error catalog of docs/06 §3.2 and the code agree on every HTTP status, and a few
things the answers are written with (docs/06 §1, docs/11 §8)."""

import re
from datetime import UTC, datetime
from pathlib import Path

from dawalink.api.errors import HTTP_STATUS, ErrorCode, service_status
from dawalink.api.present import clock_words
from dawalink.ops.seed_demo import set_demo_passwords
from dawalink.services import auth
from dawalink.services.errors import Code
from tests.api.conftest import Api

API_DOC = Path(__file__).parents[3] / "docs" / "06_api.md"
ROW = re.compile(r"^\| (`[A-Z_]+`(?: / `[A-Z_]+`)*) \| (\d{3}) \|", re.MULTILINE)


def documented() -> dict[str, int]:
    """`{code: HTTP status}` from the catalog table of the API document."""
    found: dict[str, int] = {}
    for names, status in ROW.findall(API_DOC.read_text(encoding="utf-8")):
        for name in re.findall(r"[A-Z_]+", names):
            found[name] = int(status)
    return found


def test_every_documented_code_answers_with_its_documented_status() -> None:
    in_code = {code.value: status for code, status in HTTP_STATUS.items()} | {
        code.value: service_status(code) for code in Code
    }

    wrong = {
        name: (status, in_code.get(name))
        for name, status in documented().items()
        if in_code.get(name) != status
    }

    assert wrong == {}


def test_every_code_the_services_refuse_with_is_documented() -> None:
    known = set(documented())

    missing = sorted(code.value for code in [*Code, *ErrorCode] if code.value not in known)

    assert missing == []


def test_a_deadline_at_midnight_is_the_end_of_that_day() -> None:
    now = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)  # 10:00 in Beirut

    assert clock_words(datetime(2026, 11, 16, 19, 0, tzinfo=UTC), now) == "today 21:00"
    # 22:00 UTC is 00:00 of the 17th in Beirut: the pharmacy closes at midnight today.
    assert clock_words(datetime(2026, 11, 16, 22, 0, tzinfo=UTC), now) == "today 24:00"
    assert clock_words(datetime(2026, 11, 17, 19, 0, tzinfo=UTC), now) == "tomorrow 21:00"
    assert clock_words(datetime(2026, 11, 20, 19, 0, tzinfo=UTC), now) == "Fri 20 Nov 21:00"


def test_the_demo_accounts_get_their_password_from_the_settings(api: Api) -> None:
    demo = api.world.make.client(
        person={"email": "client01@demo.dawalink.test", "password_hash": "!"}
    )
    other = api.world.make.client(person={"email": "someone@example.com", "password_hash": "!"})

    with api.world.as_owner():
        changed = set_demo_passwords(api.world.connection, "a demo password of ours")

    assert changed == 1
    hashes = dict(api.world.all("SELECT id, password_hash FROM users"))
    assert auth._password_matches(hashes[demo], "a demo password of ours")
    assert hashes[other] == "!"
