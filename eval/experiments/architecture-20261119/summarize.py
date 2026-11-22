"""Offline reproducible aggregates and paired case-cluster intervals, no model calls."""
import argparse
import copy
import json
import random
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean
from dawalink.evals.score_understanding import CHECKS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = ROOT / 'eval/experiments/architecture-20261118/runs'
LEDGER = RUNS.parent / 'budget.sqlite'


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    position = (len(values)-1)*p
    low = int(position)
    high = min(low+1, len(values)-1)
    return round(values[low]*(high-position)+values[high]*(position-low), 4) if high != low else round(values[low], 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    hashes = json.loads((HERE/'screening-source-freeze.json').read_text())['source_hashes']
    excluded = json.loads((HERE/'coverage-repair.json').read_text())['primary_excluded_runs']
    adjudications = [json.loads(l) for l in (HERE/'evidence/manual-adjudications.jsonl').read_text().splitlines()]
    results = defaultdict(lambda: {'cases':{},'run_ids':[],'known_microusd':0,'held_microusd':0,'calls':0,'turn_seconds':[],'card_seconds':[],'answer_seconds':[],'raw_checks':defaultdict(list),'adjusted_checks':defaultdict(list),'by_suite':defaultdict(lambda: {'n':0,'raw_pass':0,'adjusted_pass':0,'execution_ok':0})})
    case_records = []
    for folder in sorted(RUNS.iterdir()):
        if not (folder/'completion.json').exists() or not (folder/'manifest.json').exists():
            continue
        m = json.loads((folder/'manifest.json').read_text())
        if m.get('kind') != 'comparison' or m['hashes'] != hashes or folder.name in excluded:
            continue
        filename = 'conversations.jsonl' if m['suite'] == 'multiturn' else 'answers.jsonl'
        rows = [json.loads(l) for f in folder.glob(f'*/{filename}') for l in f.read_text().splitlines()]
        if len(rows) != m['expected']:
            continue
        a = results[m['architecture']]
        a['run_ids'].append(folder.name)
        with sqlite3.connect(LEDGER) as db:
            actual, held, calls = db.execute('SELECT COALESCE(SUM(actual),0),COALESCE(SUM(held),0),COUNT(*) FROM calls WHERE run=?',(folder.name,)).fetchone()
        a['known_microusd'] += actual
        a['held_microusd'] += held
        a['calls'] += calls
        grouped = defaultdict(list)
        for row in rows:
            steps = row.get('exchanges') or [row]
            changes = [j for j in adjudications if j['run']==folder.name and j['id']==row['id'] and j.get('where')==row.get('where')]
            raw_ok = adjusted_ok = row.get('outcome') == 'ok' and all(s.get('outcome')=='ok' for s in steps)
            execution_ok = raw_ok
            raw_failed, adjusted_failed = [], []
            for index, step in enumerate(steps,1):
                raw = {k:v for k,v in step.get('checks',{}).items() if v is not None}
                adjusted = copy.copy(raw)
                for change in changes:
                    if change.get('turn') in (None,index):
                        adjusted.update(change.get('overrides',{}))
                for name,values,destination in [('raw',raw,'raw_checks'),('adjusted',adjusted,'adjusted_checks')]:
                    for key,value in values.items():
                        a[destination][key].append(value==CHECKS.get(key,True))
                rf = [k for k,v in raw.items() if v!=CHECKS.get(k,True)]
                af = [k for k,v in adjusted.items() if v!=CHECKS.get(k,True)]
                raw_failed += rf
                adjusted_failed += af
                raw_ok = raw_ok and bool(raw) and not rf
                adjusted_ok = adjusted_ok and bool(adjusted) and not af
            semantic = [f for c in changes for f in c.get('semantic_failures',[])]
            adjusted_ok = adjusted_ok and not semantic
            grouped[row['id']].append({'where':row.get('where'),'execution_ok':execution_ok,'raw_pass':raw_ok,'adjusted_pass':adjusted_ok,'raw_failed':raw_failed,'adjusted_failed':adjusted_failed,'semantic_failures':semantic})
            # Seconds are recorded generation/tool spans, not wall-clock queue or DB setup.
            for turn in row.get('exchanges') or row.get('turns') or [row]:
                seconds = turn.get('seconds')
                if seconds is not None:
                    a['turn_seconds'].append(seconds)
                    (a['card_seconds'] if turn.get('cards') or turn.get('card_items') else a['answer_seconds']).append(seconds)
        for case, observations in grouped.items():
            record = {'architecture':m['architecture'],'suite':m['suite'],'id':case,'repetition':m['repetition'],'run':folder.name,'raw_pass':all(o['raw_pass'] for o in observations),'adjusted_pass':all(o['adjusted_pass'] for o in observations),'execution_ok':all(o['execution_ok'] for o in observations),'observations':observations}
            a['cases'][m['suite']+':'+case+':'+m['repetition']] = record
            case_records.append(record)
            s = a['by_suite'][m['suite']]
            s['n'] += 1
            for key in ['raw_pass','adjusted_pass','execution_ok']:
                s[key] += int(record[key])
    for a in results.values():
        cases = list(a.pop('cases').values())
        a['n'] = len(cases)
        for key in ['raw_pass','adjusted_pass','execution_ok']:
            a[key] = sum(c[key] for c in cases)
        for name in ['raw_checks','adjusted_checks']:
            a[name] = {key:{'pass':sum(values),'n':len(values),'rate':mean(values)} for key,values in a[name].items()}
        for name in ['turn_seconds','card_seconds','answer_seconds']:
            values = a.pop(name)
            a[name] = {'n':len(values),'p50':percentile(values,.5),'p95':percentile(values,.95)}
        a['cost_per_adjusted_passing_case_usd'] = a['known_microusd']/1e6/a['adjusted_pass'] if a['adjusted_pass'] else None
    pairs = {}
    for challenger in ['staged','verified']:
        by_arch = defaultdict(dict)
        for c in case_records:
            by_arch[c['architecture']][(c['suite'],c['id'],c['repetition'])] = c
        keys = sorted(set(by_arch['current']) & set(by_arch[challenger]))
        clusters = defaultdict(list)
        for key in keys:
            clusters[key[:2]].append(int(by_arch[challenger][key]['adjusted_pass'])-int(by_arch['current'][key]['adjusted_pass']))
        if clusters:
            rng = random.Random(20261119)
            values = list(clusters.values())
            draws = []
            for _ in range(10000):
                sample = [rng.choice(values) for _ in values]
                draws.append(mean(v for cluster in sample for v in cluster))
            pairs[challenger] = {'paired_observations':len(keys),'case_clusters':len(clusters),'adjusted_quality_difference':mean(v for cluster in values for v in cluster),'paired_case_cluster_bootstrap_95':[percentile(draws,.025),percentile(draws,.975)],'method':'10000 bootstrap resamples of suite/case, carrying both repetitions together; seed 20261119. Development screening only, not simulation-seed inference.'}
    with sqlite3.connect(LEDGER) as db:
        spending = db.execute('SELECT stage,status,COUNT(*),COALESCE(SUM(actual),0),SUM(held) FROM calls GROUP BY stage,status').fetchall()
    output = {'architectures':dict(results),'paired':pairs,'case_records':case_records,'spending':spending,'manual_adjudications':adjudications,'limitations':['Manual review by implementation assistant, not human or independent blind review.','Mixed-language English/Arabic/Arabizi accepted; unrequested French and English-only responses to Arabizi are language failures.','Repeated screening observations are paired and clustered by case, not 120 independent requests.','Offline development cases do not measure six-hour fulfillment or successful real reservations.']}
    with args.output.open('x') as stream:
        json.dump(output,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in output.items() if k in ['architectures','paired','spending']},indent=2))

if __name__ == '__main__':
    main()
