"""Freeze reviewed development inputs without altering earlier experiment freezes."""
import hashlib
import json
from pathlib import Path

from dawalink.evals.datasets import RCase, UCase, read
from dawalink.evals.run_multiturn import MCase

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = ROOT / "eval/experiments/architecture-20261118"
paths = [(EXPERIMENT / "reviewed-development/understanding.jsonl", UCase),
         (EXPERIMENT / "reviewed-development/safety.jsonl", RCase),
         (ROOT / "eval/datasets/multiturn.jsonl", MCase)]
manifest = {}
for path, kind in paths:
    cases = read(path, kind)
    print(path.name, len(cases), "schema valid")
    manifest[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
with (EXPERIMENT / "reconciliation-freeze.json").open("x") as stream:
    json.dump(manifest, stream, indent=2)
print("Separate reviewed-case freeze saved; original dataset-freeze.json unchanged")
