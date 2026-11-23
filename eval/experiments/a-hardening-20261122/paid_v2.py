"""Run only the new A development protocol; historical scripts/evidence stay untouched."""
import hashlib
import json
import os
import sys
from pathlib import Path

from dawalink.agent.llm.base import LLMRejected
from dawalink.evals import budget, experiment

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CAPS = dict(baseline=4_000_000, screening=10_000_000, expanded=6_000_000,
            heldout=3_000_000, retries=2_000_000)


def main():
    if (HERE / 'STOP_PAID').exists():
        raise SystemExit('New A paid work stopped; inspect the checkpoint before resuming')
    if '--stage' not in sys.argv or sys.argv[sys.argv.index('--stage') + 1] != 'expanded':
        raise SystemExit('This development bootstrap only authorizes expanded allocation')
    if '--architecture' in sys.argv and sys.argv[sys.argv.index('--architecture') + 1] != 'current':
        raise SystemExit('Only A/current is authorized')
    pin = json.loads((HERE / 'candidate2-pin.json').read_text())
    if experiment.fingerprint() != pin['source_hashes']:
        raise SystemExit('Development source changed; create a distinct candidate protocol')
    for name, expected in pin['harness_hashes'].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != expected:
            raise SystemExit('Pinned development harness changed')
    budget.CAPS.update(CAPS)
    reserve = budget.Ledger.reserve

    def bounded(ledger, run, stage, amount=budget.HAIKU_RESERVATION):
        with ledger.connect() as db:
            unknown = {r[0] for r in db.execute("SELECT id FROM calls WHERE status='uncertain'")}
        if unknown - set(pin['existing_uncertain_ids']):
            (HERE / 'STOP_PAID').write_text('New billing uncertainty; preserve all reservations.\n')
        if (HERE / 'STOP_PAID').exists():
            raise LLMRejected('Stopped before transmission; inspect case checkpoints and ledger')
        return reserve(ledger, run, stage, amount)

    budget.Ledger.reserve = bounded
    for key in list(os.environ):
        if any(s in key for s in ('API_KEY', 'LANGFUSE', 'DATABASE_', 'LLM_', 'EVAL_', 'DAWALINK_ARCHITECTURE')):
            del os.environ[key]
    for line in (ROOT / 'eval/checkpoints/2026-11-19-git-integration/local.env').read_text().splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            os.environ[key] = value
    for line in (ROOT / '.env').read_text().splitlines():
        if line.startswith('ANTHROPIC_API_KEY='):
            os.environ['ANTHROPIC_API_KEY'] = line.split('=', 1)[1].strip().strip('"\'')
            break
    else:
        raise SystemExit('Evaluation key missing')
    os.environ['EVAL_DATASET'] = 'expanded'
    os.environ['EVAL_STOP_FILE'] = str(HERE / 'STOP_PAID')
    before = set((experiment.EXPERIMENT / 'runs').iterdir())
    try:
        experiment.main()
    finally:
        for folder in set((experiment.EXPERIMENT / 'runs').iterdir()) - before:
            experiment.write_once(folder / 'a-hardening-policy.json', {
                'authorization': 'Owner pasted six-stage task, 22 November 2026',
                'caps_microusd': CAPS, 'total_microusd': budget.TOTAL,
                'development_pin_sha256': hashlib.sha256((HERE / 'candidate2-pin.json').read_bytes()).hexdigest(),
                'bootstrap_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'stop_on_new_uncertain_call': True,
            })


if __name__ == '__main__':
    main()
