"""Offline matched-world and paired-seed comparison; never infer reliability from one seed."""
import argparse
import json
import random
import sqlite3
import statistics
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
RUNS=ROOT/'eval/experiments/architecture-20261118/runs'


def read(run):
    folder=RUNS/run
    manifest=json.loads((folder/'manifest.json').read_text())
    summaries=list(folder.glob('*/summary.json'))
    if len(summaries)!=1:
        return {'run':run,'complete':False,'reason':'missing or multiple summaries'}
    output=summaries[0].parent
    summary=json.loads(summaries[0].read_text())
    config=json.loads((output/'config.json').read_text())
    initial=json.loads((output/'initial-inputs.json').read_text())
    needs=[json.loads(s) for s in (output/'needs.jsonl').read_text().splitlines()]
    events=[json.loads(s) for s in (output/'events.jsonl').read_text().splitlines()]
    completion=json.loads((folder/'completion.json').read_text())
    with sqlite3.connect(f'file:{RUNS.parent / "budget.sqlite"}?mode=ro',uri=True) as db:
        cost,unsettled=db.execute("SELECT COALESCE(SUM(actual),0),SUM(CASE WHEN status NOT IN ('settled','reconciled') THEN 1 ELSE 0 END) FROM calls WHERE run=?",(run,)).fetchone()
    fulfilled=sum(n['units_secured']>=n['units_wanted'] for n in needs)
    spans=[]
    trace=output/'turns.jsonl'
    if trace.exists():
        for line in trace.read_text().splitlines():
            t=json.loads(line);spans.append(sum(s['seconds'] for s in t['spans']))
    latency=sorted(spans)
    secured_times=sorted(n['minutes_to_secure'] for n in needs if n.get('minutes_to_secure') is not None)
    return dict(run=run,contender=config['contender'],seed=config['seed'],
                request_coverage_complete=len(needs)==100 and len({n['n'] for n in needs})==100,
                complete=(len(needs)==100 and len({n['n'] for n in needs})==100
                          and summary.get('needs')==100 and completion.get('error_type') is None
                          and completion['status']=='complete' and not unsettled), cost_complete=not unsettled,
                full_world_finished=(len(needs)==100 and len({n['n'] for n in needs})==100
                                     and summary.get('needs')==100
                                     and completion.get('error_type') is None and not unsettled),
                execution_coverage_status=completion['status'],initial=initial,
                source_hashes=manifest['hashes'],
                arrivals=[{k:v for k,v in e.items() if k!='applied'} for e in events if e['kind']=='stock_arrival'],
                draws={json.dumps([e['kind'],e['key']],sort_keys=True):e['value'] for e in events if e['kind'] in ('draw','delay')},
                metrics=dict(units_secured=sum(n['units_secured'] for n in needs),
                             fully_served_requests=fulfilled,
                             median_simulated_minutes_to_fulfill=statistics.median(secured_times) if secured_times else None,
                             p95_simulated_minutes_to_fulfill=secured_times[max(0,int(len(secured_times)*.95+.999)-1)] if secured_times else None,
                             client_interactions=sum(n['taps']+n['messages'] for n in needs),
                             execution_failures=summary.get('turns',{}).get('turns_not_ok',0),
                             api_known_usd=cost/1e6,
                             api_usd_per_fulfilled_request=cost/1e6/fulfilled if fulfilled else None,
                             turn_latency_p50_s=statistics.median(latency) if latency else None,
                             turn_latency_p95_s=latency[max(0, int(len(latency)*.95+.999)-1)] if latency else None),
                legitimate_action_dependent_differences='Actions change asks, holds, reactions and reachable inventory. Common keyed draws must agree; absent action keys need not occur.')


def compare(run_ids):
    rows=[read(r) for r in run_ids]
    groups={}
    for r in rows:
        if 'seed' in r:
            contenders=groups.setdefault(r['seed'],{})
            if r['contender'] in contenders:
                raise ValueError('Duplicate contender/seed attempt: report attempts separately')
            contenders[r['contender']]=r
    pairs=[];differences={};full_world_differences={}
    for seed,contenders in groups.items():
        a=contenders.get('agent')
        if not a:continue
        for name,b in contenders.items():
            if name=='agent':continue
            shared=set(a['draws'])&set(b['draws'])
            mismatches=[k for k in shared if a['draws'][k]!=b['draws'][k]]
            comparable=a['initial']==b['initial'] and a['arrivals']==b['arrivals'] and not mismatches and a['source_hashes']==b['source_hashes']
            complete=a['complete'] and b['complete']
            full_world=a['full_world_finished'] and b['full_world_finished']
            delta={k:a['metrics'][k]-b['metrics'][k] for k in ('units_secured','fully_served_requests','client_interactions','execution_failures')}
            pairs.append(dict(seed=seed,baseline=name,world_event_comparable=comparable,shared_action_keys=len(shared),draw_mismatches=mismatches,complete_pair=complete,full_world_pair=full_world,delta_A_minus_baseline=delta))
            if comparable and complete:
                for metric,value in delta.items():differences.setdefault((name,metric),[]).append(value)
            if comparable and full_world:
                for metric,value in delta.items():full_world_differences.setdefault((name,metric),[]).append(value)
    def estimates(deltas):
        result=[]
        for (name,metric),values in deltas.items():
            rng=random.Random(20261122)
            boot=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(10000)) if len(values)>1 else None
            result.append(dict(baseline=name,metric=metric,seeds=len(values),paired_mean=statistics.mean(values),paired_95pct_bootstrap_interval=[boot[249],boot[9749]] if boot else None))
        return result
    for r in rows:
        for key in ('draws','arrivals','source_hashes'):r.pop(key,None)
    return dict(runs=rows,pairs=pairs,paired_seed_estimates=estimates(differences),
                secondary_full_world_estimates=estimates(full_world_differences),limitations=['One seed has no cross-world uncertainty estimate.','Simulation behavior is assumption-based, not measured pharmacy/client behavior.','Incomplete runs are retained in run tables and excluded from complete-pair estimates.',
'Secondary full-world estimates include execution failures and turn caps when the entire simulation returned normally with 100 request records and settled costs; these remain separate from strict completed pairs.',
'Units secured are locks obtained within each six-hour window, not proof of dispensing; the simulation includes no-shows.',
'Turn latency sums recorded spans and omits untraced overhead; simulated minutes to fulfillment are a separate measure.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('runs',nargs='+');args=parser.parse_args()
    with args.output.open('x') as f:json.dump(compare(args.runs),f,indent=2);f.write('\n')
