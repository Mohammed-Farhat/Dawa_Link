"""Audit historical evidence and append-only ledger after new A work (no model calls)."""
import hashlib
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'eval/experiments/architecture-20261119/revised-20261120'
LEDGER = ROOT / 'eval/experiments/architecture-20261118/budget.sqlite'
CAPS = dict(baseline=4000000, screening=10000000, expanded=6000000, heldout=3000000, retries=2000000)


def audit():
    seal = json.loads((OLD / 'completed-seal.json').read_text())
    # New source intentionally differs. Historical source was verified in full before
    # preservation commit bdc5c16 and remains available there and in run archives.
    evidence = {p: h for p, h in seal['sha256'].items()
                if not p.startswith('backend/') and not p.endswith('architecture-20261118/budget.sqlite')}
    changed = [p for p, h in evidence.items() if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != h]
    with sqlite3.connect(f'file:{LEDGER}?mode=ro', uri=True) as now, sqlite3.connect(
        f'file:{OLD / "completed-budget.sqlite"}?mode=ro', uri=True
    ) as old:
        altered = []
        for table, key in [('calls', 'id'), ('call_events', 'seq')]:
            for row in old.execute(f'SELECT * FROM {table}'):
                if now.execute(f'SELECT * FROM {table} WHERE {key}=?', (row[0],)).fetchone() != row:
                    altered.append([table, row[0]])
        stages = {s: dict(known=k or 0, committed=h, remaining=CAPS[s]-h)
                  for s, k, h in now.execute('SELECT stage,SUM(actual),SUM(held) FROM calls GROUP BY stage')}
        for s in CAPS:
            stages.setdefault(s, dict(known=0, committed=0, remaining=CAPS[s]))
        uncertain = [dict(id=i, stage=s, held=h) for i,s,h in now.execute(
            "SELECT id,stage,held FROM calls WHERE status='uncertain' ORDER BY id")]
        active = [r[0] for r in now.execute("SELECT id FROM calls WHERE status='reserved'")]
    errors = changed + [str(x) for x in altered]
    if any(s['remaining'] < 0 for s in stages.values()) or sum(s['committed'] for s in stages.values()) > 25000000:
        errors.append('Budget cap exceeded')
    return dict(passed=not errors, errors=errors, historical_evidence_files=len(evidence),
                historical_ledger_rows_unchanged=not altered, stages_microusd=stages,
                known_microusd=sum(s['known'] for s in stages.values()),
                committed_microusd=sum(s['committed'] for s in stages.values()),
                uncertain=uncertain, active_reservations=active,
                handoff_sha256=hashlib.sha256((ROOT/'DawaLink_Roadmap_and_Database_Handoff.md').read_bytes()).hexdigest())


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2))
