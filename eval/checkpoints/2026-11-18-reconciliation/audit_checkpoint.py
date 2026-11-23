"""Read-only verification of paired worlds, spending and preserved evidence."""
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

from dawalink.evals import scan_results

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
EXPERIMENT = ROOT / "eval/experiments/architecture-20261118"
report = {"runs": [], "paired_inputs_identical": False}
inputs = []
for label in ("search", "rules", "rules-asking"):
    log = (HERE / f"evidence/paired-{label}.txt").read_text()
    run_id = re.search(r"/runs/([^/\s]+) status:", log).group(1)
    folder = EXPERIMENT / "runs" / run_id
    config = json.loads((folder / "manifest.json").read_text())
    completion = json.loads((folder / "completion.json").read_text())
    (path,) = folder.glob("*/initial-inputs.json")
    initial = json.loads(path.read_text())
    inputs.append(initial)
    (summary,) = folder.glob("*/summary.json")
    report["runs"].append({"run_id": run_id, "manifest": config,
                           "completion": completion, "initial": initial,
                           "summary": json.loads(summary.read_text())})
report["paired_inputs_identical"] = inputs[0] == inputs[1] == inputs[2]
assert report["paired_inputs_identical"], "Initial worlds/events differ"
assert all(r["completion"]["status"] == "complete" for r in report["runs"])
report["paired_code_hashes_identical"] = all(
    r["manifest"]["hashes"] == report["runs"][0]["manifest"]["hashes"] for r in report["runs"])

def calls(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        return db.execute("SELECT * FROM calls ORDER BY id").fetchall()

before = calls(HERE / "evidence/ledger-before.sqlite")
after = calls(EXPERIMENT / "budget.sqlite")
report["ledger_calls_unchanged"] = before == after
assert before == after
report["ledger_totals"] = {"settled_calls": sum(r[5] == "settled" for r in after),
                           "uncertain_calls": sum(r[5] == "uncertain" for r in after),
                           "actual_microusd": sum(r[4] or 0 for r in after),
                           "committed_microusd": sum(r[3] for r in after)}
report["agent_diff_exit"] = subprocess.run(
    ["git", "diff", "--exit-code", "HEAD", "--", "backend/src/dawalink/agent"],
    cwd=ROOT, capture_output=True).returncode
assert report["agent_diff_exit"] == 0
report["git_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
report["git_branch"] = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
report["handoff_sha256"] = hashlib.sha256((ROOT / "DawaLink_Roadmap_and_Database_Handoff.md").read_bytes()).hexdigest()
old = json.loads((HERE.parent / "2026-11-18-readiness/evidence/integrity.json").read_text())
report["old_integrity_structure"] = list(old)[:5]
read, found = scan_results.scan(EXPERIMENT / "runs")
report["experiment_privacy_scan"] = {"files": read, "candidates": len(found),
                                    "findings": [{"file": str(f.file.relative_to(ROOT)),
                                                  "what": f.what, "text": f.text} for f in found]}
with (HERE / "evidence/checkpoint-audit-findings.json").open("x") as stream:
    json.dump(report, stream, indent=2, default=str)
print(json.dumps({k:v for k,v in report.items() if k != "runs"}, indent=2))
