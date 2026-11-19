"""Compare saved actual external events without rerunning or modifying results."""
import itertools
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPERIMENT = ROOT / "eval/experiments/architecture-20261118"
rows = []
draws = {}
arrivals = {}
for label in ("search", "rules", "rules-asking"):
    log = (HERE / f"evidence/events-{label}.txt").read_text()
    run_id = re.search(r"/runs/([^/\s]+) status:", log).group(1)
    folder = EXPERIMENT / "runs" / run_id
    manifest = json.loads((folder / "manifest.json").read_text())
    completion = json.loads((folder / "completion.json").read_text())
    (initial,) = folder.glob("*/initial-inputs.json")
    (event_file,) = folder.glob("*/events.jsonl")
    events = [json.loads(line) for line in event_file.read_text().splitlines()]
    (summary,) = folder.glob("*/summary.json")
    arrivals[label] = sorted(
        [e for e in events if e["kind"] == "stock_arrival"], key=lambda e: json.dumps(e, sort_keys=True)
    )
    keyed = {}
    for e in events:
        if e["kind"] not in ("draw", "delay"):
            continue
        key = json.dumps({k: v for k, v in e.items() if k != "value"}, sort_keys=True)
        assert key not in keyed or keyed[key] == e["value"], "same draw changed within run"
        keyed[key] = e["value"]
    draws[label] = keyed
    rows.append({"contender": label, "run_id": run_id, "completion": completion,
                 "initial_inputs": json.loads(initial.read_text()),
                 "summary": json.loads(summary.read_text()),
                 "events": len(events), "arrivals": len(arrivals[label]),
                 "all_arrivals_applied": all(e["applied"] for e in arrivals[label]),
                 "distinct_conditional_draws": len(keyed), "hashes": manifest["hashes"]})
pairs = []
for a, b in itertools.combinations(draws, 2):
    shared = draws[a].keys() & draws[b].keys()
    pairs.append({"a": a, "b": b, "shared_draws": len(shared),
                  "different_shared_values": sum(draws[a][k] != draws[b][k] for k in shared),
                  "only_a": len(draws[a].keys() - draws[b].keys()),
                  "only_b": len(draws[b].keys() - draws[a].keys())})
with sqlite3.connect(f"file:{EXPERIMENT / 'budget.sqlite'}?mode=ro", uri=True) as db:
    calls = db.execute("SELECT * FROM calls ORDER BY id").fetchall()
with sqlite3.connect(f"file:{HERE / 'evidence/ledger-before.sqlite'}?mode=ro", uri=True) as db:
    before = db.execute("SELECT * FROM calls ORDER BY id").fetchall()
report = {
    "runs": rows, "shared_conditional_draws": pairs,
    "initial_inputs_identical": all(r["initial_inputs"] == rows[0]["initial_inputs"] for r in rows),
    "code_hashes_identical": all(r["hashes"] == rows[0]["hashes"] for r in rows),
    "actual_arrivals_identical": all(v == arrivals["search"] for v in arrivals.values()),
    "ledger_call_rows_unchanged": calls == before,
    "known_spend_microusd": sum(c[4] or 0 for c in calls),
    "committed_microusd": sum(c[3] for c in calls),
    "limitations": ["One seed; conditional event sets depend on contender actions.",
                    "No paid current-agent run; this is an infrastructure audit."]
}
with (HERE / "evidence/event-audit-findings.json").open("x") as out:
    json.dump(report, out, indent=2)
assert all(report[k] for k in ("initial_inputs_identical", "code_hashes_identical",
                              "actual_arrivals_identical", "ledger_call_rows_unchanged"))
assert all(r["completion"]["status"] == "complete" and r["all_arrivals_applied"]
           and r["arrivals"] == r["initial_inputs"]["arrivals"] for r in rows)
assert all(p["shared_draws"] > 0 and p["different_shared_values"] == 0 for p in pairs)
print(json.dumps({k: v for k, v in report.items() if k != "runs"}, indent=2))
for row in rows:
    print(row["contender"], row["run_id"], row["events"], "events,", row["arrivals"], "arrivals,",
          row["summary"]["units_secured"], "/", row["summary"]["units_wanted"], "units")
