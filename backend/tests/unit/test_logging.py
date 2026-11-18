"""Logs are JSON lines, including what libraries such as uvicorn write (docs/02 §1)."""

import json
import logging

import pytest
import structlog
from pydantic import BaseModel, ValidationError

from dawalink.observability.logging import configure_logging


def test_our_logs_and_library_logs_are_json_lines(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    with structlog.contextvars.bound_contextvars(request_id="abc123"):
        structlog.get_logger("test").info("reserved", units=2)
    logging.getLogger("uvicorn.error").info("Uvicorn running")

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert lines[0]["event"] == "reserved"
    assert lines[0]["units"] == 2
    assert lines[0]["request_id"] == "abc123"
    assert lines[0]["level"] == "info"
    assert lines[0]["timestamp"].endswith("Z")
    assert lines[1]["event"] == "Uvicorn running"


def test_configuring_twice_does_not_duplicate_lines(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    configure_logging("INFO")
    structlog.get_logger("test").info("once")

    assert len(capsys.readouterr().out.splitlines()) == 1


def test_an_ordinary_error_is_logged_with_its_message_and_where_it_happened(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")

    def stock_the_shelf() -> None:
        raise RuntimeError("the shelf is full")

    try:
        try:
            stock_the_shelf()
        except RuntimeError as first:
            raise KeyError("shelf") from first
    except KeyError:
        structlog.get_logger("test").exception("task_failed")

    (line,) = [json.loads(row) for row in capsys.readouterr().out.splitlines()]

    assert line["event"] == "task_failed"
    assert "RuntimeError: the shelf is full" in line["exception"]
    assert "stock_the_shelf" in line["exception"]
    # The cause comes first, then what it led to.
    assert line["exception"].index("RuntimeError") < line["exception"].index("KeyError")


def test_an_error_that_repeats_what_it_was_given_is_logged_by_its_kind_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """docs/09 FS-13: a schema's error quotes the value it refused."""
    configure_logging("INFO")

    class Contact(BaseModel):
        phone: int

    sent = {"phone": "someone" + "@example.com"}
    try:
        Contact.model_validate(sent)
    except ValidationError:
        structlog.get_logger("test").exception("task_failed")
    logging.getLogger("a.library").error("it failed", exc_info=ValueError("plain"))

    ours, theirs = [json.loads(row) for row in capsys.readouterr().out.splitlines()]

    assert "someone@example.com" not in json.dumps(ours)
    assert "ValidationError" in ours["exception"]
    assert "ValueError: plain" in theirs["exception"]
