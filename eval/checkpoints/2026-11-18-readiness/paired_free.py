from pathlib import Path
import json
from dawalink.config import load_settings
from dawalink.sim.run import one
from dawalink.sim.params import Params
root=Path('../eval/checkpoints/2026-11-18-readiness/evidence/paired-free')
root.mkdir(exist_ok=False)
for contender in ('search','rules','rules_asking'):
 result=one(load_settings(),contender,1,Params(),folder=root/contender)
 print(contender,result.summary,flush=True)
fields=('n','client_n','medicines','units_wanted')
rows={name:[{k:r[k] for k in fields} for line in (root/name/'needs.jsonl').read_text().splitlines() if (r:=json.loads(line))] for name in ('search','rules','rules_asking')}
assert rows['search']==rows['rules']==rows['rules_asking']
(root/'paired.json').write_text(json.dumps({'identical_demand':True,'requests':100,'seed':1}))
