"""Free residual negative controls, paired-world reconstruction and output scan."""
import hashlib
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import create_engine, select

from dawalink.config import load_settings
from dawalink.db.models import Product
from dawalink.domain.clock import at_beirut
from dawalink.evals.scan_results import scan
from dawalink.evals.score_understanding import Seen
from dawalink.sim import scenario, world
from dawalink.sim.params import Params
from dawalink.sim.run import STARTS_AT

sys.path.insert(0, str(Path.cwd()))
from tests.unit.evals.test_score_understanding import CONCOR, case, checked, find

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPERIMENT = ROOT/'eval/experiments/architecture-20261118'

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

configs = [json.loads((HERE/'evidence/paired-free'/name/'config.json').read_text())
           for name in ('search','rules','rules_asking')]
assert all(c['seed'] == 1 and c['params'] == configs[0]['params'] for c in configs)
params = Params()
lands = world.load()
engine = create_engine(load_settings().database_migrator_url)
with engine.connect() as connection:
    demand = world.demand_set(connection)
    groups = {r.id: r.equivalence_key or f'product:{r.id}'
              for r in connection.execute(select(Product.id, Product.equivalence_key))}
engine.dispose()
snapshots = []
for contender in ('search','rules','rules_asking'):
    shelves = [world.shelf(p, demand, seed=1, now=at_beirut(params.day, STARTS_AT),
                           early_release_share=params.early_release_share)
               for p in lands.pharmacies]
    day = scenario.build(1, lands, demand, groups, params)
    snapshots.append({'initial_stock_sha256': digest(shelves),
                      'demand_schedule_sha256': digest([asdict(n) for n in day.needs]),
                      'arrival_schedule_sha256': digest([asdict(a) for a in day.arrivals])})
assert snapshots[0] == snapshots[1] == snapshots[2]
fairness = {'same_saved_parameters': True, 'reconstructed_inputs_equal': True,
            'seed': 1, 'requests': len(day.needs), 'arrivals': len(day.arrivals),
            'hashes': snapshots[0], 'answers_after_min': params.answers_after_min,
            'limitation': 'Reconstruction from frozen functions and catalog, not an independent '
            'runtime event log. Conditional reactions differ with contender actions. One seed only.'}
with (HERE/'evidence/fairness-contract.json').open('x') as stream:
    json.dump(fairness, stream, indent=2)

quantity = checked(case(), Seen('Here.', [find(CONCOR, qty=1)], cards=['reserve'],
                               card_items=[{'product_id': CONCOR, 'qty': 3}]))['quantity']
assert quantity is True  # Deliberate negative control: document an unresolved scorer defect.
files, findings = scan(EXPERIMENT/'runs')
with sqlite3.connect(EXPERIMENT/'budget.sqlite') as db:
    ledger = [dict(zip(('status','calls','held_microusd','actual_microusd'), row))
              for row in db.execute('select status,count(*),sum(held),sum(actual) from calls group by status')]
out = {'wrong_final_quantity_accepted': quantity, 'scanned_run_files': files,
       'privacy_findings': [{'file': str(f.file.relative_to(ROOT)), 'kind': f.what,
                            'match': f.text, 'context': f.around} for f in findings],
       'ledger': ledger}
with (HERE/'evidence/residual-audit.json').open('x') as stream:
    json.dump(out, stream, ensure_ascii=False, indent=2)
print('Paired saved parameters and reconstructed initial stock/demand/arrivals: equal')
print('Wrong final quantity accepted:', quantity, '(remaining defect)')
print('New run files scanned:', files, 'heuristic findings:', len(findings))
print('Ledger:', json.dumps(ledger))
