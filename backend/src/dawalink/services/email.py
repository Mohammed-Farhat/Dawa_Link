"""Sending the email outbox (docs/04 SM-12, R-NT; FX-7).

Emails are fixed templates: the LLM never writes one. An email says what happened, then
lists the facts of the event, formatted here: times in Beirut time, prices in LBP with
the approximate USD amount. The reader's address is looked up at the moment of sending
and never stored in the outbox. A failed send is tried again after 1, 5 and 30 minutes,
then given up and logged as an alert.
"""

import smtplib
import string
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from email.message import EmailMessage
from enum import StrEnum
from typing import Any, Protocol

import structlog
from sqlalchemy import select

from dawalink.db.models import CatalogImport, EmailOutbox, User
from dawalink.domain.clock import beirut
from dawalink.domain.money import usd_approx
from dawalink.domain.numbers import EMAIL_RETRY_AFTER, HTTP_TIMEOUT_S
from dawalink.services.context import Tx

log = structlog.get_logger(__name__)

# What each notification says. `{name}` is filled from the notification's payload.
SUBJECTS: dict[str, str] = {
    "CN-3": "Reserved: {order_ref}",
    "CN-5": "Not available: {order_ref}",
    "CN-6": "Reminder: pick up {order_ref} today",
    "CN-7": "Your reservation {order_ref} has expired",
    "CN-8": "Your reservations are paused",
    "CN-9": "A pharmacy can release {product} for you",
    "CN-10": "{product} is available for you",
    "CN-11": "Your watch ended without stock",
    "CN-12": "Your reservation {order_ref} was cancelled",
    "CN-15": "Your request {request_ref}: a plan is ready",
    "CN-16": "Your request {request_ref}: one hour left",
    "CN-17": "Your request {request_ref} is closed",
    "PN-4": "New reservation {order_ref}: put the box aside",
    "PN-7": "Can you release {product}?",
    "PN-8": "Reservation {order_ref} was cancelled: put the box back",
    "PN-10": "Your DawaLink inventory hasn't been updated for a week",
}
FOOTER = "Open DawaLink to see the details.\n\nThis email was sent automatically."
PRESCRIPTION_NOTICE = "Prescription needed: bring it to the pharmacy."
# An order that has ended has no pickup time left to show.
ENDED = frozenset({"CN-5", "CN-7", "CN-12", "PN-8"})
FALLBACK_SUBJECT = "A message from DawaLink"


class MailServerDown(Exception):
    """The mail server can't be reached at all: no email will go through right now."""


class Outcome(StrEnum):
    NOTHING = "nothing"  # not due, already sent, or another worker has it
    SENT = "sent"
    FAILED = "failed"  # this email was refused; the others may still go through
    SERVER_DOWN = "server_down"


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None:
        """Sends one email, or raises: `MailServerDown` when nothing can be sent."""
        ...


class LogSender:
    """Used when no mail server is configured: the email is only noted in the log."""

    def send(self, to: str, subject: str, body: str) -> None:
        log.info("email_logged_only", reason="no mail server configured", subject=subject)


class SmtpSender:
    """A plain SMTP server: the local mail catcher in development."""

    def __init__(self, host: str, port: int, sender: str) -> None:
        self._host, self._port, self._sender = host, port, sender

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self._sender, to, subject
        message.set_content(body)
        try:
            server = smtplib.SMTP(self._host, self._port, timeout=HTTP_TIMEOUT_S)
        except OSError as error:  # refused, timed out, unknown host
            raise MailServerDown(type(error).__name__) from error
        with server:
            server.send_message(message)


def _plain(value: Any, _: Decimal | None) -> str:
    return str(value)


def _moment(value: Any, _: Decimal | None) -> str:
    """A stored moment, in Beirut time: "Tue 20 Oct, 21:00"."""
    return beirut(datetime.fromisoformat(str(value))).strftime("%a %d %b, %H:%M")


def _money(value: Any, lbp_per_usd: Decimal | None) -> str:
    """R-C3: always LBP, with the approximate USD amount when the rate is known."""
    amount = f"{int(value):,} LBP"
    if not lbp_per_usd:
        return amount
    return f"{amount} (about ${usd_approx(int(value), int(lbp_per_usd)):,.2f})"


