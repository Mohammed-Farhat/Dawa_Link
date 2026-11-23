"""Recompute primary coverage, raw scores and review coverage without model calls.

Conditional scorer rates are not semantic acceptance. Execution failures stay in the
all-case/context denominator and in the flagged-result count. No outcomes are replaced.
"""
import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from export_review import REGRESSIONS, failed

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = ROOT / 'eval/experiments/architecture-20261118/runs'


def summarize():
    pin = json.loads((HERE / 'candidate5-pin.json').read_text())
    plan = json.loads((HERE / 'candidate5-batches.json').read_text())['batches']
    queue = json.loads((HERE / 'evidence/candidate5-primary-queue.json').read_text())
    by_batch = {b['name']: b for b in plan}
    completed = queue['completed']
    if len({b['batch'] for b in completed}) != len(completed):
        raise ValueError('Duplicate dispatched batch')
    review_path = HERE / 'evidence/candidate5-primary-assistant-review.jsonl'
    reviews = [json.loads(l) for l in review_path.read_text().splitlines()] if review_path.exists() else []
    reviewed = {(r['run'], r['id'], r.get('where')) for r in reviews}
    groups = defaultdict(list)
    raw_files = {}
    required_review = set()
    seen = set()
    for batch in completed:
        specification = by_batch[batch['batch']]
        folder = RUNS / batch['run']
        manifest = json.loads((folder / 'manifest.json').read_text())
        if manifest['hashes'] != pin['source_hashes']:
            raise ValueError('Primary source differs from candidate pin')
        filename = 'conversations.jsonl' if specification['suite']=='multiturn' else 'answers.jsonl'
        paths = list(folder.glob(f'*/{filename}'))
        if len(paths) != 1:
            raise ValueError('Missing or duplicate raw outcome file')
        path = paths[0]
        raw_files[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = [json.loads(l) for l in path.read_text().splitlines()]
        if len(rows)!=specification['rows'] or {r['id'] for r in rows}!=set(specification['ids']):
            raise ValueError('Batch coverage differs from pre-outcome matrix')
        for row in rows:
            key = (specification['suite'], row['id'], row.get('where'))
            if key in seen:
                raise ValueError('Duplicate primary context')
            seen.add(key)
            groups[specification['suite']].append(row)
            flag = failed(row) or any(failed(e) for e in row.get('exchanges', []))
            if specification['suite'] in ('safety','multiturn') or flag or row['id'] in REGRESSIONS:
                required_review.add((batch['run'],row['id'],row.get('where')))
    suites = {}
    for suite, rows in groups.items():
        checks = defaultdict(Counter)
        for row in rows:
            for observation in row.get('exchanges', [row]):
                for key, value in observation.get('checks', {}).items():
                    checks[key]['not_applicable' if value is None else 'yes' if value else 'no'] += 1
        suites[suite] = dict(
            cases=len({r['id'] for r in rows}), contexts_or_conversations=len(rows),
            execution_ok=sum(r.get('outcome')=='ok' for r in rows),
            flagged_outcomes=sum(failed(r) or any(failed(e) for e in r.get('exchanges', [])) for r in rows),
            raw_conditional_checks={k:dict(v) for k,v in sorted(checks.items())},
        )
        if suite=='multiturn':
            suites[suite].update(expected_turns=sum(r['expected_turns'] for r in rows),
                                 observed_turns=sum(len(r['exchanges']) for r in rows))
    with sqlite3.connect(f'file:{RUNS.parent / "budget.sqlite"}?mode=ro',uri=True) as db:
        costs = []
        for batch in completed:
            known, unsettled = db.execute(
                "SELECT COALESCE(SUM(actual),0), SUM(CASE WHEN status NOT IN ('settled','reconciled') THEN 1 ELSE 0 END) FROM calls WHERE run=?",
                (batch['run'],),
            ).fetchone()
            costs.append(dict(run=batch['run'],known_microusd=known,unsettled_calls=unsettled or 0))
    return dict(
        queue_status=queue['status'], completed_batches=len(completed),expected_batches=len(plan),
        all_primary_case_attempts_present=len(completed)==len(plan), suites=suites,
        costs=costs,known_primary_microusd=sum(r['known_microusd'] for r in costs),
        required_assistant_review_records=len(required_review),
        missing_assistant_reviews=[dict(run=r,id=i,where=w) for r,i,w in sorted(required_review-reviewed,key=str)],
        assistant_verdicts=dict(Counter(r['verdict'] for r in reviews)),
        independent_acceptance=False,raw_file_sha256=raw_files,
        limitations=[
            'Raw conditional scorer checks retain their original applicability and known regex errors.',
            'Execution failures remain in every suite context/conversation count, not silently excluded.',
            'Flagged outcomes combine scorer/semantic/execution flags and are not confirmed agent-defect counts.',
            'A failed fixed conversation may stop before later scripted turns; observed turns are reported.',
            'Implementation-assistant review is not independent human acceptance.',
        ],
    )


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    result=summarize()
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2)
        stream.write('\n')
