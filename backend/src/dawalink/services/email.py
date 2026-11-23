"""Sending the email outbox (docs/04 SM-12, R-NT; FX-7).

Emails are fixed templates: the LLM never writes one. An email says what happened, then
lists the facts of the event, formatted here: times in Beirut time, prices in LBP with
the approximate USD amount, and ends with one plain next step. The reader's address is
looked up at the moment of sending and never stored in the outbox. A failed send is tried
again after 1, 5 and 30 minutes, then given up and logged as an alert. Delivery is at
least once: if the commit after a send fails, the email goes again on the next pass.
"""

import smtplib
import ssl
import string
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from email.message import EmailMessage
from enum import StrEnum
from typing import Any, Protocol

import structlog
from sqlalchemy import select

from dawalink.db.models import CatalogImport, ClientProfile, EmailOutbox, User
from dawalink.domain.accounts import ClientStatus
from dawalink.domain.clock import beirut
from dawalink.domain.money import usd_approx
from dawalink.domain.numbers import EMAIL_RETRY_AFTER, HTTP_TIMEOUT_S, RESET_LINK_VALID
from dawalink.domain.vocabulary import OutboxState
from dawalink.services.context import Tx

log = structlog.get_logger(__name__)

# What each notification says. `{name}` is filled from the notification's payload.
SUBJECTS: dict[str, str] = {
    "CN-1": "Confirm your email for DawaLink",
    "CN-18": "You already have a DawaLink account",
    "CN-19": "Set a new password for DawaLink",
    "CN-20": "Your DawaLink password was changed",
    "CN-3": "Reserved: {order_ref}",
    "CN-5": "Not available: {order_ref}",
    "CN-6": "Reminder: {order_ref} is reserved for you",
    # "Expired" is kept for a box's expiry date: a reservation nobody collected is a
    # missed pickup, as the profile and the admin's screens say (BLD-D45).
    "CN-7": "Missed pickup: {order_ref}",
    "CN-8": "Your reservations are paused",
    # An offer is held, not reserved: it is lost unless the client accepts it in time.
    "CN-9": "A pharmacy is holding {product} for you: accept it in DawaLink",
    "CN-10": "{product} is held for you: accept it in DawaLink",
    # "Notify me", the client's word for a watch (docs/11 §8).
    "CN-11": '"Notify me" ended: {product} didn\'t appear in time',
    "CN-12": "Your reservation {order_ref} was cancelled",
    # The reply itself stays in the app: a person typed it, and an email is a template.
    "CN-14": "DawaLink's team answered you",
    "CN-15": "Your request {request_ref}: a plan is ready",
    "CN-16": "Your request {request_ref}: one hour left",
    "CN-17": "Your request {request_ref} is closed",
    "PN-1": "We received your pharmacy's registration",
    "PN-2": "Your pharmacy is approved on DawaLink",
    "PN-3": "Your pharmacy's registration was not accepted",
    "PN-12": "Your pharmacy on DawaLink is {account_state}",
    "PN-13": "We need more information about your pharmacy's registration",
    "PN-4": "New reservation {order_ref}: put the box aside",
    "PN-7": "Can you release {product}?",
    "PN-8": "Reservation {order_ref} was cancelled: put the box back",
    "PN-10": "Your DawaLink inventory hasn't been updated for a week",
}
FOOTER = "Open DawaLink to see the details.\n\nThis email was sent automatically."
PRESCRIPTION_NOTICE = "Prescription needed: bring it to the pharmacy."
# An order that has ended has no pickup time left to show.
ENDED = frozenset({"CN-5", "CN-7", "CN-12", "PN-8"})
# A held box (O7, O8) has no order number to show at the counter yet, and nobody should
# go to the pharmacy for it before accepting: no number, no prescription line.
OFFERS = frozenset({"CN-9", "CN-10"})
FALLBACK_SUBJECT = "A message from DawaLink"
# A watch that ended because its medicine left DawaLink (R-C6), not for want of stock.
NO_LONGER_OFFERED = "no_longer_available"

