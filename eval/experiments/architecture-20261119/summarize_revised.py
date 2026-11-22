"""Offline metrics using analyze_revised's explicit primary-observation lineage."""
import argparse
import json
import random
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean

from dawalink.evals.score_understanding import CHECKS
from analyze_revised import HERE, RUNS, analyze


def percentile(values, probability):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * probability
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return round(values[low] + (values[high] - values[low]) * (position - low), 6)


def summarize(analysis):
    adjudications = []
    for path in (HERE / 'evidence/manual-adjudications.jsonl',
                 HERE / 'revised-20261120/manual-adjudications.jsonl'):
        if path.exists():
            adjudications.extend(json.loads(line) for line in path.read_text().splitlines())
    raw_rows = {}
    for run in {case['run'] for case in analysis['cases']}:
        folder = RUNS / run
        manifest = json.loads((folder / 'manifest.json').read_text())
        name = 'conversations.jsonl' if manifest['suite'] == 'multiturn' else 'answers.jsonl'
        raw_rows[run] = [json.loads(line) for file in folder.glob('*/' + name)
                         for line in file.read_text().splitlines()]
    architectures = {}
    for architecture in ('current', 'staged', 'verified'):
        cases = [case for case in analysis['cases'] if case['architecture'] == architecture]
        by_suite = {}
        for suite in ('understanding', 'safety', 'multiturn'):
            subset = [case for case in cases if case['suite'] == suite]
            by_suite[suite] = {'n': len(subset), **{
                key: sum(case[key] for case in subset)
                for key in ('raw_pass', 'adjusted_pass', 'execution_ok')}}
        checks = {'raw': defaultdict(list), 'adjusted': defaultdict(list)}
        latencies = {'all': [], 'with_cards': [], 'without_cards': []}
        safety_interactions = []
        known_microusd = model_calls = 0
        for case in cases:
            for row in raw_rows[case['run']]:
                if row['id'] != case['id']:
                    continue
                changes = [change for change in adjudications
                           if change['run'] == case['run'] and change['id'] == case['id']
                           and change.get('where') == row.get('where')]
                steps = row.get('exchanges') or [row]
                for number, step in enumerate(steps, 1):
                    known_microusd += round(step.get('cost_usd', 0) * 1_000_000)
                    model_calls += step.get('model_calls', 0)
                    raw = {key: value for key, value in step.get('checks', {}).items()
                           if value is not None}
                    adjusted = dict(raw)
                    for change in changes:
                        if change.get('turn') in (None, number):
                            adjusted.update(change.get('overrides', {}))
                    for label, values in (('raw', raw), ('adjusted', adjusted)):
                        for key, value in values.items():
                            # Manual semantic failures can add a quality check to one
                            # safety reply. They must not selectively add applicability
                            # only for that failed reply in per-check rate denominators.
                            if key not in raw:
                                continue
                            checks[label][key].append(value == CHECKS.get(key, True))
                # Understanding rows combine turns for scoring and cost; use their
                # saved individual turn spans for per-turn latency, without double counting.
                if case['suite'] == 'safety':
                    # Safety seconds can include both attack and synthetic follow-up.
                    # Do not label these combined interaction spans as single turns.
                    if row.get('seconds') is not None:
                        safety_interactions.append(row['seconds'])
                    continue
                for turn in row.get('exchanges') or row.get('turns') or [row]:
                    seconds = turn.get('seconds')
                    if seconds is not None:
                        latencies['all'].append(seconds)
                        group = 'with_cards' if turn.get('cards') or turn.get('card_items') else 'without_cards'
                        latencies[group].append(seconds)
        quality = sum(case['adjusted_pass'] for case in cases)
        executed = sum(case['execution_ok'] for case in cases)
        targets = json.loads((HERE / 'targets.json').read_text())['targets']
        target_checks = {}
        for key, minimum in {
            **dict.fromkeys(('product', 'every_item', 'quantity', 'quantity_understood',
                             'proposal_quantity', 'proposal_complete', 'budget',
                             'days_of_use', 'pickup_day', 'situation', 'asks_first',
                             'uses_the_answer', 'asks_for_the_rest', 'shows_a_card'),
                            targets['product_quantity_constraint_completeness_min']),
            'asks_when_it_must': targets['required_clarification_min'],
            'asks_needlessly': 1 - targets['needless_questions_max'],
            'clinical_refusal': targets['clinical_refusal'],
            'refuses_wrongly': 1 - targets['wrong_refusal_max'],
            'language': targets['language_min'],
            'nothing_invented': targets['nothing_invented'],
        }.items():
            values = checks['adjusted'].get(key, [])
            rate = mean(values) if values else None
            target_checks[key] = {'pass': sum(values), 'n': len(values),
                                  'correct_rate': rate, 'minimum_correct_rate': minimum,
                                  'meets_observed_target': rate >= minimum if rate is not None else None}
        with sqlite3.connect('file:' + str(RUNS.parent / 'budget.sqlite') + '?mode=ro', uri=True) as db:
            holds = []
            ledger_known = ledger_calls = 0
            for values in by_suite.values():
                values.update(known_ledger_microusd=0, ledger_model_calls=0)
            for run in sorted({case['run'] for case in cases}):
                known, calls = db.execute('SELECT COALESCE(SUM(actual),0),COUNT(*) FROM calls WHERE run=?', (run,)).fetchone()
                ledger_known += known
                ledger_calls += calls
                suite = next(case['suite'] for case in cases if case['run'] == run)
                by_suite[suite]['known_ledger_microusd'] += known
                by_suite[suite]['ledger_model_calls'] += calls
                holds.extend(dict(id=id, run=run, held_microusd=held, status=status)
                             for id, held, status in db.execute(
                                 "SELECT id,held,status FROM calls WHERE run=? AND status NOT IN ('settled','reconciled')",
                                 (run,)))
        architectures[architecture] = {
            'n': len(cases), 'by_suite': by_suite,
            **{key: sum(case[key] for case in cases)
               for key in ('raw_pass', 'adjusted_pass', 'execution_ok')},
            'traced_primary_row_microusd': known_microusd,
            'traced_primary_row_model_calls': model_calls,
            'known_ledger_microusd_for_primary_runs': ledger_known,
            'ledger_model_calls_for_primary_runs': ledger_calls,
            'unresolved_calls_in_primary_runs': holds,
            'known_run_cost_per_execution_success_case_usd': ledger_known / 1e6 / executed if executed else None,
            'known_run_cost_per_quality_passing_case_usd': ledger_known / 1e6 / quality if quality else None,
            'cost_scope': 'All calls in primary-containing runs, including fixture preparation. A1/B1 original safety runs additionally include their now-ancillary old tail contexts; no exact equal-scope total-cost claim from this aggregate. Understanding and normalized conversation/safety-tail run costs have matched scope.',
            'checks': {label: {key: {'pass': sum(values), 'n': len(values), 'pass_rate': mean(values)}
                               for key, values in by_check.items()}
                       for label, by_check in checks.items()},
            'check_rate_scope': 'Original non-null applicability only, with reviewed values substituted. Additional manual semantic failures still fail the primary case, but do not selectively enlarge per-check denominators.',
            'observed_target_checks': target_checks,
            'by_repetition': {rep: {'n': len(subset), **{
                key: sum(case[key] for case in subset)
                for key in ('raw_pass', 'adjusted_pass', 'execution_ok')}}
                for rep in ('1', '2')
                for subset in [[case for case in cases if case['repetition'] == rep]]},
            'turn_latency_seconds': {label: {'n': len(values), 'p50': percentile(values, .5),
                                             'p95': percentile(values, .95)}
                                     for label, values in latencies.items()},
            'turn_latency_scope': 'Understanding and fixed-conversation individual saved turns only; safety spans excluded because they combine attack and optional follow-up.',
            'safety_interaction_latency_seconds': {'n': len(safety_interactions),
                'p50': percentile(safety_interactions, .5),
                'p95': percentile(safety_interactions, .95)},
        }
    paired = {}
    indexed = {(case['architecture'], case['suite'], case['id'], case['repetition']): case
               for case in analysis['cases']}
    for challenger in ('staged', 'verified'):
        clusters = defaultdict(list)
        successful_only = defaultdict(list)
        for (architecture, suite, id, rep), reference in indexed.items():
            if architecture != 'current':
                continue
            contender = indexed.get((challenger, suite, id, rep))
            if contender is None:
                continue
            difference = int(contender['adjusted_pass']) - int(reference['adjusted_pass'])
            clusters[(suite, id)].append(difference)
            if contender['execution_ok'] and reference['execution_ok']:
                successful_only[(suite, id)].append(difference)
        rng = random.Random(20261119)
        values = list(clusters.values())
        draws = [mean(value for cluster in [rng.choice(values) for _ in values] for value in cluster)
                 for _ in range(10000)] if values else []
        sensitivity_values = list(successful_only.values())
        sensitivity_rng = random.Random(20261119)
        sensitivity_draws = [mean(value for cluster in [sensitivity_rng.choice(sensitivity_values)
                                                       for _ in sensitivity_values]
                                  for value in cluster)
                             for _ in range(10000)] if sensitivity_values else []
        paired[challenger] = {
            'paired_observations': sum(map(len, values)), 'case_clusters': len(values),
            'adjusted_quality_difference': mean(value for cluster in values for value in cluster) if values else None,
            'paired_case_cluster_bootstrap_95': [percentile(draws, .025), percentile(draws, .975)],
            'method': '10000 resamples of suite/case clusters, retaining both repetitions together; seed20261119. Development screening, not simulation-seed inference.',
            'execution_success_sensitivity': {
                'n': sum(map(len, successful_only.values())),
                'difference': mean(value for cluster in successful_only.values() for value in cluster)
                              if successful_only else None,
                'paired_case_cluster_bootstrap_95': [percentile(sensitivity_draws, .025),
                                                     percentile(sensitivity_draws, .975)],
                'warning': 'Post-execution sensitivity only; excluded failures remain in primary scores.'},
        }
    return {'coverage': analysis['coverage'], 'architectures': architectures, 'paired': paired,
            'spending': analysis['spending'],
            'limitations': ['Manual review by implementation assistant, not human or independent blind review.',
                'Traced row costs/call counts omit some fixture preparation and differ in rounding/cache accounting; ledger run totals are authoritative.',
                'Known ledger costs exclude unknown charges. All unresolved holds remain committed. A1/B1 primary-containing safety runs include old ancillary tails; whole-run total cost is not an exact equal-scope comparison.',
                'Failed recovery, ancillary conversation and smoke costs remain charged in full aggregate ledger spending, separately from primary-containing run totals.',
                'Unnecessary-question check measures repeated supplied logistics; other avoidable questions may be missed.',
                'Latency is recorded generation/tool time, excluding suite setup and queues.',
                'No real fulfilled requests, six-hour fulfillment, or simulation-seed intervals measured in screening.',
                'No final advancement before all paired observations and required manual reviews complete.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = summarize(analyze())
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'coverage': {key: value for key, value in result['coverage'].items() if key != 'missing'},
                      'by_suite': {key: value['by_suite'] for key, value in result['architectures'].items()},
                      'paired': result['paired']}, indent=2))
