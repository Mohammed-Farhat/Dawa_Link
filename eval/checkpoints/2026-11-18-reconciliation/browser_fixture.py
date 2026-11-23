"""Disposable browser fixture. Free scripted model; production agent/API unchanged."""
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dawalink.agent.llm.base import ToolResults, UserText
from dawalink.agent.llm.scripted import call, reply
from dawalink.agent.turn import Agent
from dawalink.api.main import create_app
from dawalink.config import load_settings
from dawalink.db.models import InventoryItem, Pharmacy, Product, User
from dawalink.db.session import make_engine
from dawalink.domain.clock import at_beirut
from dawalink.ops.seed_demo import seed_demo, set_demo_passwords
from dawalink.services.clock_check import ClockTasks
from dawalink.sim import database

HERE = Path(__file__).resolve().parent
STATE = HERE / "browser-state.json"
NAME = "dawalink_sim_browser_reconciliation_1811"
NOW = at_beirut(date(2026, 11, 16), time(10))


def settings():
    original = load_settings()
    assert "127.0.0.1:55433/evaluation" in original.database_url
    urls = database.addresses(original).on(NAME)
    return original.model_copy(update={
        "database_admin_url": urls.admin, "database_migrator_url": urls.migrator,
        "database_url": urls.app, "database_retention_url": urls.retention,
    })


class FileClock:
    def now(self):
        return datetime.fromisoformat(json.loads(STATE.read_text())["now"])


class BrowserModel:
    name = "scripted"

    def complete(self, prompt, *, timeout_s):
        state = json.loads(STATE.read_text())
        last = prompt.messages[-1]
        if isinstance(last, ToolResults):
            result = json.loads(last.results[-1].content)
            if "proposal_id" in result:
                return reply("Review this proposal. Nothing is reserved until you approve.",
                             proposal_ids=[result["proposal_id"]])
            return reply("The fixture tool could not make that proposal.")
        if state["phase"] == "request":
            return call("prepare_request_summary", items=[{
                "product_id": state["empty_product_id"], "qty": 1, "days_of_use": 7,
            }], alternatives_ok=False)
        assert isinstance(last, UserText)
        if state["phase"] == "clarify":
            return reply("Which pickup day, for how many days, and do you drive or walk?")
        return call("propose_reservation", listing_id=state["listing_id"],
                    pickup_day="2026-11-16", days_of_use=7)


def make():
    config = settings()
    engine = make_engine(config.database_url)
    sessions = sessionmaker(engine, expire_on_commit=False)
    clock = FileClock()
    agent = Agent(sessions, clock, BrowserModel())
    return create_app(config, agent=agent, clock=clock, sessions=sessions)


def main():
    action = sys.argv[1]
    original = load_settings()
    if action == "init":
        assert not STATE.exists()
        urls = database.fresh(original, NAME)
        engine = create_engine(urls.migrator)
        with engine.begin() as connection:
            seed_demo(connection, seed=42, now=NOW)
            set_demo_passwords(connection, original.demo_accounts_password.get_secret_value())
        with sessionmaker(engine)() as session:
            listing, product = session.execute(
                select(InventoryItem, Product).join(Product).join(Pharmacy).join(
                    User, User.id == Pharmacy.owner_user_id
                ).where(
                    User.email == "pharmacy02@demo.dawalink.test",
                    Product.controlled.is_(False), InventoryItem.qty_on_hand >= 3,
                    InventoryItem.expiry_date >= date(2026, 11, 30),
                    InventoryItem.expiry_date <= date(2027, 4, 30),
                ).order_by(InventoryItem.id)
            ).first()
            stocked = select(InventoryItem.product_id)
            empty = session.scalars(select(Product).where(
                Product.controlled.is_(False), Product.id.not_in(stocked)
            ).order_by(Product.moph_code)).first()
            state = {"now": NOW.isoformat(), "phase": "reserve",
                     "listing_id": str(listing.id), "product": product.moph_name,
                     "empty_product_id": str(empty.id), "empty_product": empty.moph_name}
        with STATE.open("x") as stream:
            json.dump(state, stream, indent=2)
        engine.dispose()
        print(json.dumps(state))
    elif action in ("clarify", "reserve", "request"):
        state = json.loads(STATE.read_text())
        state["phase"] = action
        STATE.write_text(json.dumps(state))
        print(action, "phase selected")
    elif action == "timeout":
        state = json.loads(STATE.read_text())
        state["now"] = (NOW + timedelta(hours=6, minutes=1)).isoformat()
        STATE.write_text(json.dumps(state))
        config = settings()
        engine = make_engine(config.database_url)
        tasks = ClockTasks(sessionmaker(engine), FileClock())
        print("Expired request windows:", tasks.end_windows())
        engine.dispose()
    else:
        raise ValueError(action)


if __name__ == "__main__":
    main()
