"""Audit current source, primary coverage, review claims and append-only accounting."""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from dawalink.evals.dataset_selection import select_dataset
from dawalink.evals.experiment import fingerprint
from analyze_revised import HERE, ROOT, RUNS, analyze


def audit(require_complete):
    errors = []
    analysis = analyze()
    pin = json.loads((HERE / 'screening-source-freeze.json').read_text())
    if fingerprint() != pin['source_hashes']:
        errors.append('Frozen backend/source fingerprint changed')
    for name, key in [('screening.json', 'sample_sha256'), ('targets.json', 'targets_sha256')]:
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != pin[key]:
            errors.append(name + ' changed')
    select_dataset('expanded')
    reference = json.loads((HERE / 'reference.json').read_text())
    for name, expected in reference['source_hashes'].items():
        if not name.endswith('/turn.py') and hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            errors.append('Reference agent file changed: ' + name)
    handoff = ROOT / 'DawaLink_Roadmap_and_Database_Handoff.md'
    handoff_ok = hashlib.sha256(handoff.read_bytes()).hexdigest() == '0a3e0a09e2e04c1307aa3645d78e044b2ec3954bddb8f5cadc2dc3483b7aff13'
    if not handoff_ok:
        errors.append('Handoff changed')
    authority = json.loads((HERE / 'evidence/owner-approved-caps-20261120e.json').read_text())
    caps = authority['caps_microusd']
    assert sum(caps.values()) == authority['aggregate_microusd'] == 25_000_000
    original = subprocess.check_output(['git', 'show', 'HEAD:eval/experiments/architecture-20261118/budget.sqlite'], cwd=ROOT)
    with sqlite3.connect('file:' + str(RUNS.parent / 'budget.sqlite') + '?mode=ro', uri=True) as db:
        with tempfile.NamedTemporaryFile(suffix='.sqlite') as tmp:
            tmp.write(original)
            tmp.flush()
            with sqlite3.connect(tmp.name) as old:
                old_calls = old.execute('SELECT * FROM calls ORDER BY id').fetchall()
                old_events = old.execute('SELECT * FROM call_events ORDER BY seq').fetchall()
                for row in old_calls:
                    if db.execute('SELECT * FROM calls WHERE id=?', (row[0],)).fetchone() != row:
                        errors.append('Historical call altered: ' + row[0])
                for row in old_events:
                    if db.execute('SELECT * FROM call_events WHERE seq=?', (row[0],)).fetchone() != row:
                        errors.append('Historical event altered: ' + str(row[0]))
        old_ids = {row[0] for row in old_calls}
        historical_snapshots = []
        for snapshot in (HERE / 'evidence/budget-final.sqlite',
                         HERE / 'resume-20261120/budget.sqlite',
                         HERE / 'revised-20261120/budget-final.sqlite'):
            with sqlite3.connect('file:' + str(snapshot) + '?mode=ro', uri=True) as prior:
                prior_calls = prior.execute('SELECT * FROM calls ORDER BY id').fetchall()
                prior_events = prior.execute('SELECT * FROM call_events ORDER BY seq').fetchall()
                for row in prior_calls:
                    if db.execute('SELECT * FROM calls WHERE id=?', (row[0],)).fetchone() != row:
                        errors.append('Sealed prior call altered: ' + row[0])
                for row in prior_events:
                    if db.execute('SELECT * FROM call_events WHERE seq=?', (row[0],)).fetchone() != row:
                        errors.append('Sealed prior event altered: ' + str(row[0]))
                historical_snapshots.append(dict(file=str(snapshot.relative_to(ROOT)),
                                                 calls=len(prior_calls), events=len(prior_events)))
        calls = db.execute('SELECT id,run,stage,held,actual,status FROM calls').fetchall()
        purposes = Counter()
        for id, run, stage, held, actual, status in calls:
            if id in old_ids:
                continue
            events = db.execute('SELECT kind,details FROM call_events WHERE call_id=?', (id,)).fetchall()
            kinds = Counter(kind for kind, _ in events)
            if kinds['request'] != 1:
                errors.append('Missing/duplicate request event: ' + id)
            if status == 'settled':
                if held != actual or kinds['provider_response'] != 1 or kinds['provider_failure']:
                    errors.append('Incorrect settled accounting: ' + id)
            elif status == 'uncertain':
                if held != 645000 or actual is not None or kinds['provider_failure'] != 1:
                    errors.append('Incorrect unknown hold: ' + id)
            elif require_complete or status != 'reserved':
                errors.append('Unexpected call status: ' + id)
            for kind, raw in events:
                if kind == 'request':
                    details = json.loads(raw)
                    purposes[details.get('purpose', 'missing')] += 1
                    if details.get('architecture') not in ('current', 'staged', 'verified') or details.get('model') != 'claude-haiku-5-5' or not details.get('request_sha256'):
                        errors.append('Invalid request metadata: ' + id)
            if stage in ('heldout', 'expanded', 'retries'):
                errors.append('Unexpected non-screening/baseline evaluation call: ' + id)
        stages = dict(db.execute('SELECT stage,SUM(held) FROM calls GROUP BY stage'))
        if sum(stages.values()) > 25_000_000 or any(amount > caps[stage] for stage, amount in stages.items()):
            errors.append('Budget ceiling exceeded')
        unknown = [dict(id=id, run=run, stage=stage, held_microusd=held)
                   for id, run, stage, held, actual, status in calls if status == 'uncertain']
        baseline = [row for row in unknown if row['stage'] == 'baseline']
        if len(baseline) != 6 or sum(row['held_microusd'] for row in baseline) != 3870000:
            errors.append('Original six unknown reservations changed')
        known = sum(actual or 0 for _, _, _, _, actual, _ in calls)
        active = [id for id, _, _, _, _, status in calls if status == 'reserved']
    # Review records are explicit assertions by the implementation assistant;
    # this check validates coverage of those assertions, not independent correctness.
    reviewed_rows = set()
    paths = [HERE / 'evidence/manual-review-coverage.jsonl',
             HERE / 'resume-20261120/manual-review.jsonl',
             *sorted((HERE / 'revised-20261120').glob('*review-coverage.jsonl'))]
    for path in paths:
        for record in map(json.loads, path.read_text().splitlines()):
            if 'rows_reviewed' in record:
                folder = RUNS / record['run']
                rows = [json.loads(line) for file in folder.glob('*/answers.jsonl')
                        for line in file.read_text().splitlines()]
                if not rows:
                    rows = [json.loads(line) for file in folder.glob('*/conversations.jsonl')
                            for line in file.read_text().splitlines()]
                if len(rows) != record['rows_reviewed']:
                    errors.append('Review row-count claim differs: ' + record['run'])
                reviewed_rows.update((record['run'], row['id'], row.get('where')) for row in rows)
            else:
                reviewed_rows.add((record['run'], record['id'], record.get('where')))
                if 'exchanges_reviewed' in record:
                    conversations = [json.loads(line)
                                     for file in (RUNS / record['run']).glob('*/conversations.jsonl')
                                     for line in file.read_text().splitlines()]
                    selected = [row for row in conversations if row['id'] == record['id']]
                    if len(selected) != 1 or len(selected[0].get('exchanges', [])) != record['exchanges_reviewed']:
                        errors.append('Review exchange-count claim differs: ' + record['run'])
    unreviewed = [{'run': row['run'], 'id': row['id'], 'where': row['where']}
                  for row in analysis['review_queue']
                  if (row['run'], row['id'], row['where']) not in reviewed_rows]
    pair_file = HERE / 'revised-20261120/paired-disagreement-review.json'
    pair_records = json.loads(pair_file.read_text())['cases'] if pair_file.exists() else []
    paired_reviewed = {tuple(record['case']) for record in pair_records}
    missing_pairs = [row['case'] for row in analysis['disagreements']
                     if tuple(row['case']) not in paired_reviewed]
    if require_complete:
        if not analysis['coverage']['complete']:
            errors.append('Incomplete360 paired screening coverage')
        if unreviewed:
            errors.append('Unreviewed safety/semantic/failed observations')
        if missing_pairs:
            errors.append('Unreviewed architecture disagreements')
    return dict(integrity_passed=not errors, errors=errors,
                screening_coverage=analysis['coverage'], source_pin_unchanged=fingerprint() == pin['source_hashes'],
                handoff_unchanged=handoff_ok, original_calls_unchanged=len(old_calls),
                original_events_unchanged=len(old_events), new_calls=len(calls) - len(old_calls),
                historical_snapshots_preserved=historical_snapshots,
                purposes=dict(purposes), caps_microusd=caps, known_microusd=known,
                unknown_holds_microusd=sum(row['held_microusd'] for row in unknown),
                committed_microusd=sum(stages.values()), committed_by_stage_microusd=stages,
                unknown_calls=unknown, active_reservations=active,
                unreviewed_required_rows=unreviewed, unreviewed_disagreements=missing_pairs,
                review_limitation='Implementation-assistant review assertions, not human or independent blind validation.',
                scope='Accepted development only. Held-out semantic contents not read. Original raw files, call stages and charges remain unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--allow-incomplete', action='store_true')
    args = parser.parse_args()
    result = audit(not args.allow_incomplete)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({key: result[key] for key in ('integrity_passed', 'errors', 'known_microusd', 'unknown_holds_microusd', 'committed_by_stage_microusd')}, indent=2))
    if result['errors']:
        raise SystemExit(1)
