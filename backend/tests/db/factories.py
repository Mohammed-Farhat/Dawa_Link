"""Small builders for database tests: each inserts one valid row and returns its key.

Every builder takes the few values a test cares about and fills in the rest.
"""

import itertools
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, insert

from dawalink.db.models import (
    CatalogImport,
    Claim,
    ClientProfile,
    Conversation,
    InventoryItem,
    Order,
    Pharmacy,
    Product,
    RequestItem,
    SourcingRequest,
    User,
)

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)  # 10:00 in Beirut
BEIRUT_DISTRICT = 1
_numbers = itertools.count(1)
_REF_LETTERS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _ref(prefix: str) -> str:
    number, letters = next(_numbers), ""
    for _ in range(6):
        number, digit = divmod(number, len(_REF_LETTERS))
        letters = _REF_LETTERS[digit] + letters
    return f"{prefix}-{letters}"


def _insert(connection: Connection, model: type, values: dict[str, Any]) -> Any:
    key = next(iter(model.__table__.primary_key.columns))  # type: ignore[attr-defined]
    return connection.execute(insert(model).values(**values).returning(key)).scalar_one()


def user(connection: Connection, role: str = "client", **values: Any) -> uuid.UUID:
    number = next(_numbers)
    defaults = {
        # Unique across runs too: a few tests commit their rows.
        "email": f"user-{uuid.uuid4().hex[:12]}@example.test",
        "password_hash": "!",
        "role": role,
        "full_name": f"Test User {number}",
    }
    return _insert(connection, User, defaults | values)  # type: ignore[no-any-return]


def client(connection: Connection, status: str = "ACTIVE", **values: Any) -> uuid.UUID:
    user_id = user(connection)
    _insert(
        connection,
        ClientProfile,
        {"user_id": user_id, "status": status, "district_id": BEIRUT_DISTRICT} | values,
    )
    return user_id


def pharmacy(connection: Connection, status: str = "APPROVED", **values: Any) -> uuid.UUID:
    number = next(_numbers)
    defaults = {
        "owner_user_id": user(connection, "pharmacist"),
        "name": f"Test Pharmacy {number}",
        "address": "1 Test Street",
        "license_number": f"TEST-{number}",
        "phone": f"+961 00 {number:06d}",
        "district_id": BEIRUT_DISTRICT,
        "lat": 33.89,
        "lon": 35.50,
        "status": status,
    }
    return _insert(connection, Pharmacy, defaults | values)  # type: ignore[no-any-return]


def catalog_import(connection: Connection) -> uuid.UUID:
    values = {
        "file_name": "test.xls",
        "source_date": TODAY,
        "lbp_per_usd": 89_500,
        "rows_total": 0,
        "rows_imported": 0,
    }
    return _insert(connection, CatalogImport, values)  # type: ignore[no-any-return]


def product(connection: Connection, public_price_lbp: int = 1_000_000, **values: Any) -> uuid.UUID:
    number = next(_numbers)
    defaults = {
        "moph_code": 900_000 + number,
        "import_id": values.pop("import_id", None) or catalog_import(connection),
        "moph_name": f"TESTAMOL {number}",
        "search_name": f"testamol {number}",
        "public_price_lbp": public_price_lbp,
    }
    return _insert(connection, Product, defaults | values)  # type: ignore[no-any-return]


def item(
    connection: Connection,
    *,
    pharmacy_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    days_left: int = 60,
    qty_on_hand: int = 5,
    **values: Any,
) -> uuid.UUID:
    defaults = {
        "pharmacy_id": pharmacy_id or pharmacy(connection),
        "product_id": product_id or product(connection),
        "batch": f"B{next(_numbers)}",
        "expiry_date": TODAY + timedelta(days=days_left),
        "qty_on_hand": qty_on_hand,
    }
    return _insert(connection, InventoryItem, defaults | values)  # type: ignore[no-any-return]


def order(connection: Connection, state: str = "RESERVED", **values: Any) -> uuid.UUID:
    """An order with no stock behind it: enough to test the orders table itself."""
    pharmacy_id = values.pop("pharmacy_id", None) or pharmacy(connection)
    product_id = values.pop("product_id", None) or product(connection)
    is_open = state in ("OFFERED", "RESERVED")
    defaults: dict[str, Any] = {
        "ref": _ref("R"),
        "client_id": values.pop("client_id", None) or client(connection),
        "pharmacy_id": pharmacy_id,
        "inventory_item_id": values.pop("inventory_item_id", None)
        or item(connection, pharmacy_id=pharmacy_id, product_id=product_id),
        "product_id": product_id,
        "source": "search",
        "state": state,
        "qty_requested": 1,
        "qty_locked": 1 if is_open else 0,
        "qty_picked_up": 1 if state == "PICKED_UP" else None,
        "pickup_day": TODAY,
        "price_snapshot_lbp": 600_000,
        "offer_expires_at": NOW + timedelta(hours=2) if state == "OFFERED" else None,
        "deadline": None if state.startswith("OFFER") else NOW + timedelta(hours=11),
        "idempotency_key": f"key-{next(_numbers)}",
    }
    return _insert(connection, Order, defaults | values)  # type: ignore[no-any-return]


def claim(connection: Connection, kind: str = "WATCH", **values: Any) -> uuid.UUID:
    defaults = {
        "kind": kind,
        "client_id": values.pop("client_id", None) or client(connection),
        "product_id": values.pop("product_id", None) or product(connection),
        "qty": 1,
        "qty_missing": 1,
        "ends_at": NOW + timedelta(hours=6),
    }
    return _insert(connection, Claim, defaults | values)  # type: ignore[no-any-return]


def request(connection: Connection, **values: Any) -> uuid.UUID:
    defaults = {
        "ref": _ref("Q"),
        "client_id": values.pop("client_id", None) or client(connection),
        "alternatives_ok": False,
        "ends_at": NOW + timedelta(hours=6),
        "idempotency_key": f"key-{next(_numbers)}",
    }
    return _insert(connection, SourcingRequest, defaults | values)  # type: ignore[no-any-return]


def request_item(connection: Connection, request_id: uuid.UUID, **values: Any) -> uuid.UUID:
    defaults = {
        "request_id": request_id,
        "position": 1,
        "product_id": values.pop("product_id", None) or product(connection),
        "qty": 1,
    }
    return _insert(connection, RequestItem, defaults | values)  # type: ignore[no-any-return]


def conversation(connection: Connection, **values: Any) -> uuid.UUID:
    defaults = {
        "client_id": values.pop("client_id", None) or client(connection),
        "kind": "chat",
        "last_activity_at": NOW,
    }
    return _insert(connection, Conversation, defaults | values)  # type: ignore[no-any-return]
