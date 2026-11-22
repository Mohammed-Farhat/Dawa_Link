"""Isolated synthetic live-model browser fixture; every API call uses canonical ledger.

From backend/: python ../eval/experiments/a-hardening-20261122/live_browser.py init
Then uvicorn live_browser:make --factory --app-dir ../eval/experiments/a-hardening-20261122
--host 127.0.0.1 --port 58000. Environment loaded explicitly in config(), never printed.
"""
import hashlib
import json
import os
import sys
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dawalink.agent.llm.base import LLMRejected
from dawalink.agent.turn import Agent
from dawalink.api.main import create_app
from dawalink.config import load_settings
from dawalink.db.models import InventoryItem, Pharmacy, Product, User
from dawalink.db.session import make_engine
from dawalink.domain.clock import at_beirut
from dawalink.evals import budget, experiment
from dawalink.ops.seed_demo import seed_demo, set_demo_passwords
from dawalink.services.clock_check import ClockTasks
from dawalink.sim import database, save

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
STATE=HERE/'browser-state.json'
NAME='dawalink_sim_a_live_20261122'
NOW=at_beirut(date(2026,11,16),time(10))


def environment():
    for key in list(os.environ):
        if any(s in key for s in ('API_KEY','LANGFUSE','DATABASE_','LLM_','EVAL_','DAWALINK_ARCHITECTURE')):
            del os.environ[key]
    for line in (ROOT/'eval/checkpoints/2026-11-19-git-integration/local.env').read_text().splitlines():
        if line and not line.startswith('#'):
            key,value=line.split('=',1);os.environ[key]=value
    os.environ['DAWALINK_ARCHITECTURE']='current'
    config=load_settings()
    assert '127.0.0.1:55433/evaluation' in config.database_url
    return config


def settings():
    original=environment()
    urls=database.addresses(original).on(NAME)
    return original.model_copy(update=dict(database_admin_url=urls.admin,
        database_migrator_url=urls.migrator,database_url=urls.app,database_retention_url=urls.retention))


class FileClock:
    def now(self):
        return datetime.fromisoformat(json.loads(STATE.read_text())['now'])


def make():
    config=settings()
    pin=json.loads((HERE/'candidate5-pin.json').read_text())
    if experiment.fingerprint()!=pin['source_hashes']:
        raise RuntimeError('Source differs from development candidate')
    state=json.loads(STATE.read_text());folder=HERE/state['evidence']
    os.environ['EVAL_LEDGER']=str(experiment.EXPERIMENT/'budget.sqlite')
    os.environ['EVAL_RUN_ID']=state['run_id'];os.environ['EVAL_STAGE']='expanded'
    budget.CAPS.update(dict(baseline=4000000,screening=10000000,expanded=6000000,heldout=3000000,retries=2000000))
    reserve=budget.Ledger.reserve
    def bounded(ledger,run,stage,amount=budget.HAIKU_RESERVATION):
        if (HERE/'STOP_PAID').exists():raise LLMRejected('Paid work stopped')
        with ledger.connect() as db:
            uncertain={r[0] for r in db.execute("SELECT id FROM calls WHERE status='uncertain'")}
        if uncertain-set(pin['existing_uncertain_ids']):raise LLMRejected('New uncertain charge; stopped')
        return reserve(ledger,run,stage,amount)
    budget.Ledger.reserve=bounded
    key=next(line.split('=',1)[1].strip().strip('"\'') for line in (ROOT/'.env').read_text().splitlines() if line.startswith('ANTHROPIC_API_KEY='))
    engine=make_engine(config.database_url);sessions=sessionmaker(engine,expire_on_commit=False)
    agent=Agent(sessions,FileClock(),budget.EvaluationModel(api_key=key,model='claude-haiku-5-5',effort='medium'),tracer=save.FileTracer(folder))
    return create_app(config,agent=agent,clock=agent.clock,sessions=sessions)


def main():
    action=sys.argv[1]
    if action=='init':
        assert not STATE.exists()
        original=environment();urls=database.fresh(original,NAME)
        engine=create_engine(urls.migrator)
        with engine.begin() as connection:
            seed_demo(connection,seed=42,now=NOW)
            set_demo_passwords(connection,original.demo_accounts_password.get_secret_value())
        with sessionmaker(engine)() as session:
            listing,product=session.execute(select(InventoryItem,Product).join(Product).join(Pharmacy).join(User,User.id==Pharmacy.owner_user_id).where(
                User.email=='pharmacy02@demo.dawalink.test',Product.controlled.is_(False),
                InventoryItem.qty_on_hand>=3,InventoryItem.expiry_date>=date(2026,11,30),InventoryItem.expiry_date<=date(2027,4,30)
            ).order_by(InventoryItem.id)).first()
            empty=session.scalars(select(Product).where(Product.controlled.is_(False),Product.id.not_in(select(InventoryItem.product_id))).order_by(Product.moph_code)).first()
            state=dict(now=NOW.isoformat(),listing_id=str(listing.id),product=product.moph_name,
                       empty_product_id=str(empty.id),empty_product=empty.moph_name,
                       run_id='browser_'+uuid.uuid4().hex,evidence='evidence/browser_'+uuid.uuid4().hex[:12])
        folder=HERE/state['evidence'];folder.mkdir()
        (folder/'manifest.json').write_text(json.dumps(dict(source_hashes=experiment.fingerprint(),
            model='claude-haiku-5-5',effort='medium',stage='expanded',run_id=state['run_id'],
            fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),synthetic_only=True),indent=2)+'\n')
        with STATE.open('x') as f:json.dump(state,f,indent=2)
        engine.dispose();print(json.dumps({k:state[k] for k in ('product','empty_product','evidence')}))
    elif action=='timeout':
        state=json.loads(STATE.read_text());state['now']=(NOW+timedelta(hours=6,minutes=1)).isoformat()
        STATE.write_text(json.dumps(state,indent=2)+'\n')
        config=settings();engine=make_engine(config.database_url)
        tasks=ClockTasks(sessionmaker(engine),FileClock());print('Expired windows:',tasks.end_windows());engine.dispose()
    else:raise ValueError(action)


if __name__=='__main__':main()
