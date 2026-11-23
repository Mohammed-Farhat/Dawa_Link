"""Execute saved argument vectors through the EXISTING experiment runner, sequentially.

This owns no model, scoring or world implementation. Every suite uses paid.py ->
experiment.main -> existing suite, including its canonical budget and immutable evidence.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

from dawalink.evals.budget import CAPS, HAIKU_RESERVATION, TOTAL, Ledger

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUNS = ROOT / 'eval/experiments/architecture-20261118/runs'
LEDGER = RUNS.parent / 'budget.sqlite'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--execution-id', required=True)
    parser.add_argument('--start-step', type=int, default=1)
    parser.add_argument('--plan', default='screening-commands.json')
    args = parser.parse_args()
    if not args.execution_id.replace('-', '').isalnum():
        raise SystemExit('invalid execution ID')
    commands = json.loads((HERE / args.plan).read_text())['commands']
    ledger = Ledger(LEDGER)
    with (HERE / f'evidence/screening-{args.execution_id}.jsonl').open('x') as events:
        for index, command in enumerate(commands, 1):
            if index < args.start_step:
                continue
            with ledger.connect() as db:
                local, total = db.execute(
                    "SELECT COALESCE(SUM(CASE WHEN stage='screening' THEN held ELSE 0 END),0),"
                    "COALESCE(SUM(held),0) FROM calls"
                ).fetchone()
            if local + HAIKU_RESERVATION > CAPS['screening'] or total + HAIKU_RESERVATION > TOTAL:
                events.write(json.dumps({'step': index, 'status': 'budget_preflight_stop',
                                         'ledger': ledger.totals()}) + '\n')
                print('Stopped before next call reservation', flush=True)
                return
            before = set(RUNS.iterdir())
            start = time.monotonic()
            log = HERE / f'evidence/screening-{args.execution_id}-step-{index:02d}.txt'
            with log.open('x') as output:
                output.write(json.dumps(command) + '\n')
                output.flush()
                result = subprocess.run(command, cwd=ROOT / 'backend', stdout=output,
                                        stderr=subprocess.STDOUT)
            created = set(RUNS.iterdir()) - before
            entry = {'step': index, 'argv': command, 'exit_code': result.returncode,
                     'seconds': round(time.monotonic() - start, 3),
                     'runs': sorted(p.name for p in created), 'ledger': ledger.totals()}
            events.write(json.dumps(entry) + '\n')
            events.flush()
            print(json.dumps(entry), flush=True)
            if result.returncode or len(created) != 1:
                print('Stopped for inspection; no automatic retry', flush=True)
                return
            folder = created.pop()
            with ledger.connect() as db:
                unsettled = db.execute(
                    "SELECT COUNT(*) FROM calls WHERE run=? AND status NOT IN ('settled','reconciled')",
                    (folder.name,)
                ).fetchone()[0]
            # Any provider/budget uncertainty stops scaling. Do not reset or borrow.
            if unsettled:
                print('Stopped for unresolved provider reservations', flush=True)
                return
            completion = json.loads((folder / 'completion.json').read_text())
            manifest = json.loads((folder / 'manifest.json').read_text())
            filename = 'conversations.jsonl' if manifest['suite'] == 'multiturn' else 'answers.jsonl'
            rows = sum(len(p.read_text().splitlines()) for p in folder.glob(f'*/{filename}'))
            if rows != manifest['expected']:
                print('Stopped for missing raw coverage; no automatic retry', flush=True)
                return
            if completion['status'] != 'complete':
                print('Full raw coverage with non-ok outcomes; retained as failures, continuing '
                      'other contenders for paired inspection', flush=True)


if __name__ == '__main__':
    main()
