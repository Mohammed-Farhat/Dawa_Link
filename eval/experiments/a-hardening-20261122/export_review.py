"""Select all required flags and a reproducible conversation sample; no verdicts implied."""
import argparse
import hashlib
import json
import random
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
RUNS=ROOT/'eval/experiments/architecture-20261118/runs'


def failed(row):
    # asks_again/needless/refuses_wrongly are negative predicates; most are positive.
    negative={'asks_again','asks_needlessly','refuses_wrongly'}
    checks=row.get('checks',{})
    return any(v is not None and bool(v)!=(k not in negative) for k,v in checks.items()) or (
        row.get('outcome','ok')!='ok' or row.get('review',{}).get('review_needed',False))


def export(run_ids):
    selected=[];conversations=[];coverage=[]
    for run_id in run_ids:
        folder=RUNS/run_id
        manifest=json.loads((folder/'manifest.json').read_text())
        suite=manifest['suite']
        paths=sorted(folder.glob('*/answers.jsonl'))+sorted(folder.glob('*/conversations.jsonl'))
        if not paths:
            paths=sorted(folder.glob('*/case-checkpoints.jsonl'))
        row_count=sum(len(p.read_text().splitlines()) for p in paths)
        completion=json.loads((folder/'completion.json').read_text()) if (folder/'completion.json').exists() else None
        coverage.append(dict(run=run_id,suite=suite,expected=manifest['expected'],observed_rows=row_count,
                             execution_status=completion['status'] if completion else 'in_progress',
                             source_hashes=manifest['hashes'],partial=row_count!=manifest['expected']))
        for path in paths:
            for n,line in enumerate(path.read_text().splitlines(),1):
                row=json.loads(line)
                record=dict(run=run_id,suite=suite,id=row['id'],where=row.get('where'),
                            raw_file=str(path.relative_to(ROOT)),raw_line=n,
                            raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            context=row,reviewer=None,review_origin=None,verdict=None,
                            human_reviewed=False,independent=False)
                flag=failed(row) or any(failed(t) for t in row.get('turns',[])) or any(failed(e) for e in row.get('exchanges',[]))
                record['flagged']=flag
                if suite=='conversations':conversations.append(record)
                if suite=='safety' or suite=='multiturn' or flag:
                    record['selection_reason']='all_safety' if suite=='safety' else 'all_fixed_conversations' if suite=='multiturn' else 'automatic_or_semantic_flag'
                    selected.append(record)
    complete=sorted([r for r in conversations if r['context'].get('ended') in ('cards','client_left','too_long')],key=lambda r:(r['run'],r['id']))
    sample=random.Random(20261122).sample(complete,min(50,len(complete)))
    existing={(r['run'],r['id'],r['where']) for r in selected}
    for r in sample:
        if (r['run'],r['id'],r['where']) not in existing:
            r['selection_reason']='seed_20261122_conversation_sample';selected.append(r)
    return selected,dict(seed=20261122,coverage=coverage,completed_played_conversations=len(complete),sampled_played_conversations=len(sample),
                         sampled_ids=[{'run':r['run'],'id':r['id']} for r in sample],
                         reviewer_status='Unreviewed selection. Assistant review must remain labeled; no independent acceptance.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('runs',nargs='+');args=parser.parse_args()
    args.output.mkdir(exist_ok=False)
    records,meta=export(args.runs)
    (args.output/'pack.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    (args.output/'selection.json').write_text(json.dumps(meta,indent=2)+'\n')
