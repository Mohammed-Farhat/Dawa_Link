"""Local-only scripted browser fixture, using the unchanged agent and API."""
import json
from datetime import date, time
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from dawalink.config import load_settings
from dawalink.db.session import make_engine
from dawalink.db.models import InventoryItem, Product, Pharmacy
from dawalink.domain.clock import ManualClock, at_beirut
from dawalink.agent.turn import Agent
from dawalink.agent.llm.scripted import ScriptedModel, reply, call
from dawalink.agent.llm import ToolResults
from dawalink.api.main import create_app

def make():
    settings=load_settings()
    assert '127.0.0.1:55433/evaluation' in settings.database_url
    engine=make_engine(settings.database_url)
    sessions=sessionmaker(engine,expire_on_commit=False)
    with sessions() as s:
        box=s.execute(select(InventoryItem).join(Product).join(Pharmacy).where(
            Product.controlled.is_(False), InventoryItem.qty_on_hand > 2
        ).order_by(InventoryItem.id)).scalars().first()
        assert box
        listing=str(box.id)
        print('Scripted browser fixture listing selected',flush=True)
    def show(prompt):
        result=prompt.messages[-1]
        assert isinstance(result,ToolResults)
        data=json.loads(result.results[-1].content)
        return reply('Here is the reservation proposal. Approve it to reserve.', proposal_ids=[data['proposal_id']])
    model=ScriptedModel(reply('Which pickup day, and for how many days? Do you drive or walk?'),
        call('propose_reservation',listing_id=listing,pickup_day='2026-11-16',days_of_use=7),show)
    agent=Agent(sessions,ManualClock(at_beirut(date(2026,11,16),time(10))),model)
    return create_app(settings,agent=agent,clock=agent.clock,sessions=sessions)
