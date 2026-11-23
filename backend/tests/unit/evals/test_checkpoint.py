import json
from pathlib import Path

import pytest

from dawalink.evals.checkpoint import save_case, stop_requested


def test_incremental_outcomes_keep_failures_and_do_not_replace_prior_rows(tmp_path: Path) -> None:
    folder = tmp_path / "unique-run"
    good = {"id": "U-1", "outcome": "ok"}
    bad = {"id": "U-2", "outcome": "guardrail_blocked"}
    save_case(folder, good)
    save_case(folder, bad)
    assert [
        json.loads(s) for s in (folder / "case-checkpoints.jsonl").read_text().splitlines()
    ] == [good, bad]


def test_case_boundary_stop_is_explicit_not_a_stale_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EVAL_STOP_FILE", raising=False)
    assert not stop_requested()
    marker = tmp_path / "STOP"
    monkeypatch.setenv("EVAL_STOP_FILE", str(marker))
    assert not stop_requested()
    marker.touch()
    assert stop_requested()
