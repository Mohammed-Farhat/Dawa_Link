"""The command that makes an admin (A#20): its authenticator key reaches a person, not a log.

These tests never reach a database: the address is one nobody answers, so a test that got
past the checks would fail on connecting, not create an admin anywhere.
"""

import io

import pytest
from sqlalchemy.exc import OperationalError

from dawalink.ops import create_admin
from tests.conftest import UNREACHABLE_DATABASE

ARGS = ["--email", "admin@example.org", "--name", "Test Admin"]


class Console(io.StringIO):
    """A stream that says whether it is a terminal."""

    def __init__(self, terminal: bool) -> None:
        super().__init__()
        self.terminal = terminal

    def isatty(self) -> bool:
        return self.terminal


@pytest.fixture
def nowhere(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE)
    monkeypatch.setenv("WEBSITE_URL", "http://localhost:5173")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_SECRET_KEY", "a-test-only-secret-key")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return monkeypatch


def test_without_a_terminal_it_refuses_before_anything_else(nowhere: pytest.MonkeyPatch) -> None:
    nowhere.setattr("sys.stdout", Console(terminal=False))
    nowhere.setenv("ADMIN_PASSWORD", "A long test password, 1")

    with pytest.raises(SystemExit) as stopped:
        create_admin.main(ARGS)

    assert stopped.value.code == create_admin.NO_TERMINAL_FOR_THE_KEY
    assert "--print-key-without-terminal" in str(stopped.value.code)


def test_the_flag_says_the_log_is_wanted(nowhere: pytest.MonkeyPatch) -> None:
    """With the flag it goes on, here as far as the database nobody answers."""
    nowhere.setattr("sys.stdout", Console(terminal=False))
    nowhere.setenv("ADMIN_PASSWORD", "A long test password, 1")

    with pytest.raises(OperationalError):
        create_admin.main([*ARGS, "--print-key-without-terminal"])


def test_a_terminal_needs_no_flag(nowhere: pytest.MonkeyPatch) -> None:
    nowhere.setattr("sys.stdout", Console(terminal=True))
    nowhere.setenv("ADMIN_PASSWORD", "A long test password, 1")

    with pytest.raises(OperationalError):
        create_admin.main(ARGS)


def test_without_a_terminal_to_type_in_the_password_comes_from_the_setting(
    nowhere: pytest.MonkeyPatch,
) -> None:
    """getpass would read a line from nowhere: it is refused before the database."""
    nowhere.setattr("sys.stdout", Console(terminal=True))
    nowhere.setattr("sys.stdin", Console(terminal=False))

    with pytest.raises(SystemExit) as stopped:
        create_admin.main(ARGS)

    assert stopped.value.code == create_admin.NO_TERMINAL_FOR_THE_PASSWORD
