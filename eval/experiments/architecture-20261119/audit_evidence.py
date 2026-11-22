"""Read-only final integrity audit; does not select or read held-out case contents."""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from dawalink.evals.budget import CAPS, TOTAL
from dawalink.evals.dataset_selection import select_dataset
from dawalink.evals.experiment import fingerprint

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = ROOT/'eval/experiments/architecture-20261118/runs'
LEDGER = RUNS.parent/'budget.sqlite'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--allow-incomplete',action='store_true')
    args = parser.parse_args()
    freeze = json.loads((HERE/'screening-source-freeze.json').read_text())
    sample = json.loads((HERE/'screening.json').read_text())
    reference = json.loads((HERE/'reference.json').read_text())
    excluded = json.loads((HERE/'coverage-repair.json').read_text())['primary_excluded_runs']
    errors, runs = [], []
    if fingerprint() != freeze['source_hashes']:
        errors.append('current source drift')
    for name, key in [('screening.json','sample_sha256'),('targets.json','targets_sha256')]:
        if hashlib.sha256((HERE/name).read_bytes()).hexdigest() != freeze[key]:
            errors.append(name+' drift')
    select_dataset('expanded')  # verifies accepted development hashes, including attribution inputs
    unchanged_reference = []
    for name, expected in reference['source_hashes'].items():
        if name.endswith('/turn.py'):
            continue
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            errors.append('unexpected reference agent change: '+name)
        unchanged_reference.append(name)
    observations = 0
    signatures = Counter()
    case_coverage = Counter()
    for folder in sorted(RUNS.iterdir()):
        if not (folder/'manifest.json').exists():
            continue
        m = json.loads((folder/'manifest.json').read_text())
        if m.get('kind') != 'comparison' or m['hashes'] != freeze['source_hashes'] or folder.name in excluded:
            continue
        signatures[(m['architecture'],m['repetition'],m['suite'])] += 1
        filename = 'conversations.jsonl' if m['suite']=='multiturn' else 'answers.jsonl'
        rows = [json.loads(l) for p in folder.glob('*/'+filename) for l in p.read_text().splitlines()]
        ids = Counter(r['id'] for r in rows)
        case_coverage.update((m['architecture'],m['repetition'],m['suite'],id) for id in ids)
        wanted = {m['argv'][m['argv'].index('--cases')+1]} if m['suite']=='multiturn' else set(sample['cases'][m['suite']])
        if set(ids) != wanted:
            errors.append(folder.name+' wrong case IDs')
        if len(rows) != m['expected']:
            errors.append(folder.name+' missing raw observations')
        if m['suite']=='safety':
            accepted = {r['id']:r for r in map(json.loads,(ROOT/'eval/development-v2/scored/safety.jsonl').read_text().splitlines())}
            if Counter((r['id'],r['where']) for r in rows) != Counter((id,where) for id in ids for where in accepted[id]['where']):
                errors.append(folder.name+' wrong safety contexts')
        elif any(n!=1 for n in ids.values()):
            errors.append(folder.name+' duplicate case')
        if not (folder/'completion.json').exists():
            errors.append(folder.name+' missing completion')
        observations += len(rows)
        runs.append(folder.name)
    expected = Counter({(a,rep,s):10 if s=='multiturn' else 1 for a in ['current','staged','verified'] for rep in ['1','2'] for s in ['understanding','safety','multiturn']})
    complete = signatures == expected
    if not complete and not args.allow_incomplete:
        errors.append('not exactly 72 primary screening invocations')
    expected_cases = Counter((a,rep,s,id) for a in ['current','staged','verified'] for rep in ['1','2'] for s,ids in sample['cases'].items() for id in ids)
    complete = complete and case_coverage == expected_cases
    if case_coverage != expected_cases and not args.allow_incomplete:
        errors.append('not exactly 360 paired case observations')
    purposes = Counter()
    incident = json.loads((HERE/'evidence/provider-incident.json').read_text())
    allowed_uncertain = {c['id'] for c in incident['new_uncertain_calls']}
    with sqlite3.connect(LEDGER) as db:
        new_calls = db.execute('SELECT id,run,status,held,actual FROM calls WHERE run LIKE "20261119%"').fetchall()
        for id,run,status,held,actual in new_calls:
            events = db.execute('SELECT kind,details FROM call_events WHERE call_id=?',(id,)).fetchall()
            kinds = Counter(k for k,_ in events)
            accounting_ok = (status=='settled' and kinds['provider_response']==1) or (
                id in allowed_uncertain and status=='uncertain' and kinds['provider_failure']==1
                and held==645000 and actual is None)
            if kinds['request'] != 1 or not accounting_ok:
                errors.append('unreconciled new call or missing accounting event '+id)
            for kind, raw in events:
                d=json.loads(raw)
                if kind=='request':
                    purposes[d.get('purpose','missing')] += 1
                    if d.get('architecture') not in ['current','staged','verified'] or d.get('model')!='claude-haiku-5-5' or not d.get('request_sha256'):
                        errors.append('invalid request metadata '+id)
            if status=='settled' and held!=actual:
                errors.append('settled reserve mismatch '+id)
        spending = db.execute('SELECT stage,status,COUNT(*),COALESCE(SUM(actual),0),SUM(held) FROM calls GROUP BY stage,status').fetchall()
        stage_sums = dict(db.execute('SELECT stage,SUM(held) FROM calls GROUP BY stage').fetchall())
        if sum(stage_sums.values()) > TOTAL or any(n > CAPS[s] for s,n in stage_sums.items()):
            errors.append('budget ceiling exceeded')
        historical_holds = db.execute('SELECT id,run,stage,held FROM calls WHERE status="uncertain" AND run NOT LIKE "20261119%"').fetchall()
        if len(historical_holds)!=6 or sum(r[3] for r in historical_holds)!=3870000:
            errors.append('historical uncertain reservations changed')
        original = subprocess.check_output(['git','show','HEAD:eval/experiments/architecture-20261118/budget.sqlite'],cwd=ROOT)
        with tempfile.NamedTemporaryFile(suffix='.sqlite') as tmp:
            tmp.write(original);tmp.flush()
            with sqlite3.connect(tmp.name) as old:
                original_calls = old.execute('SELECT id,run,stage,held,actual,status,created FROM calls ORDER BY id').fetchall()
                for row in original_calls:
                    current = db.execute('SELECT id,run,stage,held,actual,status,created FROM calls WHERE id=?',(row[0],)).fetchone()
                    if current!=row:errors.append('historical call altered '+row[0])
                original_events = old.execute('SELECT seq,call_id,kind,details,created FROM call_events ORDER BY seq').fetchall()
                for row in original_events:
                    if db.execute('SELECT seq,call_id,kind,details,created FROM call_events WHERE seq=?',(row[0],)).fetchone()!=row:
                        errors.append('historical event altered '+str(row[0]))
    output={'errors':errors,'integrity_passed':not errors,'screening_complete':complete,'eligible_runs':runs,'suite_signatures':{'/'.join(k):v for k,v in signatures.items()},'missing_invocations':sum((expected-signatures).values()),'missing_case_observations':sum((expected_cases-case_coverage).values()),'raw_observations':observations,'development_case_observations':sum(case_coverage.values()),'unchanged_reference_files':unchanged_reference,'new_calls':len(new_calls),'purposes':dict(purposes),'spending':spending,'historical_uncertain_holds':historical_holds,'original_calls_unchanged':len(original_calls),'original_events_unchanged':len(original_events),'scope':'Only accepted development case bodies inspected. Existing source fingerprint hashes original dataset files without semantic held-out inspection. Incomplete coverage is explicit, never a passed comparison.'}
    with args.output.open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps(output,indent=2))
    if errors:
        raise SystemExit(1)

if __name__=='__main__':main()
