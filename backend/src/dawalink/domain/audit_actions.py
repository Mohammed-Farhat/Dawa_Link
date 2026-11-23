"""Every kind of event the audit log holds, by its stored code (docs/04 INV-13; docs/03 AS-11).

The code is what is stored (`audit_events.action`) and what other code reads back
(`services/health.py`, `services/requests.py`, `services/pharmacy_profile.py`): it never
changes. The admin's console turns each one into a sentence; this list is how the
website knows them all (`docs/openapi.json`, `AuditAction`).

**Adding an audit event:** add its code here, then a sentence for it on the website
(`strings.admin.audit.actions`). A test reads every `audit.record` of the backend and
fails on a code that is not here (`tests/api/test_admin_lists.py`).
"""

from enum import StrEnum


class AuditAction(StrEnum):
    # A pharmacy's account (SM-1).
    PHARMACY_REGISTERED = "pharmacy.registered"
    PHARMACY_IN_QUEUE = "pharmacy.in_queue"
    PHARMACY_REGISTRATION_EDIT = "pharmacy.registration_edit"
    PHARMACY_RESUBMITTED = "pharmacy.resubmitted"
    PHARMACY_APPROVE = "pharmacy.approve"
    PHARMACY_REJECT = "pharmacy.reject"
    PHARMACY_REQUEST_INFO = "pharmacy.request_info"
    PHARMACY_ADMIN_EDIT = "pharmacy.admin_edit"
    PHARMACY_PIN_CHECKED = "pharmacy.pin_checked"
    PHARMACY_SUSPEND = "pharmacy.suspend"
    PHARMACY_REINSTATE = "pharmacy.reinstate"
    PHARMACY_PHONE_CHANGED = "pharmacy.phone_changed"
    PHARMACY_MOVED = "pharmacy.moved"
    PHARMACY_LISTING_RULE = "pharmacy.listing_rule"
    PHARMACY_SETTINGS = "pharmacy.settings"
    # A pharmacy's stock.
    INVENTORY_ADD = "inventory.add"
    INVENTORY_EDIT = "inventory.edit"
    INVENTORY_UPLOAD_APPLY = "inventory.upload_apply"
    # Reservations and offers (SM-5, SM-6).
    ORDER_RESERVE = "order.reserve"
    ORDER_CANCEL = "order.cancel"
    ORDER_SYSTEM_CANCEL = "order.system_cancel"
    ORDER_PICKED_UP = "order.picked_up"
    ORDER_NOT_AVAILABLE = "order.not_available"
    ORDER_NO_SHOW = "order.no_show"
    ORDER_NO_SHOW_CONTESTED = "order.no_show_contested"
    ORDER_NO_SHOW_CLEARED = "order.no_show_cleared"
    ORDER_OFFER = "order.offer"
    ORDER_ACCEPT_OFFER = "order.accept_offer"
    ORDER_DECLINE_OFFER = "order.decline_offer"
    ORDER_OFFER_EXPIRED = "order.offer_expired"
    ORDER_WITHDRAW = "order.withdraw"
    # A client's account (SM-2).
    CLIENT_REGISTERED = "client.registered"
    CLIENT_REGISTERED_AGAIN = "client.registered_again"
    CLIENT_VERIFIED = "client.verified"
    CLIENT_PAUSE = "client.pause"
    CLIENT_PAUSE_LIFTED = "client.pause_lifted"
    CLIENT_PAUSE_ENDED = "client.pause_ended"
    CLIENT_SUSPEND = "client.suspend"
    CLIENT_REINSTATE = "client.reinstate"
    CLIENT_DELETED = "client.deleted"
    # Requests, watches and early release (SM-7, SM-8).
    CLAIM_CREATE = "claim.create"
    CLAIM_STATE = "claim.state"
    REQUEST_CREATE = "request.create"
    REQUEST_CHANGE_CONSTRAINTS = "request.change_constraints"
    REQUEST_CLOSE = "request.close"
    REQUEST_REOPEN = "request.reopen"
    REQUEST_ITEM_STATE = "request_item.state"
    EARLY_RELEASE_REQUEST = "early_release.request"
    EARLY_RELEASE_CLOSE = "early_release.close"
    EARLY_RELEASE_ASK_STATE = "early_release_ask.state"
    # Escalations and reported answers (SM-9, SM-10).
    ESCALATION_OPEN = "escalation.open"
    ESCALATION_APPEND = "escalation.append"
    ESCALATION_REPLY = "escalation.reply"
    ESCALATION_RESOLVE = "escalation.resolve"
    ANSWER_REPORT_NEW = "answer_report.new"
    ANSWER_REPORT_CONFIRM = "answer_report.confirm"
    ANSWER_REPORT_DISMISS = "answer_report.dismiss"
    ANSWER_REPORT_EXPORT = "answer_report.export"
    # Flags (R-AB): "abuse_flag." and the admin's action.
    ABUSE_FLAG_DISMISS = "abuse_flag.dismiss"
    ABUSE_FLAG_WARN = "abuse_flag.warn"
    ABUSE_FLAG_SUSPEND = "abuse_flag.suspend"
    # Logins, passwords, admins and views of personal details.
    PII_VIEW = "pii.view"
    PII_VIEW_LIMIT = "pii.view_limit"
    LOGIN_LOCKED = "login.locked"
    PASSWORD_CHANGED = "password.changed"
    PASSWORD_RESET = "password.reset"
    ADMIN_CREATED = "admin.created"
    # The demo clock (R-DEMO).
    CLOCK_ADVANCE = "clock.advance"


# The families the audit log's "Kind" filter offers, each by the starts of its codes.
# `request.` is not the start of `request_item.`, nor `early_release.` of
# `early_release_ask.`: each is listed.
KINDS: dict[str, tuple[str, ...]] = {
    "pharmacies": ("pharmacy.",),
    "stock": ("inventory.",),
    "reservations": ("order.",),
    "clients": ("client.",),
    "requests": ("claim.", "request.", "request_item.", "early_release.", "early_release_ask."),
    "escalations": ("escalation.",),
    "reports": ("answer_report.",),
    "flags": ("abuse_flag.",),
    "accounts": ("login.", "password.", "admin.", "pii."),
    "clock": ("clock.",),
}


def kind_of(code: str) -> str | None:
    """The family a code belongs to, or None for a code no family names."""
    for kind, starts in KINDS.items():
        if code.startswith(starts):
            return kind
    return None
