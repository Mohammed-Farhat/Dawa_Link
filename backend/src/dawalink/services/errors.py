"""Why a service refused, as a stable code (docs/06 §3.2).

Code and tests depend on the code only, never on the message.
"""

from enum import StrEnum
from typing import Any


class Code(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    # Accounts
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"
    CLIENT_PAUSED = "CLIENT_PAUSED"
    PHARMACY_NOT_APPROVED = "PHARMACY_NOT_APPROVED"
    # Reservations and offers
    LISTING_NOT_AVAILABLE = "LISTING_NOT_AVAILABLE"
    NOT_ENOUGH_STOCK = "NOT_ENOUGH_STOCK"
    PRICE_CHANGED = "PRICE_CHANGED"
    LIMIT_OPEN_ORDERS = "LIMIT_OPEN_ORDERS"
    LIMIT_GROUP_UNITS = "LIMIT_GROUP_UNITS"
    GROUP_ITEM_FAILED = "GROUP_ITEM_FAILED"
    RESERVATION_NOT_ACTIVE = "RESERVATION_NOT_ACTIVE"
    OFFER_NOT_OPEN = "OFFER_NOT_OPEN"
    NOT_CONTESTABLE = "NOT_CONTESTABLE"
    DOES_NOT_FIT = "DOES_NOT_FIT"
    PICKUP_DAY_INVALID = "PICKUP_DAY_INVALID"
    # Requests and watches
    OUTSIDE_REQUEST_HOURS = "OUTSIDE_REQUEST_HOURS"
    LIMIT_OPEN_REQUESTS = "LIMIT_OPEN_REQUESTS"
    LIMIT_WATCHES = "LIMIT_WATCHES"
    LIMIT_EARLY_RELEASE = "LIMIT_EARLY_RELEASE"
    WATCH_EXISTS = "WATCH_EXISTS"
    PRODUCT_NOT_ALLOWED = "PRODUCT_NOT_ALLOWED"
    REQUEST_CLOSED = "REQUEST_CLOSED"
    CLAIM_NOT_ACTIVE = "CLAIM_NOT_ACTIVE"
    # Pharmacy
    PICKUP_DEADLINE_PASSED = "PICKUP_DEADLINE_PASSED"
    UNITS_INVALID = "UNITS_INVALID"
    ASK_NOT_OPEN = "ASK_NOT_OPEN"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UPLOAD_NOT_VALIDATED = "UPLOAD_NOT_VALIDATED"
    ITEM_EXISTS = "ITEM_EXISTS"
    PRICE_ABOVE_PUBLIC = "PRICE_ABOVE_PUBLIC"


class ServiceError(Exception):
    """A rule said no. Nothing was changed: the caller rolls the transaction back.

    `details` holds what the client may be told (an available quantity, a date), never
    anything about another client or a pharmacy's private stock.
    """

    def __init__(self, code: Code, message: str, **details: Any) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.message = message
        self.details = details
