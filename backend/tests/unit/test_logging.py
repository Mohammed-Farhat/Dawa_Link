"""Logs are JSON lines, including what libraries such as uvicorn write (docs/02 §1)."""

import json
import logging

import pytest
import structlog

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
