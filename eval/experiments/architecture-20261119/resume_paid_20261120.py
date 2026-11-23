"""Apply the owner's bounded allowance to the unchanged experiment entry point.

No model or scoring implementation lives here. Original STOP_SCREENING and all
prior evidence remain intact; only this explicitly authorized bootstrap may resume.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

from dawalink.evals import budget, experiment

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AUTH = HERE / 'evidence/owner-allowance-20261120.json'


def main():
    authorization = json.loads(AUTH.read_text())
    assert authorization['additional_allowance_microusd'] == 645000
    assert authorization['screening_ceiling_microusd'] == 6645000
    assert authorization['aggregate_ceiling_microusd'] == budget.TOTAL == 25000000
    if (HERE / 'STOP_ALLOWANCE_20261120').exists():
        raise SystemExit('Authorized allowance stopped; no automatic restart')
    if '--stage' not in sys.argv or sys.argv[sys.argv.index('--stage') + 1] != 'screening':
        raise SystemExit('This allowance is only for screening')
    budget.CAPS['screening'] = authorization['screening_ceiling_microusd']
    ledger = budget.Ledger(experiment.EXPERIMENT / 'budget.sqlite')
    with ledger.connect() as db:
        new_unknown = db.execute(
            "SELECT COUNT(*) FROM calls WHERE status IN ('uncertain','reserved') "
            "AND run LIKE '20261120%'"
        ).fetchone()[0]
        local, total = db.execute(
            "SELECT SUM(CASE WHEN stage='screening' THEN held ELSE 0 END),SUM(held) FROM calls"
        ).fetchone()
    if new_unknown or local + budget.HAIKU_RESERVATION > budget.CAPS['screening'] or total + budget.HAIKU_RESERVATION > budget.TOTAL:
        raise SystemExit('Allowance preflight stopped: unresolved call or insufficient headroom')
    for key in list(os.environ):
        if any(s in key for s in ('API_KEY', 'LANGFUSE', 'DATABASE_', 'LLM_', 'EVAL_', 'DAWALINK_ARCHITECTURE')):
            del os.environ[key]
    for line in (ROOT / 'eval/checkpoints/2026-11-19-git-integration/local.env').read_text().splitlines():
        key, value = line.split('=', 1)
        os.environ[key] = value
    for line in (ROOT / '.env').read_text().splitlines():
        if line.startswith('ANTHROPIC_API_KEY='):
            os.environ['ANTHROPIC_API_KEY'] = line.split('=', 1)[1].strip().strip('"\'')
            break
    else:
        raise SystemExit('Evaluation key missing')
    os.environ['EVAL_DATASET'] = 'expanded'
    before = set((experiment.EXPERIMENT / 'runs').iterdir())
    try:
        experiment.main()
    finally:
        for folder in set((experiment.EXPERIMENT / 'runs').iterdir()) - before:
            experiment.write_once(folder / 'owner-allowance.json', {
                'authorization': authorization,
                'authorization_sha256': hashlib.sha256(AUTH.read_bytes()).hexdigest(),
                'bootstrap_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'effective_caps_microusd': budget.CAPS,
                'aggregate_cap_microusd': budget.TOTAL,
            })


if __name__ == '__main__':
    main()