# What a payload may hold, the label it is shown under, and how it is written. Anything
# else in a payload (IDs, lists, flags) is for the app's screens and stays out of emails.
FACTS: tuple[tuple[str, str, Callable[[Any, Decimal | None], str]], ...] = (
    ("order_ref", "Order number", _plain),
    ("request_ref", "Request", _plain),
    ("product", "Medicine", _plain),
    ("units", "Packs", _plain),
    ("units_not_available", "Packs not available", _plain),
    ("price_lbp", "Price per pack", _money),
    ("suggested_price_lbp", "Suggested price per pack", _money),
    ("pharmacy", "Pharmacy", _plain),
    ("pharmacy_address", "Address", _plain),
    ("open_hours", "Open on the pickup day", _plain),
    ("pickup_by", "Pick up by", _moment),
    ("offer_expires_at", "Offer valid until", _moment),
    ("respond_by", "Please answer by", _moment),
    ("paused_until", "Paused until", _moment),
    ("items_missing", "Medicines still missing", _plain),
)


def missing_fields(template: str, params: dict[str, Any]) -> set[str]:
    """The names a template's subject needs and the payload doesn't give."""
    needed = {
        name for _, name, _, _ in string.Formatter().parse(SUBJECTS.get(template, "")) if name
    }
    return {name for name in needed if params.get(name) in (None, "")}


def render(
    template: str, params: dict[str, Any], lbp_per_usd: Decimal | None = None
) -> tuple[str, str]:
    """The subject and the plain-text body of one email.

    A template we don't know, or one whose payload lacks a name, gets the general subject:
    an email never shows a blank or a placeholder.
    """
    subject = FALLBACK_SUBJECT
    if template in SUBJECTS and not missing_fields(template, params):
        subject = SUBJECTS[template].format_map(params)
    facts = [
        f"{label}: {write(params[name], lbp_per_usd)}"
        for name, label, write in FACTS
        if params.get(name) not in (None, "") and not (name == "pickup_by" and template in ENDED)
    ]
    # The notice is for the client who will go to the counter, while the order is still on.
    if params.get("prescription_required") and template.startswith("CN-") and template not in ENDED:
        facts.append(PRESCRIPTION_NOTICE)
    return subject, "\n\n".join(part for part in (subject, "\n".join(facts), FOOTER) if part)


def display_rate(tx: Tx) -> Decimal | None:
    """The LBP per USD rate stated on the newest imported price list (R-C3)."""
    return tx.session.execute(
        select(CatalogImport.lbp_per_usd).order_by(CatalogImport.source_date.desc()).limit(1)
    ).scalar()


def send_one(tx: Tx, sender: EmailSender, outbox_id: int) -> Outcome:
    """Sends one queued email and records what happened.

    The outbox row stays locked while the email is sent, so two workers never send the
    same one. This is the one place a network call happens inside a transaction: the row
    is only ever touched here, and the sender gives up after N-41.
    """
    email = tx.session.execute(
        select(EmailOutbox)
        .where(EmailOutbox.id == outbox_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar()
    if email is None or email.state not in ("QUEUED", "FAILED") or email.next_attempt_at > tx.now:
        return Outcome.NOTHING
    try:
        # Writing the email is inside the `try` too: one that can't be written must fail
        # on its own, not stop every email queued behind it on each pass.
        address = tx.session.execute(
            select(User.email).where(User.id == email.user_id)
        ).scalar_one()
        subject, body = render(email.template, email.params, display_rate(tx))
        sender.send(address, subject, body)
    except Exception as error:
        down = isinstance(error, MailServerDown)
        email.attempts += 1
        email.last_error = str(error) if down else type(error).__name__
        if email.attempts > len(EMAIL_RETRY_AFTER):
            email.state = "DEAD"
            log.error("email_dead", template=email.template, outbox_id=email.id)
        else:
            email.state = "FAILED"
            email.next_attempt_at = tx.now + EMAIL_RETRY_AFTER[email.attempts - 1]
        return Outcome.SERVER_DOWN if down else Outcome.FAILED
    email.state, email.sent_at, email.last_error = "SENT", tx.now, None
    return Outcome.SENT
