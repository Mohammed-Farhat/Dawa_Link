from pathlib import Path
import json,collections
root=Path('../eval/checkpoints/2026-11-18-readiness/evidence/paired-free')
for name in ('search','rules','rules_asking'):
 p=root/name/'summary.json'
 if not p.exists():continue
 summary=json.loads(p.read_text())
 print(name,{k:summary[k] for k in ('units_secured','units_wanted','unusable_cards','unusable_after_told')})
 if name=='search':continue
 # Persist examples of client-reported constraints near unusable proposals.
 rows=[json.loads(x) for x in (root/name/'threads.jsonl').read_text().splitlines()]
 examples=[r for r in rows if r.get('author')=='client' and any(w in (r.get('text') or '').lower() for w in ('car','foot','tomorrow','siyyara','bukra'))]
 print('client constraint examples:',examples[:3])
