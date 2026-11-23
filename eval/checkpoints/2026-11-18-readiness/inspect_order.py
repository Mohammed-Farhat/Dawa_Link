from dawalink.config import load_settings
from sqlalchemy import create_engine,text
with create_engine(load_settings().database_admin_url).connect() as c:
 print(c.execute(text("select u.email from orders o join pharmacies p on p.id=o.pharmacy_id join users u on u.id=p.owner_user_id where o.ref='R-8DQTK3'")).all())