# Said before the facts: what the client must do for the email to mean anything. Worded
# as a rule, because the app's list shows the same line after the client has accepted.
HELD_LINE = (
    'It is held for you, not reserved: it is yours only if you tap "Accept and reserve" in '
    "DawaLink before the time below."
)
LEADS: dict[str, str] = {
    # A released box nobody accepts goes back to the pharmacy's private stock (R-E6).
    "CN-9": f"{HELD_LINE} After that it is no longer held for you.",
    # A listed box goes to the next person waiting, or back on the listings (R-PRI).
    "CN-10": f"{HELD_LINE} After that it goes to the next person.",
}
# Said after the facts: one plain next step (docs/03 CN-). No link and no web address:
# an email names DawaLink, and the account emails are the only ones with a link.
NEXT_STEPS: dict[str, str] = {
    "CN-3": "Show the order number at the counter and pay there.",
    # R-N2: a [Not available] never counts against the client. A partial mark keeps the
    # rest reserved, so the line must be true whether some packs are still held or none.
    "CN-5": (
        "You pay nothing for the packs that weren't there, and this never counts as a "
        "missed pickup. To find them elsewhere, search again or ask DawaLink."
    ),
    # R-N3: the contest is on the reservation's own page.
    "CN-7": (
        "Missed pickups can pause your reservations. If you did pick it up, open this "
        'reservation in DawaLink and press "I picked it up".'
    ),
    # SM-2: a paused client still searches and chats, and can't reserve.
    "CN-8": (
        "This is because of missed pickups. Until then you can still search and ask the "
        "assistant, but you can't reserve."
    ),
    "CN-11": "You can ask DawaLink to keep looking for it.",
}
NO_LONGER_OFFERED_SUBJECT = '"Notify me" ended'
NO_LONGER_OFFERED_STEP = "This medicine is no longer offered on DawaLink."
# The account emails say something of their own, and hold the only links we send besides
# "open DawaLink" (docs/04 R-AU4, R-AU7, R-AU9). `{link}` is added when the email is
# written: a confirmation or reset link's token is made at that moment and never stored.
# An email with no path has no link.
ACCOUNT_EMAILS: dict[str, tuple[str, str | None]] = {
    "CN-1": (
        "Welcome to DawaLink. Open this link to confirm your email address, then log in "
        "with your password. The link works once, for 24 hours:\n\n{link}\n\n"
        "If you didn't create a DawaLink account, ignore this email.",
        "/verify-email?token={token}",
    ),
    "CN-18": (
        "Someone tried to create a DawaLink account with this email address. You already "
        "have one: just log in.\n\n{link}\n\n"
        "If that wasn't you, there is nothing to do.",
        "/login",
    ),
    "CN-19": (
        "Someone asked to set a new password for your DawaLink account. Open this link to "
        "choose one. It works once, for "
        f"{int(RESET_LINK_VALID.total_seconds() // 60)} minutes:\n\n{{link}}\n\n"
        "If you didn't ask, ignore this email: your password stays as it is.",
        "/reset-password?token={token}",
    ),
    # No link in it, and nothing about the request: what happened, and what to do if it
    # wasn't the account's owner.
    "CN-20": (
        "The password of your DawaLink account was changed on {when}, with a link sent to "
        "this email address. Every device that was logged in is logged out.\n\n"
        "If this wasn't you, set a new password at once: on DawaLink's login page, press "
        '"Forgot your password?".',
        None,
    ),
}


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
    """An SMTP server: the local mail catcher in development, Amazon SES in AWS.

    With a user name it logs in, after STARTTLS when `starttls` is set: SES refuses a
    login in clear (docs/12 §9). Without one it just hands the email over, as the local
    mail catcher expects.

    What stops every email (no connection, no TLS, a refused login or sender, a server
    that goes away) is `MailServerDown`, which ends the pass. What stops this email only
    (a refused address, a refused message) is raised as it is, so the others still go
    through (FX-9).
    """

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        *,
        user: str | None = None,
        password: str | None = None,
        starttls: bool = False,
        tls: ssl.SSLContext | None = None,
    ) -> None:
        self._host, self._port, self._sender = host, port, sender
        self._user, self._password, self._starttls = user, password, starttls
        # smtplib's own default doesn't check the server's certificate: this one does.
        # Tests give a context that trusts their own certificate.
        self._tls = tls or ssl.create_default_context()

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self._sender, to, subject
        message.set_content(body)
        try:
            server = smtplib.SMTP(self._host, self._port, timeout=HTTP_TIMEOUT_S)
        except OSError as error:  # refused, timed out, unknown host
            raise MailServerDown(type(error).__name__) from error
        try:
            self._open(server)
            self._hand_over(server, message)
        finally:
            _close_quietly(server)

    def _open(self, server: smtplib.SMTP) -> None:
        """TLS and the login. Any failure here is the server's, never one email's."""
        try:
            if self._starttls:
                server.starttls(context=self._tls)
            if self._user is not None:
                server.login(self._user, self._password or "")
        except smtplib.SMTPAuthenticationError as error:
            # A wrong user name or password: nothing will be sent until someone fixes it.
            log.error("email_login_refused", host=self._host, code=error.smtp_code)
            raise MailServerDown(type(error).__name__) from error
        except OSError as error:  # SMTP errors, TLS errors and lost connections alike
            raise MailServerDown(type(error).__name__) from error

    def _hand_over(self, server: smtplib.SMTP, message: EmailMessage) -> None:
        try:
            server.send_message(message)
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPSenderRefused) as error:
            # Gone mid-way, or our own From address refused: no email gets through.
            raise MailServerDown(type(error).__name__) from error
        except smtplib.SMTPException:
            raise  # this address or this message: the others may still go through
        except OSError as error:  # the connection reset or timed out
            raise MailServerDown(type(error).__name__) from error


