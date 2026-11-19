"""Read-only inventory and consistent backup; no reconciliation or provider calls."""
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ledger = HERE.parents[2]/'eval/experiments/architecture-20261118/budget.sqlite'
backup = HERE/'evidence/ledger-before.sqlite'
assert not backup.exists()
with sqlite3.connect(ledger) as db:
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute("SELECT * FROM calls WHERE status='uncertain'")]
    totals = [dict(r) for r in db.execute(
        'SELECT status,count(*) calls,sum(held) committed_microusd,sum(actual) actual_microusd '
        'FROM calls GROUP BY status')]
    with sqlite3.connect(backup) as target:
        db.backup(target)
with (HERE/'evidence/billing-inventory.json').open('x') as out:
    json.dump({'uncertain_calls': rows, 'totals': totals,
               'billing_evidence': 'not available; no holds released'},out,indent=2)
print(json.dumps(totals))
