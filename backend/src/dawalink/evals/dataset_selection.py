"""Internal development-suite selection; draft versions cannot enter paid/scored runs."""

import json
from pathlib import Path

from dawalink.evals.datasets import CaseBase
from dawalink.evals.development_review import ROOT, VERSION, digest

EXPERIMENT = ROOT / "eval/experiments/architecture-20261118"


def select_dataset(name: str, *, allow_draft: bool = False) -> tuple[Path, Path]:
    """Return understanding/safety folder and fixed-conversation file together."""
    if name == "expanded":
        if allow_draft:
            return VERSION, VERSION / "multiturn.jsonl"
        manifest = VERSION / "freeze.json"
        if not manifest.exists():
            raise ValueError(
                "expanded development set is draft: separate review/human checks pending"
            )
        freeze = json.loads(manifest.read_text())
        if freeze.get("status") != "frozen":
            raise ValueError("expanded development set is not frozen")
        required = {f"scored/{suite}.jsonl" for suite in ("understanding", "safety", "multiturn")}
        if not required <= freeze.get("hashes", {}).keys():
            raise ValueError("expanded development freeze changed: scored suites missing")
        for relative, expected in freeze["hashes"].items():
            path = VERSION / relative
            if path.resolve().is_relative_to(VERSION.resolve()) and digest(path) == expected:
                continue
            raise ValueError("expanded development freeze changed")
        return VERSION / "scored", VERSION / "scored/multiturn.jsonl"
    if name not in ("development", "challenge", "reviewed"):
        raise ValueError("invalid development dataset")
    folder = EXPERIMENT / ("reviewed-development" if name == "reviewed" else name)
    return folder, ROOT / "eval/datasets/multiturn.jsonl"


def fixed_cases[Case: CaseBase](cases: list[Case], ids: str) -> list[Case]:
    """Stable original order, reject typos/duplicates before spending."""
    if not ids:
        return cases
    wanted = ids.split(",")
    if len(set(wanted)) != len(wanted):
        raise ValueError("duplicate fixed case ID")
    by_id = {c.id: c for c in cases}
    if set(wanted) - by_id.keys():
        raise ValueError("unknown fixed case ID")
    return [c for c in cases if c.id in wanted]
