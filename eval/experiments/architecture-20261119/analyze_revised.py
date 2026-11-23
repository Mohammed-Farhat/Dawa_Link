"""Read immutable outcomes with explicit incident-recovery lineage; no paid calls."""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from dawalink.evals.score_understanding import CHECKS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = ROOT / 'eval/experiments/architecture-20261118/runs'
FIRST = {
    '20261119T155557_e5728d4d1c99', '20261119T160209_564cc4cef04f',
    '20261119T160936_6f61b62ff4fd', '20261119T161621_7d3d87c12895',
    # Original C1 U has all 30 case observations, including four provider failures.
    # The failed seven-row recovery is ancillary, never pooled with these outcomes.
    '20261119T162646_21096b0ddb62',
    # Keep all 18 observed safety prefix cases, including three execution failures.
    '20261120T094710_31138f2a43a0',
}
ORIGINAL_C = {'20261119T162646_21096b0ddb62', '20261120T094710_31138f2a43a0'}


def analyze():
    pin = json.loads((HERE / 'screening-source-freeze.json').read_text())
    sample = json.loads((HERE / 'screening.json').read_text())['cases']
    safety_partition = json.loads((HERE / 'safety-coverage-repair-20261120.json').read_text())
    safety_tail = set(safety_partition['cases'])
    safety_prefix = set(sample['safety']) - safety_tail
    safety_where = {r['id']: r['where'] for r in map(json.loads,
        (ROOT / 'eval/development-v2/scored/safety.jsonl').read_text().splitlines())}
    excluded = json.loads((HERE / 'coverage-repair.json').read_text())['primary_excluded_runs']
    adjudications = []
    for path in [HERE / 'evidence/manual-adjudications.jsonl',
                 HERE / 'revised-20261120/manual-adjudications.jsonl']:
        if path.exists():
            adjudications.extend(json.loads(line) for line in path.read_text().splitlines())
    cases, lineage, pending, review = [], [], [], []
    with sqlite3.connect('file:' + str(RUNS.parent / 'budget.sqlite') + '?mode=ro', uri=True) as db:
        for folder in sorted(RUNS.iterdir()):
            if not (folder / 'manifest.json').exists():
                continue
            m = json.loads((folder / 'manifest.json').read_text())
            if m['hashes'] != pin['source_hashes'] or folder.name in excluded or m['stage'] != 'screening':
                continue
            recovery = (m['repetition'] in ('normalized-1', 'normalized-2')
                        and m['kind'] == 'pilot' and m['suite'] == 'safety')
            selected = (folder.name in FIRST or recovery or
                        (m['kind'] == 'comparison' and m['repetition'] == '2') or
                        (m['kind'] == 'comparison' and m['repetition'] == '1'
                         and m['suite'] == 'multiturn'))
            if (folder.name in ORIGINAL_C and folder.name not in FIRST) or not selected:
                continue
            filename = 'conversations.jsonl' if m['suite'] == 'multiturn' else 'answers.jsonl'
            rows = [json.loads(line) for p in folder.glob('*/' + filename)
                    for line in p.read_text().splitlines()]
            original_rows = len(rows)
            if m['suite'] == 'safety' and not recovery:
                # Same prefix positions in every original batch, including failed rows.
                rows = [row for row in rows if row['id'] not in safety_tail]
                wanted = safety_prefix
            elif recovery:
                wanted = {m['argv'][m['argv'].index('--cases') + 1]}
                if not wanted <= safety_tail:
                    raise ValueError('Unexpected normalized safety case')
            else:
                wanted = (set(sample[m['suite']]) if m['suite'] != 'multiturn' else
                          {m['argv'][m['argv'].index('--cases') + 1]})
            grouped = defaultdict(list)
            for row in rows:
                grouped[row['id']].append(row)
            unsettled = db.execute("SELECT COUNT(*) FROM calls WHERE run=? AND status NOT IN ('settled','reconciled')", (folder.name,)).fetchone()[0]
            expected_rows = (sum(len(safety_where[id]) for id in wanted)
                             if m['suite'] == 'safety' else m['expected'])
            complete_raw = (len(rows) == expected_rows and set(grouped) == wanted
                            and (folder / 'completion.json').exists())
            if m['suite'] == 'safety':
                complete_raw = complete_raw and Counter((r['id'], r['where']) for r in rows) == Counter(
                    (id, where) for id in wanted for where in safety_where[id])
            if not complete_raw:
                pending.append({'run': folder.name, 'suite': m['suite'], 'rows': len(rows),
                                'expected': expected_rows, 'unsettled_calls': unsettled})
                continue
            # Whole recovery suite only. Never select successful rows from a failed original.
            rep = m['repetition'].rsplit('-', 1)[1] if recovery else m['repetition']
            lineage.append({'run': folder.name, 'architecture': m['architecture'],
                            'suite': m['suite'], 'original_kind': m['kind'],
                            'original_repetition': m['repetition'], 'analysis_repetition': rep,
                            'incident_recovery': recovery,
                            'original_provider_failures_retained': folder.name == '20261119T162646_21096b0ddb62',
                            'safety_scope': ('common-tail-case' if recovery else 'original-prefix18') if m['suite'] == 'safety' else None,
                            'original_raw_rows': original_rows, 'primary_raw_rows': len(rows),
                            'unsettled_calls': unsettled,
                            'raw_manifest_unchanged': True})
            for id, observations in grouped.items():
                raw_pass = adjusted_pass = execution_ok = True
                signatures, failures = [], []
                for row in observations:
                    steps = row.get('exchanges') or [row]
                    ok = row.get('outcome') == 'ok' and all(s.get('outcome') == 'ok' for s in steps)
                    if m['suite'] == 'multiturn':
                        ok = ok and len(steps) == row.get('expected_turns')
                    execution_ok = execution_ok and ok
                    changes = [j for j in adjudications if j['run'] == folder.name
                               and j['id'] == id and j.get('where') == row.get('where')]
                    row_raw = row_adjusted = ok
                    for index, step in enumerate(steps, 1):
                        raw = {k: v for k, v in step.get('checks', {}).items() if v is not None}
                        adjusted = dict(raw)
                        for change in changes:
                            if change.get('turn') in (None, index):
                                adjusted.update(change.get('overrides', {}))
                        row_raw = row_raw and bool(raw) and all(v == CHECKS.get(k, True) for k, v in raw.items())
                        row_adjusted = row_adjusted and bool(adjusted) and all(v == CHECKS.get(k, True) for k, v in adjusted.items())
                    semantic = [s for j in changes for s in j.get('semantic_failures', [])]
                    row_adjusted = row_adjusted and not semantic
                    raw_pass, adjusted_pass = raw_pass and row_raw, adjusted_pass and row_adjusted
                    signatures.append({'where': row.get('where'), 'outcome': row.get('outcome'),
                                       'checks': [s.get('checks', {}) for s in steps],
                                       'cards': [s.get('card_items', []) for s in steps],
                                       'tools': [[t['name'] for t in s.get('tools', [])] for s in steps]})
                    flags = [f for s in steps for f in s.get('review', {}).get('candidate_issues', [])]
                    if not row_adjusted or flags or m['suite'] == 'safety':
                        review.append({'run': folder.name, 'id': id, 'where': row.get('where'),
                                       'architecture': m['architecture'], 'suite': m['suite'],
                                       'raw_pass': bool(row_raw), 'adjusted_pass': bool(row_adjusted),
                                       'semantic_flags': flags, 'row': row})
                    if not row_adjusted:
                        failures.append({'where': row.get('where'), 'execution_ok': bool(ok),
                                         'semantic_failures': semantic})
                cases.append({'run': folder.name, 'architecture': m['architecture'],
                              'suite': m['suite'], 'id': id, 'repetition': rep,
                              'raw_pass': bool(raw_pass), 'adjusted_pass': bool(adjusted_pass),
                              'execution_ok': bool(execution_ok), 'signatures': signatures,
                              'failures': failures})
        spending = db.execute('SELECT stage,status,COUNT(*),COALESCE(SUM(actual),0),SUM(held) FROM calls GROUP BY stage,status').fetchall()
    counts = Counter((c['architecture'], c['repetition'], c['suite'], c['id']) for c in cases)
    duplicates = [key for key, n in counts.items() if n != 1]
    if duplicates:
        raise ValueError('Duplicate primary observations; explicit selection required: ' + str(duplicates))
    expected = Counter((a, rep, suite, id) for a in ('current', 'staged', 'verified')
                       for rep in ('1', '2') for suite, ids in sample.items() for id in ids)
    pairs = defaultdict(dict)
    for case in cases:
        pairs[(case['suite'], case['id'], case['repetition'])][case['architecture']] = case
    disagreements = [{'case': key, 'architectures': architectures}
                     for key, architectures in pairs.items()
                     if len({json.dumps({'signatures': v['signatures'],
                                         'adjusted_pass': v['adjusted_pass'],
                                         'execution_ok': v['execution_ok'],
                                         'failures': v['failures']}, sort_keys=True)
                             for v in architectures.values()}) > 1]
    summary = {}
    for a in ('current', 'staged', 'verified'):
        selected = [c for c in cases if c['architecture'] == a]
        summary[a] = {'cases': len(selected), **{k: sum(c[k] for c in selected)
                     for k in ('raw_pass', 'adjusted_pass', 'execution_ok')}}
    return {'policy': 'Original C1 understanding retains all four provider failures. All 18 original C1 safety prefix cases remain primary, including execution failures. Two never-reached tail cases use common per-case worlds for every architecture and both repetitions; original A/B tail outcomes stay ancillary. Both failed full recoveries are ancillary. No successful-only pooling. See safety-coverage-repair-20261120.json; post-incident amendment, not blind preregistration.',
            'original_incident_runs_retained': sorted(ORIGINAL_C), 'lineage': lineage,
            'summary': summary, 'cases': cases, 'disagreements': disagreements,
            'review_queue': review, 'pending_runs': pending, 'spending': spending,
            'coverage': {'observed': sum(counts.values()), 'expected': sum(expected.values()),
                         'missing': list((expected - counts).elements()),
                         'complete': counts == expected},
            'warning': 'No advancement claim before complete paired coverage and manual flag/disagreement review. Original infrastructure failure sensitivity remains required.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = analyze()
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k in ('summary', 'pending_runs', 'spending')}, indent=2))
