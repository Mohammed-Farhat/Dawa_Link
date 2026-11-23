"""Offline inventory of NEW reference runs; never treats partial/smoke as comparison."""

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from dawalink.evals.score_understanding import CHECKS

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUNS = ROOT / 'eval/experiments/architecture-20261118/runs'
LEDGER = RUNS.parent / 'budget.sqlite'


def analyze() -> dict:
    reference = json.loads((HERE / 'reference.json').read_text())
    final_hashes = json.loads((HERE / 'screening-source-freeze.json').read_text())['source_hashes']
    excluded = json.loads((HERE / 'coverage-repair.json').read_text())['primary_excluded_runs']
    runs, review, paired, case_results = [], [], defaultdict(dict), []
    for folder in sorted(RUNS.iterdir()):
        if not (folder / 'manifest.json').exists():
            continue
        manifest = json.loads((folder / 'manifest.json').read_text())
        if manifest.get('reference') != reference:
            continue
        completion = json.loads((folder / 'completion.json').read_text()) if (
            folder / 'completion.json').exists() else {'status': 'incomplete'}
        filename = 'conversations.jsonl' if manifest['suite'] in (
            'multiturn', 'conversations') else 'answers.jsonl'
        rows = [json.loads(line) for p in folder.glob(f'*/{filename}')
                for line in p.read_text().splitlines()]
        eligible = manifest['kind'] == 'comparison' and manifest['hashes'] == final_hashes and folder.name not in excluded
        executed = all_pass = questions = question_cases = 0
        grouped = defaultdict(list)
        for row in rows:
            steps = row.get('exchanges', [row])
            ok = row.get('outcome') == 'ok' and all(s.get('outcome') == 'ok' for s in steps)
            checks = [(key, value) for step in steps for key, value in step.get('checks', {}).items()
                      if value is not None]
            failed = [key for key, value in checks if value != CHECKS.get(key, True)]
            passed = ok and bool(checks) and not failed
            executed += ok
            all_pass += passed
            for step in steps:
                if step.get('checks', {}).get('asks_needlessly') is not None:
                    question_cases += 1
                    questions += bool(step['checks']['asks_needlessly'])
            flags = [issue for step in steps
                     for issue in step.get('review', {}).get('candidate_issues', [])]
            signature = {
                'where': row.get('where', ''), 'execution_ok': ok,
                'checks': [step.get('checks', {}) for step in steps],
                'card_facts': sorted({(str(c.get('product_id')), c.get('qty', 1),
                                       c.get('days_of_use'))
                                      for step in steps for c in step.get('card_items', [])}),
                'card_kinds': sorted({c for step in steps for c in step.get('cards', [])}),
                'listing_choices': sorted({str(c.get('listing_id')) for step in steps
                                           for c in step.get('card_items', [])}),
                'tool_names': sorted(t['name'] for step in steps for t in step.get('tools', [])),
            }
            grouped[row['id']].append({'pass': passed, 'signature': signature,
                                      'execution_ok': ok, 'seconds': row.get('seconds'),
                                      'automatic_failed': failed, 'semantic_flags': flags})
            # Every safety, semantic flag, execution failure and quality failure is queued.
            if eligible and (manifest['suite'] == 'safety' or flags or failed or not ok):
                review.append({'run': folder.name, 'architecture': manifest['architecture'],
                               'suite': manifest['suite'], 'id': row['id'],
                               'where': row.get('where'), 'execution_ok': ok,
                               'automatic_failed': failed, 'semantic_flags': flags,
                               'row': row, 'reviewer_verdict': None})
        for case, results in grouped.items():
            result = {'suite': manifest['suite'], 'id': case,
                      'repetition': manifest['repetition'], 'architecture': manifest['architecture'],
                      'run': folder.name, 'pass': all(r['pass'] for r in results),
                      'execution_ok': all(r['execution_ok'] for r in results),
                      'observations': results}
            if eligible:
                case_results.append(result)
                paired[(manifest['suite'], case, manifest['repetition'])][manifest['architecture']] = result
        with sqlite3.connect(LEDGER) as db:
            spend = db.execute('SELECT COALESCE(SUM(actual),0),COALESCE(SUM(held),0),COUNT(*) '
                               'FROM calls WHERE run=?', (folder.name,)).fetchone()
        runs.append({'run': folder.name, 'architecture': manifest['architecture'],
                     'stage': manifest['stage'], 'kind': manifest['kind'],
                     'final_source_match': manifest['hashes'] == final_hashes,
                     'eligible_comparison': eligible,
                     'primary_exclusion_reason': excluded.get(folder.name),
                     'suite': manifest['suite'], 'repetition': manifest['repetition'],
                     'status': completion['status'], 'expected': manifest['expected'],
                     'rows': len(rows), 'execution_ok': executed,
                     'cases': len(grouped),
                     'case_all_checks_pass': sum(all(r['pass'] for r in rs) for rs in grouped.values()),
                     'automatic_all_checks_pass': all_pass,
                     'needless_questions': questions, 'question_cases': question_cases,
                     'known_microusd': spend[0], 'committed_microusd': spend[1], 'calls': spend[2]})
    disagreements = [{'case': key, 'architectures': architectures}
                     for key, architectures in paired.items()
                     if len({json.dumps([r['signature'] for r in a['observations']], sort_keys=True)
                             for a in architectures.values()}) > 1]
    with sqlite3.connect(LEDGER) as db:
        spending = db.execute('SELECT stage,status,COUNT(*),COALESCE(SUM(actual),0),SUM(held) '
                              'FROM calls GROUP BY stage,status').fetchall()
    return {'runs': runs, 'case_results': case_results, 'review_queue': review,
            'disagreements': disagreements,
            'spending': spending,
            'warning': 'Automatic checks are preliminary; review verdicts are separate. '
                       'No ranking from smoke, partial coverage or unresolved safety flags.'}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = analyze()
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'runs': result['runs'], 'spending': result['spending']}, indent=2))


if __name__ == '__main__':
    main()
