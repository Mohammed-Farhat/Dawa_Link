"""One-shot sequential coverage queue; never rerun, rescore or hide failed outcomes."""
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = ROOT / 'eval/experiments/architecture-20261118/runs'
FIRST = RUNS / '20261122T142220_8b5e802698ef'
STATE = HERE / 'evidence/development-queue.json'
PIN = json.loads((HERE / 'candidate4-pin.json').read_text())


def checkpoint(status, **fields):
    STATE.write_text(json.dumps(dict(status=status, **fields), indent=2) + '\n')


def safe():
    if (HERE / 'STOP_PAID').exists():
        raise RuntimeError('STOP_PAID present; queue stopped')
    with sqlite3.connect(f'file:{RUNS.parent / "budget.sqlite"}?mode=ro', uri=True) as db:
        unknown = {r[0] for r in db.execute("SELECT id FROM calls WHERE status='uncertain'")}
        active = db.execute("SELECT COUNT(*) FROM calls WHERE status='reserved'").fetchone()[0]
    if unknown - set(PIN['existing_uncertain_ids']) or active:
        raise RuntimeError('New uncertainty or active calls; queue must not transmit')


def covered(folder, filename):
    manifest = json.loads((folder / 'manifest.json').read_text())
    completion = json.loads((folder / 'completion.json').read_text())
    paths = list(folder.glob(f'*/{filename}'))
    rows = [json.loads(line) for path in paths for line in path.read_text().splitlines()]
    if len(paths) != 1 or len(rows) != manifest['expected'] or completion['error_type']:
        raise RuntimeError(f'Incomplete raw coverage in {folder.name}; do not duplicate it')
    return dict(run=folder.name, rows=len(rows), status=completion['status'],
                note='Raw coverage only; failed outcomes remain failures, not acceptance.')


def main():
    with STATE.open('x') as stream:
        json.dump(dict(status='waiting_for_understanding',run=FIRST.name), stream)
    while not (FIRST / 'completion.json').exists():
        time.sleep(30)
    completed = [covered(FIRST, 'answers.jsonl')]
    for suite, cap, filename in [('safety','0.80','answers.jsonl'), ('multiturn','0.50','conversations.jsonl')]:
        safe()
        before = set(RUNS.iterdir())
        command = [sys.executable, '-u', str(HERE / 'paid_v4.py'), suite,
                   '--architecture','current','--stage','expanded',
                   '--model','claude-haiku-5-5','--effort','medium','--max-usd',cap]
        checkpoint('running',suite=suite,command=command,completed=completed)
        with (HERE / f'evidence/candidate4-full-{suite}.txt').open('x') as log:
            result = subprocess.run(command, cwd=ROOT/'backend',stdout=log,stderr=subprocess.STDOUT)
        new = set(RUNS.iterdir()) - before
        if result.returncode or len(new) != 1:
            raise RuntimeError(f'{suite} stopped; preserve run and inspect before further work')
        completed.append(covered(new.pop(),filename))
        checkpoint('coverage_checkpoint',completed=completed)
    checkpoint('all_development_raw_coverage_saved_review_pending',completed=completed)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        checkpoint('stopped_needs_inspection',error=f'{type(error).__name__}: {error}')
        raise