def _close_quietly(server: smtplib.SMTP) -> None:
    """Say goodbye if the server is still there. A failure here changes nothing sent."""
    try:
        server.quit()
    except OSError:
        server.close()


def _plain(value: Any, _: Decimal | None) -> str:
    return str(value)


def _moment(value: Any, _: Decimal | None) -> str:
    """A stored moment, in Beirut time: "Tue 20 Oct, 21:00".

    Midnight is the end of the day before, "Wed 18 Nov, 24:00", as the ticket and a
    pharmacy's opening hours write it: "Thu 19 Nov, 00:00" would send a client a day late.
    """
    local = beirut(datetime.fromisoformat(str(value)))
    if (local.hour, local.minute) == (0, 0):
        return f"{local - timedelta(minutes=1):%a %d %b}, 24:00"
    return local.strftime("%a %d %b, %H:%M")


def _money(value: Any, lbp_per_usd: Decimal | None) -> str:
    """R-C3: always LBP, with the approximate USD amount when the rate is known.

    The dollars have one decimal, rounded as the website rounds them (docs/11 §8), so a
    ticket and its email say the same "about $2.4".
    """
    amount = f"{int(value):,} LBP"
    if not lbp_per_usd:
        return amount
    usd = usd_approx(int(value), int(lbp_per_usd))
    # The exact value of the float, half up: what the website's toFixed(1) does.
    shown = Decimal(usd).quantize(Decimal("0.1"), ROUND_HALF_UP)
    return f"{amount} (about ${shown:,})"


