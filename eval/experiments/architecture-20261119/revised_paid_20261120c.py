"""Authorized budget policy around the existing, unchanged experiment runner."""
import hashlib
import json
import os
import sys
from pathlib import Path

from dawalink.agent.llm.base import LLMRejected
from dawalink.evals import budget, experiment

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AUTH = HERE / 'evidence/approved-caps-snapshot-20261120c.json'


def apply_policy():
    authorization = json.loads(AUTH.read_text())
    caps = authorization['caps_microusd']
    assert caps == dict(baseline=4000000, screening=9000000, expanded=7000000,
                        heldout=3000000, retries=2000000)
    assert sum(caps.values()) == authorization['aggregate_microusd'] == budget.TOTAL
    budget.CAPS.update(caps)
    permitted_unknown = set(authorization['existing_uncertain_ids'])
    original_reserve = budget.Ledger.reserve

    def reserve(ledger, run, stage, amount=budget.HAIKU_RESERVATION):
        # Evaluation stop control only: existing agent prompts/tools/retries stay intact.
        with ledger.connect() as db:
            unknown = {r[0] for r in db.execute("SELECT id FROM calls WHERE status='uncertain'")}
        if unknown - permitted_unknown:
            raise LLMRejected('screening stopped after new billing uncertainty')
        return original_reserve(ledger, run, stage, amount)

    budget.Ledger.reserve = reserve
    return authorization


def main():
    authorization = apply_policy()
    if (HERE / 'STOP_REVISED_SCREENING').exists():
        raise SystemExit('Revised screening stopped; inspect before any restart')
    if '--stage' not in sys.argv or sys.argv[sys.argv.index('--stage') + 1] != 'screening':
        raise SystemExit('This bootstrap is only for screening')
    pin = json.loads((HERE / 'screening-source-freeze.json').read_text())
    if experiment.fingerprint() != pin['source_hashes']:
        raise SystemExit('Frozen source changed; do not pool results')
    for name, key in [('screening.json', 'sample_sha256'), ('targets.json', 'targets_sha256')]:
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != pin[key]:
            raise SystemExit('Frozen sample or targets changed')
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
    bootstrap_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    try:
        experiment.main()
    finally:
        for folder in set((experiment.EXPERIMENT / 'runs').iterdir()) - before:
            experiment.write_once(folder / 'approved-budget-policy.json', {
                'authorization': authorization,
                'authorization_sha256': hashlib.sha256(AUTH.read_bytes()).hexdigest(),
                'bootstrap_sha256': bootstrap_hash,
                'effective_caps_microusd': budget.CAPS,
                'aggregate_cap_microusd': budget.TOTAL,
                'stop_on_new_uncertain_call': True,
            })


if __name__ == '__main__':
    main()
