"""Seal the new checkpoint with read-only checks and exclusive evidence creation."""
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

from dawalink.evals.scan_results import scan

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EVIDENCE = HERE / "evidence"
EXPERIMENT = ROOT / "eval/experiments/architecture-20261118"

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

old = json.loads((HERE.parent / "2026-11-18-readiness/evidence/integrity.json").read_text())
assert all(digest(ROOT / path) == value for path, value in old["run_files_sha256"].items())
assert digest(ROOT / "DawaLink_Roadmap_and_Database_Handoff.md") == old["handoff_sha256"]
assert git("rev-parse", "HEAD") == "1e17db0ea522622caaf8da41d60df4ef152ccec3"
assert git("branch", "--show-current") == "test/agent-evaluation"
assert not git("diff", "HEAD", "--", "backend/src/dawalink/agent", "eval/results", "eval/baseline.json")
subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
with sqlite3.connect(f"file:{EXPERIMENT / 'budget.sqlite'}?mode=ro", uri=True) as db:
    calls = db.execute("SELECT * FROM calls ORDER BY id").fetchall()
with sqlite3.connect(f"file:{EVIDENCE / 'ledger-before.sqlite'}?mode=ro", uri=True) as db:
    assert calls == db.execute("SELECT * FROM calls ORDER BY id").fetchall()
secrets = []
for line in (ROOT / ".env").read_text().splitlines():
    key, sep, value = line.partition("=")
    if sep and key in ("ANTHROPIC_API_KEY", "ORS_API_KEY", "LANGFUSE_SECRET_KEY"):
        value = value.strip().strip("\"'")
        if len(value) > 20:
            secrets.append(value.encode())
assert secrets, "No configured credential available for exact output scan"
artifacts = [p for base in (ROOT / "eval/checkpoints", EXPERIMENT)
             for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
assert not any(secret in path.read_bytes() for path in artifacts for secret in secrets), "credential in saved output"
read, found = scan(EXPERIMENT / "runs")
privacy = []
for f in found:
    # Require the exact candidate to be a fractional second of an ISO timestamp.
    timestamp = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:(\d{2}\.\d{6})(?:\+00:00|Z)",
                          f.file.read_text())
    disposition = "timestamp false positive" if timestamp and timestamp[1] == f.text else "needs review"
    privacy.append({"file": str(f.file.relative_to(ROOT)), "what": f.what,
                    "candidate": f.text, "disposition": disposition})
assert all(f["disposition"] == "timestamp false positive" for f in privacy), "new privacy candidate requires review"
sources = [p for base in ("backend/src", "backend/tests", "backend/migrations", "frontend/src",
                         "eval/datasets", "eval/world", "eval/experiments/architecture-20261118/reviewed-development")
           for p in (ROOT / base).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
sources += [ROOT / path for path in ("backend/uv.lock", "frontend/package-lock.json",
                                   "backend/data/moph/catalog.csv", "backend/data/catalog_overrides.toml",
                                   "docs/build_plan.md", "eval/experiments/architecture-20261118/reconciliation-freeze.json")]
report = {"reference_commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
          "old_run_files_verified": len(old["run_files_sha256"]), "handoff_sha256": old["handoff_sha256"],
          "agent_prompts_historical_results_unchanged": True, "diff_whitespace_check": "passed",
          "ledger_calls_unchanged": True, "ledger_calls": len(calls),
          "known_spend_microusd": sum(c[4] or 0 for c in calls),
          "committed_microusd": sum(c[3] for c in calls),
          "configured_credential_scan": "passed", "scanned_artifacts": len(artifacts),
          "experiment_privacy_scan": {"files": read, "candidates": privacy},
          "source_and_inputs_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted(sources) if p.exists()},
          "run_files_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted((EXPERIMENT / "runs").rglob("*")) if p.is_file()}}
with (EVIDENCE / "final-integrity-v2.json").open("x") as out:
    json.dump(report, out, indent=2)
with (EVIDENCE / "final-code-v2.diff").open("x") as out:
    out.write(git("diff", "--", "backend", "frontend", "docs/build_plan.md") + "\n")
print("Original run files verified:", report["old_run_files_verified"])
print("Agent/prompts/historical results/handoff preserved; ledger call rows unchanged.")
print("Configured credential scan passed; privacy candidates:", json.dumps(privacy))
print("Final source/input and all immutable run hashes saved.")
