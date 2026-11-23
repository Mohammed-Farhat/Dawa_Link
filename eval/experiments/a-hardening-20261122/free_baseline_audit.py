"""Summarize free contenders and verify shared seeded inputs without a paid A run."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
from compare_simulations import read


def audit(runs):
    rows = [read(run) for run in runs]
    if {r.get('contender') for r in rows} != {'search', 'rules', 'rules_asking'} or len(rows) != 3:
        raise ValueError('Exactly one terminal run per free contender required')
    checks = []
    for a, b in itertools.combinations(rows, 2):
        shared = set(a['draws']) & set(b['draws'])
        mismatches = [k for k in sorted(shared) if a['draws'][k] != b['draws'][k]]
        checks.append(dict(contenders=[a['contender'], b['contender']],
                           same_initial_inputs=a['initial'] == b['initial'],
                           same_source=a['source_hashes'] == b['source_hashes'],
                           same_arrivals=a['arrivals'] == b['arrivals'],
                           shared_action_keys=len(shared), draw_mismatches=mismatches))
    passed = all(c['same_initial_inputs'] and c['same_source'] and c['same_arrivals']
                 and not c['draw_mismatches'] for c in checks)
    for row in rows:
        row['initial_sha256'] = hashlib.sha256(json.dumps(row.pop('initial'), sort_keys=True).encode()).hexdigest()
        for key in ('draws', 'arrivals', 'source_hashes'):
            row.pop(key)
    return dict(world_event_comparable=passed, checks=checks, runs=rows,
                paid_A_run_present=False, A_minus_baseline_estimates=[],
                cross_world_uncertainty=None,
                limitations=['One seeded world only; no cross-world interval.',
                             'Incomplete execution stays distinct from full-world coverage.',
                             'Six-hour secured units are locks, not dispensing.',
                             'Shared action keys must match; absent action-dependent keys are legitimate.',
                             'No paid A effect can be inferred from these free baselines.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('runs', nargs='+')
    args = parser.parse_args()
    result = audit(args.runs)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'world_event_comparable': result['world_event_comparable'],
                      'runs': [{k: r[k] for k in ('run', 'contender', 'complete', 'full_world_finished', 'metrics')}
                               for r in result['runs']]}))
