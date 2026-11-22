"""Compact offline inspection of immutable outcomes; no model calls."""
import argparse
import json
from pathlib import Path
from dawalink.evals.score_understanding import CHECKS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = ROOT / 'eval/experiments/architecture-20261118/runs'
p = argparse.ArgumentParser()
p.add_argument('run')
p.add_argument('--start', type=int, default=0)
p.add_argument('--limit', type=int, default=10)
p.add_argument('--case', default='')
a = p.parse_args()
folder = RUNS / a.run
m = json.loads((folder / 'manifest.json').read_text())
filename = 'conversations.jsonl' if m['suite'] == 'multiturn' else 'answers.jsonl'
rows = [json.loads(l) for f in folder.glob(f'*/{filename}') for l in f.read_text().splitlines()]
for r in rows[a.start:a.start+a.limit] if not a.case else [r for r in rows if r['id'] in a.case.split(',')]:
    steps = r.get('exchanges') or [r]
    print(json.dumps({'run':a.run,'architecture':m['architecture'],'suite':m['suite'],
                     'id':r['id'],'where':r.get('where'),'text':r.get('text'),
                     'turns':[{'client':s.get('client'), 'reply':s.get('reply'),
                               'failed':[k for k,v in s.get('checks',{}).items() if v is not None and v != CHECKS.get(k,True)],
                               'flags':s.get('review',{}).get('candidate_issues'),
                               'outcome':s.get('outcome'),
                               'card_facts':sorted({(str(c.get('product_id')),c.get('qty'),c.get('days_of_use')) for c in s.get('card_items',[])}),
                               'actions':[{'name':t['name'],'ok':t.get('ok')} for t in s.get('tools',[]) if t['name'] not in ['search_catalog','find_options','plan_basket','propose_reservation','propose_plan']]}
                              for s in steps]},ensure_ascii=False))
