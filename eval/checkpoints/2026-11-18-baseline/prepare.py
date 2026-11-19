"""Prepare ONLY the checkpoint DB, with a reproducible demo clock."""
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine, text
from dawalink.config import load_settings
from dawalink.ops.prepare_db import prepare
from dawalink.ops.seed_demo import seed_demo, set_demo_passwords
settings = load_settings()
assert '@127.0.0.1:55433/evaluation' in settings.database_admin_url
prepare(settings.model_copy(update={'demo_mode':False}))
engine = create_engine(settings.database_migrator_url)
with engine.begin() as conn:
    assert conn.execute(text('select count(*) from pharmacies')).scalar() == 0, 'Already seeded; refuse to overwrite'
    result = seed_demo(conn, seed=42, now=datetime(2026,11,16,10,tzinfo=ZoneInfo('Asia/Beirut')))
    accounts = set_demo_passwords(conn, settings.demo_accounts_password.get_secret_value())
    print(result)
    print('Synthetic accounts with passwords:', accounts)
    print('Products:', conn.execute(text('select count(*) from products')).scalar())
engine.dispose()
