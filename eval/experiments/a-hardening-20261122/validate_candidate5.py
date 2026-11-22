"""One-shot sequential primary matrix. No retries or outcome-based case selection."""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = ROOT / 'eval/experiments/architecture-20261118/runs'
STATE = HERE / 'evidence/candidate5-primary-queue.json'


def main():
    pin = json.loads((HERE / 'candidate5-pin.json').read_text())
    plan = json.loads((HERE / 'candidate5-batches.json').read_text())
    state = dict(status='started', completed=[],
                 pin_sha256=hashlib.sha256((HERE / 'candidate5-pin.json').read_bytes()).hexdigest())
    with STATE.open('x') as stream:
        json.dump(state, stream)
    try:
        for batch in plan['batches']:
            if (HERE / 'STOP_PAID').exists():
                raise RuntimeError('STOP_PAID present')
            with sqlite3.connect(f'file:{RUNS.parent / "budget.sqlite"}?mode=ro', uri=True) as db:
                unknown = {r[0] for r in db.execute("SELECT id FROM calls WHERE status='uncertain'")}
                active = db.execute("SELECT COUNT(*) FROM calls WHERE status='reserved'").fetchone()[0]
            if active or unknown - set(pin['existing_uncertain_ids']):
                raise RuntimeError('Active reservation or new billing uncertainty')
            cap = {'understanding-1':'0.90', 'understanding-2':'0.20',
                   'safety-1':'0.40', 'safety-2':'0.15'}.get(batch['name'], '0.20')
            command = [sys.executable, '-u', str(HERE / 'paid_v5.py'), batch['suite'],
                       '--architecture','current','--stage','expanded','--model','claude-haiku-5-5',
                       '--effort','medium','--cases',','.join(batch['ids']),'--max-usd',cap]
            before = set(RUNS.iterdir())
            state.update(status='running', batch=batch['name'], command=command)
            STATE.write_text(json.dumps(state,indent=2)+'\n')
            with (HERE / f'evidence/candidate5-primary-{batch["name"]}.txt').open('x') as log:
                result = subprocess.run(command,cwd=ROOT/'backend',stdout=log,stderr=subprocess.STDOUT)
            created = set(RUNS.iterdir()) - before
            if result.returncode or len(created) != 1:
                raise RuntimeError(f'{batch["name"]} failed before normal completion; inspect raw evidence')
            run = created.pop()
            completion = json.loads((run/'completion.json').read_text())
            filename = 'conversations.jsonl' if batch['suite']=='multiturn' else 'answers.jsonl'
            paths = list(run.glob(f'*/{filename}'))
            rows = [json.loads(l) for p in paths for l in p.read_text().splitlines()]
            if len(paths)!=1 or len(rows)!=batch['rows'] or {r['id'] for r in rows}!=set(batch['ids']):
                raise RuntimeError(f'{batch["name"]} incomplete coverage; do not duplicate attempted cases')
            if completion['error_type']:
                raise RuntimeError(f'{batch["name"]} has an execution exception')
            state['completed'].append(dict(batch=batch['name'],run=run.name,rows=len(rows),
                                           execution_status=completion['status']))
        state.update(status='raw_matrix_complete_review_pending')
    except Exception as error:
        state.update(status='stopped_needs_inspection',error=f'{type(error).__name__}: {error}')
        raise
    finally:
        STATE.write_text(json.dumps(state,indent=2)+'\n')


if __name__ == '__main__':
    main()