# What a payload may hold, the label it is shown under, and how it is written. Anything
# else in a payload (IDs, lists, flags) is for the app's screens and stays out of emails.
FACTS: tuple[tuple[str, str, Callable[[Any, Decimal | None], str]], ...] = (
    ("order_ref", "Order number", _plain),
    ("request_ref", "Request", _plain),
    ("product", "Medicine", _plain),
    ("units", "Packs", _plain),
    ("units_not_available", "Packs not available", _plain),
    ("units_still_reserved", "Packs still reserved for you", _plain),
    ("price_lbp", "Price per pack", _money),
    ("suggested_price_lbp", "Suggested price per pack", _money),
    ("pharmacy", "Pharmacy", _plain),
    ("pharmacy_address", "Address", _plain),
    ("open_hours", "Open on the pickup day", _plain),
    ("pickup_by", "Pick up by", _moment),
    ("offer_expires_at", "Held for you until", _moment),
    ("respond_by", "Please answer by", _moment),
    ("paused_until", "Paused until", _moment),
    ("items_missing", "Medicines still missing", _plain),
    # What DawaLink's team wrote to a pharmacy about its registration (PN-3, PN-13).
    ("team_message", "From DawaLink's team", _plain),
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
    an email never shows a blank or a placeholder. The body is the subject, what to do
    first (an offer), the facts, the next step, and the footer.
    """
    subject = _subject(template, params)
    parts = (
        subject,
        LEADS.get(template, ""),
        "\n".join(_fact_lines(template, params, lbp_per_usd)),
        _next_step(template, params),
        FOOTER,
    )
    return subject, "\n\n".join(part for part in parts if part)


def facts(template: str, params: dict[str, Any], lbp_per_usd: Decimal | None = None) -> list[str]:
    """What a notification says besides its title, one line each: the same lines in the
    email and in the app's list. What to do first, the facts, then the next step."""
    lead, step = LEADS.get(template, ""), _next_step(template, params)
    return [
        *([lead] if lead else []),
        *_fact_lines(template, params, lbp_per_usd),
        *([step] if step else []),
    ]


def _withdrawn_watch(template: str, params: dict[str, Any]) -> bool:
    return template == "CN-11" and params.get("reason") == NO_LONGER_OFFERED


def _subject(template: str, params: dict[str, Any]) -> str:
    if _withdrawn_watch(template, params):
        return NO_LONGER_OFFERED_SUBJECT
    if template in SUBJECTS and not missing_fields(template, params):
        return SUBJECTS[template].format_map(params)
    return FALLBACK_SUBJECT


def _next_step(template: str, params: dict[str, Any]) -> str:
    """One plain line saying what the reader can do now, or "" when nothing is to do."""
    if _withdrawn_watch(template, params):
        return NO_LONGER_OFFERED_STEP
    return NEXT_STEPS.get(template, "")


def _fact_lines(template: str, params: dict[str, Any], lbp_per_usd: Decimal | None) -> list[str]:
    """The facts of the event, one per line ("Order number: R-7K3Q2F")."""

    on = _still_on(template, params)

    def shown(name: str) -> bool:
        if params.get(name) in (None, ""):
            return False
        if name == "pickup_by" and not on:
            return False
        if name == "units_still_reserved" and not on:
            return False
        # A held box has no order number at the counter until it is accepted.
        return not (name == "order_ref" and template in OFFERS)

    lines = [
        f"{label}: {write(params[name], lbp_per_usd)}"
        for name, label, write in FACTS
        if shown(name)
    ]
    # The notice is for the client who will go to the counter, while the order is still on.
    going = template.startswith("CN-") and on and template not in OFFERS
    if params.get("prescription_required") and going:
        lines.append(PRESCRIPTION_NOTICE)
    return lines


def _still_on(template: str, params: dict[str, Any]) -> bool:
    """Whether the order still has packs to pick up.

    A [Not available] for some packs only (CN-5) keeps the rest reserved: its email still
    says when to come and to bring the prescription. A stored notification written before
    the payload said so counts as ended, which is what it said then.
    """
    if template == "CN-5":
        still = params.get("units_still_reserved")
        return isinstance(still, int) and still > 0
    return template not in ENDED


def display_rate(tx: Tx) -> Decimal | None:
    """The LBP per USD rate stated on the newest imported price list (R-C3)."""
    return tx.session.execute(
        select(CatalogImport.lbp_per_usd).order_by(CatalogImport.source_date.desc()).limit(1)
    ).scalar()


def _account_email(tx: Tx, email: EmailOutbox, website_url: str) -> tuple[str, str]:
    """An account email: a confirmation or a reset link, "you already have an account",
    or "your password was changed"."""
    # Imported here: the login module queues emails, and this one writes its links.
    from dawalink.services import auth

    words, path = ACCOUNT_EMAILS[email.template]
    # The token a link carries is made now, in the table of its own kind.
    mint = {"CN-1": auth.new_verification_token, "CN-19": auth.new_reset_token}.get(email.template)
    link = ""
    if path is not None:
        token = mint(tx, email.user_id) if mint is not None else ""
        link = website_url.rstrip("/") + path.format(token=token)
    changed_at = email.params.get("changed_at")
    when = _moment(changed_at, None) if changed_at else "a moment ago"
    subject = SUBJECTS[email.template]
    text = words.format(link=link, when=when)
    body = "\n\n".join((subject, text, "This email was sent automatically."))
    return subject, body


def _recipient_deleted(tx: Tx, email: EmailOutbox) -> bool:
    status = tx.session.execute(
        select(ClientProfile.status).where(ClientProfile.user_id == email.user_id)
    ).scalar()
    return status == ClientStatus.DELETED.value


def send_one(tx: Tx, sender: EmailSender, outbox_id: int, website_url: str = "") -> Outcome:
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
    if _recipient_deleted(tx, email):
        # Never sent, and nothing is minted for it (R-AU10). The deletion drops what was
        # waiting; this catches one queued a moment later, by a turn that was running.
        email.state, email.last_error = OutboxState.DROPPED.value, None
        return Outcome.NOTHING
    try:
        # Writing the email is inside the `try` too: one that can't be written must fail
        # on its own, not stop every email queued behind it on each pass.
        address = tx.session.execute(
            select(User.email).where(User.id == email.user_id)
        ).scalar_one()
        if email.template in ACCOUNT_EMAILS:
            subject, body = _account_email(tx, email, website_url)
        else:
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
