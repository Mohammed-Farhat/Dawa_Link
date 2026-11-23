"""Sending the email outbox (docs/04 SM-12; docs/09 FX-7)."""

import smtplib
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest

from dawalink.config import ConfigError, Settings
from dawalink.domain.orders import OrderSource
from dawalink.services import email, orders
from dawalink.services.notify import Template, notify
from dawalink.services.orders import ReserveLine
from dawalink.worker.__main__ import mailer
from tests.conftest import logged, make_settings
from tests.services.conftest import World
from tests.services.fake_smtp import (
    FakeSmtpServer,
    Login,
    client_context,
    make_certificate,
    server_context,
)


class FakeMailer:
    """Records what would be sent. `down`: the server can't be reached (FX-7).
    `refuses`: addresses the server turns away (FX-9).
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.attempts = 0
        self.down = False
        self.refuses: set[str] = set()

    def send(self, to: str, subject: str, body: str) -> None:
        self.attempts += 1
        if self.down:
            raise email.MailServerDown("ConnectionRefusedError")
        if to in self.refuses:
            raise smtplib.SMTPRecipientsRefused({to: (550, b"not verified")})
        self.sent.append((to, subject, body))


def queue(world: World, user: uuid.UUID, event: str = "one", **payload: Any) -> None:
    tx = world.tx()
    notify(tx, user, Template.WATCH_ENDED, {"product": "Testol 500 mg"} | payload, event=event)
    world.settle(tx)


def outbox(world: World, user: uuid.UUID) -> Any:
    return world.one("SELECT * FROM email_outbox WHERE user_id = :id", id=user)


def address(world: World, user: uuid.UUID) -> str:
    return str(world.one("SELECT email FROM users WHERE id = :id", id=user).email)


class TestSending:
    def test_a_queued_email_is_sent_to_the_users_address(self, world: World) -> None:
        client, mailer = world.make.client(), FakeMailer()
        queue(world, client)

        assert world.clock_tasks(mailer=mailer).send_emails() == 1

        ((to, subject, body),) = mailer.sent
        assert to == address(world, client)
        assert subject == '"Notify me" ended: Testol 500 mg didn\'t appear in time'
        assert body.splitlines()[:3] == [subject, "", "Medicine: Testol 500 mg"]
        row = outbox(world, client)
        assert (row.state, row.attempts, row.last_error) == ("SENT", 0, None)
        assert row.sent_at == world.clock.now()

    def test_an_email_is_sent_once(self, world: World) -> None:
        client, mailer = world.make.client(), FakeMailer()
        queue(world, client)
        tasks = world.clock_tasks(mailer=mailer)

        assert tasks.send_emails() == 1
        assert tasks.send_emails() == 0
        assert len(mailer.sent) == 1

    def test_a_reservation_emails_the_client_and_the_pharmacy(self, world: World) -> None:
        client, mailer = world.make.client(), FakeMailer()
        item = world.make.item(days_left=60)
        tx = world.tx()
        (order,) = orders.reserve(
            tx,
            client_id=client,
            lines=[ReserveLine(item, 1, expected_price_lbp=600_000)],
            pickup_day=tx.today,
            source=OrderSource.SEARCH,
            idempotency_key="a",
        )
        world.settle(tx)

        assert world.clock_tasks(mailer=mailer).send_emails() == 2

        subjects = sorted(subject for _, subject, _ in mailer.sent)
        assert subjects == [
            f"New reservation {order.ref}: put the box aside",
            f"Reserved: {order.ref}",
        ]
        to_client = next(body for _, subject, body in mailer.sent if subject.startswith("Reserved"))
        assert "Address: 1 Test Street" in to_client
        assert "Open on the pickup day: 08:00-21:00" in to_client
        assert "Pick up by: Tue 20 Oct, 21:00" in to_client
        assert "Price per pack: 600,000 LBP" in to_client
        to_pharmacy = next(body for _, subject, body in mailer.sent if subject.startswith("New"))
        assert "Address" not in to_pharmacy

    def test_the_address_is_never_stored_in_the_outbox(self, world: World) -> None:
        client = world.make.client()
        queue(world, client)

        row = outbox(world, client)
        assert address(world, client) not in str(row.params)
        assert address(world, client) not in row.dedupe_key

    def test_without_a_mail_server_the_email_is_only_logged(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = world.make.client()
        queue(world, client)

        assert world.clock_tasks().send_emails() == 1

        (entry,) = logged(caplog, "email_logged_only")
        assert address(world, client) not in str(entry)


class TestFailures:
    def test_a_failed_send_is_tried_again_after_a_minute(self, world: World) -> None:
        client, mailer = world.make.client(), FakeMailer()
        queue(world, client)
        mailer.down = True
        tasks = world.clock_tasks(mailer=mailer)

        assert tasks.send_emails() == 0
        row = outbox(world, client)
        assert (row.state, row.attempts) == ("FAILED", 1)
        assert row.last_error == "ConnectionRefusedError"

        world.later(seconds=59)
        tasks.send_emails()
        assert mailer.attempts == 1  # not yet

        world.later(seconds=1)
        mailer.down = False
        assert tasks.send_emails() == 1
        row = outbox(world, client)
        assert (row.state, row.attempts, row.last_error) == ("SENT", 1, None)

    def test_after_one_five_and_thirty_minutes_it_is_given_up(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """QUEUED → FAILED → retry (1 m, 5 m, 30 m) → DEAD, with an alert in the log."""
        client, mailer = world.make.client(), FakeMailer()
        queue(world, client)
        mailer.down = True
        tasks = world.clock_tasks(mailer=mailer)

        tasks.send_emails()
        for minutes in (1, 5, 30):
            assert outbox(world, client).state == "FAILED"
            world.later(minutes=minutes)
            tasks.send_emails()

        row = outbox(world, client)
        assert (row.state, row.attempts) == ("DEAD", 4)
        assert len(logged(caplog, "email_dead")) == 1

        world.later(days=1)
        tasks.send_emails()
        assert mailer.attempts == 4  # a dead email is never tried again

    def test_a_server_that_is_down_ends_the_pass(self, world: World) -> None:
        """It costs one timeout per pass, not one per email."""
        mailer = FakeMailer()
        for _ in range(3):
            queue(world, world.make.client())
        mailer.down = True

        world.clock_tasks(mailer=mailer).send_emails()

        assert mailer.attempts == 1

    def test_one_refused_address_does_not_stop_the_others(self, world: World) -> None:
        """FX-9: in the SES sandbox, an address that isn't verified is refused."""
        mailer = FakeMailer()
        refused, fine = world.make.client(), world.make.client()
        queue(world, refused)
        queue(world, fine)
        mailer.refuses = {address(world, refused)}

        assert world.clock_tasks(mailer=mailer).send_emails() == 1

        row = outbox(world, refused)
        assert (row.state, row.last_error) == ("FAILED", "SMTPRecipientsRefused")
        assert outbox(world, fine).state == "SENT"

    def test_an_address_that_keeps_refusing_is_given_up_and_the_client_still_has_the_note(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """FX-8: a bounce or an address that doesn't exist. Tried again after 1, 5 and 30
        minutes like any failure, then left; what happened is in the app all along."""
        mailer = FakeMailer()
        gone, fine = world.make.client(), world.make.client()
        queue(world, gone)
        mailer.refuses = {address(world, gone)}
        tasks = world.clock_tasks(mailer=mailer)

        tasks.send_emails()
        for minutes in (1, 5, 30):
            assert outbox(world, gone).state == "FAILED"
            world.later(minutes=minutes)
            tasks.send_emails()
        queue(world, fine)
        sent_after = tasks.send_emails()

        row = outbox(world, gone)
        assert (row.state, row.attempts, row.last_error) == ("DEAD", 4, "SMTPRecipientsRefused")
        assert len(logged(caplog, "email_dead")) == 1
        assert world.notifications(gone) == ["CN-11"]
        # One dead address holds nobody else's email up.
        assert (sent_after, outbox(world, fine).state) == (1, "SENT")

    def test_the_in_app_notification_does_not_depend_on_the_email(self, world: World) -> None:
        client, mailer = world.make.client(), FakeMailer()
        queue(world, client)
        mailer.down = True

        world.clock_tasks(mailer=mailer).send_emails()

        assert world.notifications(client) == ["CN-11"]


class TestRender:
    def test_a_reservation_email_says_where_when_and_how_much(self) -> None:
        """R-NT: order number, pharmacy, address, hours, pick up by, price, the notice.
        Times are in Beirut time and prices in LBP with the USD amount (R-C3).
        """
        subject, body = email.render(
            "CN-3",
            {
                "order_ref": "R-7K3Q2F",
                "product": "Testol 500 mg",
                "pharmacy": "Test Pharmacy",
                "pharmacy_address": "1 Test Street",
                "open_hours": "08:00-21:00",
                "units": 2,
                "price_lbp": 600_000,
                "pickup_by": "2026-10-20T18:00:00+00:00",
                "prescription_required": True,
                "pharmacy_id": "3f0c",
                "items": [{"a": 1}],
            },
            Decimal("89500"),
        )

        assert subject == "Reserved: R-7K3Q2F"
        assert body.splitlines() == [
            "Reserved: R-7K3Q2F",
            "",
            "Order number: R-7K3Q2F",
            "Medicine: Testol 500 mg",
            "Packs: 2",
            "Price per pack: 600,000 LBP (about $6.7)",
            "Pharmacy: Test Pharmacy",
            "Address: 1 Test Street",
            "Open on the pickup day: 08:00-21:00",
            "Pick up by: Tue 20 Oct, 21:00",
            "Prescription needed: bring it to the pharmacy.",
            "",
            "Show the order number at the counter and pay there.",
            "",
            "Open DawaLink to see the details.",
            "",
            "This email was sent automatically.",
        ]

    def test_without_a_rate_the_price_is_in_lbp_only(self) -> None:
        _, body = email.render("CN-3", {"order_ref": "R-7K3Q2F", "price_lbp": 600_000})

        assert "Price per pack: 600,000 LBP" in body.splitlines()

    def test_an_order_that_ended_shows_no_pickup_time_and_no_notice(self) -> None:
        _, body = email.render(
            "CN-7",
            {
                "order_ref": "R-7K3Q2F",
                "pickup_by": "2026-10-20T18:00:00+00:00",
                "prescription_required": True,
            },
        )

        assert "Pick up by" not in body
        assert "Prescription" not in body

    def test_a_pharmacys_email_carries_no_prescription_notice(self) -> None:
        _, body = email.render("PN-4", {"order_ref": "R-7K3Q2F", "prescription_required": True})

        assert "Prescription" not in body

    def test_a_missing_name_never_shows_as_a_blank(self) -> None:
        assert email.missing_fields("CN-3", {"order_ref": ""}) == {"order_ref"}

        subject, _ = email.render("CN-3", {})

        assert subject == "A message from DawaLink"

    def test_an_unknown_template_still_gets_a_subject(self) -> None:
        subject, _ = email.render("XX-1", {})

        assert subject == "A message from DawaLink"

    def test_every_template_has_a_subject(self) -> None:
        # Every notification, and the two account emails (docs/04 R-AU4, R-AU7).
        named = {template.value for template in Template} | set(email.ACCOUNT_EMAILS)
        assert named == set(email.SUBJECTS)


OFFER = {
    "order_ref": "R-7K3Q2F",
    "product": "Testol 500 mg",
    "pharmacy": "Test Pharmacy",
    "units": 1,
    "price_lbp": 600_000,
    "pickup_by": None,
    "prescription_required": True,
    "offer_expires_at": "2026-10-20T10:00:00+00:00",
    "expiry_date": "2027-01-31",
}


class TestOfferEmails:
    """B#12: a held box isn't reserved. Nothing may send the client to the counter with a
    number the pharmacy can't find, and the email must say that the box is lost unless
    they accept it in time."""

    @pytest.mark.parametrize(
        ("template", "subject"),
        [
            ("CN-9", "A pharmacy is holding Testol 500 mg for you: accept it in DawaLink"),
            ("CN-10", "Testol 500 mg is held for you: accept it in DawaLink"),
        ],
    )
    def test_it_says_held_and_to_accept_before_the_time_shown(
        self, template: str, subject: str
    ) -> None:
        shown, body = email.render(template, OFFER, Decimal("89500"))

        assert shown == subject
        first = body.split("\n\n")[1]
        assert first == email.LEADS[template]
        assert first.startswith("It is held for you, not reserved")
        assert '"Accept and reserve" in DawaLink before the time below' in first
        assert "Held for you until: Tue 20 Oct, 13:00" in body.splitlines()

    def test_a_listed_box_goes_to_the_next_person_after_the_time(self) -> None:
        assert email.LEADS["CN-10"].endswith("After that it goes to the next person.")
        # A released box goes back to the pharmacy's private stock instead (R-E6).
        assert email.LEADS["CN-9"].endswith("After that it is no longer held for you.")

    @pytest.mark.parametrize("template", ["CN-9", "CN-10"])
    def test_it_gives_no_order_number_and_no_prescription_line(self, template: str) -> None:
        _, body = email.render(template, OFFER)

        assert "R-7K3Q2F" not in body
        assert "Order number" not in body
        assert "Prescription" not in body

    def test_the_apps_list_says_the_same(self) -> None:
        """The notification and the email share one template (docs/03 CS-12)."""
        lines = email.facts("CN-10", OFFER)

        assert lines[0] == email.LEADS["CN-10"]
        assert "Held for you until: Tue 20 Oct, 13:00" in lines
        assert not any("Order number" in line or "Prescription" in line for line in lines)


class TestNextSteps:
    """B#20: each email ends with one plain next step, and no link (docs/03 CN-)."""

    def test_a_reservation_says_to_show_the_number_and_pay_at_the_counter(self) -> None:
        _, body = email.render("CN-3", {"order_ref": "R-7K3Q2F"})

        assert "Show the order number at the counter and pay there." in body.split("\n\n")

    def test_not_available_says_it_costs_nothing_and_never_counts(self) -> None:
        """R-N2. True whether some packs are still reserved or none."""
        _, body = email.render("CN-5", {"order_ref": "R-7K3Q2F", "units_not_available": 1})

        step = email.NEXT_STEPS["CN-5"]
        assert step in body.split("\n\n")
        assert "never counts as a missed pickup" in step

    NOT_AVAILABLE: ClassVar[dict[str, Any]] = {
        "order_ref": "R-7K3Q2F",
        "units": 3,
        "units_not_available": 1,
        "pickup_by": "2026-10-20T18:00:00+00:00",
        "prescription_required": True,
    }

    def test_some_packs_not_available_still_says_when_to_pick_up_the_rest(self) -> None:
        """A partial [Not available] keeps the order reserved (SM-5 O3): the rest must
        still be collected, so its email keeps the deadline and the prescription line."""
        lines = email.facts("CN-5", self.NOT_AVAILABLE | {"units_still_reserved": 2})

        assert "Packs not available: 1" in lines
        assert "Packs still reserved for you: 2" in lines
        assert "Pick up by: Tue 20 Oct, 21:00" in lines
        assert "Prescription needed: bring it to the pharmacy." in lines

    @pytest.mark.parametrize("still", [0, None])
    def test_all_packs_not_available_shows_no_pickup_time(self, still: int | None) -> None:
        """None: a notification stored before the payload said how many are left."""
        params = self.NOT_AVAILABLE | {"units_not_available": 3, "units_still_reserved": still}

        lines = email.facts("CN-5", params)

        assert not any(line.startswith(("Pick up by", "Packs still reserved")) for line in lines)
        assert "Prescription needed: bring it to the pharmacy." not in lines

    def test_a_missed_pickup_is_called_so_and_says_how_to_contest_it(self) -> None:
        """B#13 and R-N3: "expired" is a box's date; the contest is [I picked it up]."""
        subject, body = email.render("CN-7", {"order_ref": "R-7K3Q2F", "product": "Testol"})

        assert subject == "Missed pickup: R-7K3Q2F"
        assert "expired" not in body.lower()
        assert 'press "I picked it up"' in body.split("\n\n")[-3]

    def test_a_pause_says_why_and_what_still_works(self) -> None:
        _, body = email.render("CN-8", {"paused_until": "2026-10-27T08:00:00+00:00"})

        assert "Paused until: Tue 27 Oct, 10:00" in body
        assert email.NEXT_STEPS["CN-8"] in body
        assert "missed pickups" in email.NEXT_STEPS["CN-8"]

    def test_a_watch_that_ended_offers_to_keep_looking(self) -> None:
        subject, body = email.render("CN-11", {"product": "Testol 500 mg"})

        assert subject == '"Notify me" ended: Testol 500 mg didn\'t appear in time'
        assert "watch" not in subject.lower()
        assert "You can ask DawaLink to keep looking for it." in body

    def test_a_watch_whose_medicine_left_dawalink_never_says_without_stock(self) -> None:
        """R-C6: a medicine that became controlled can't be looked for at all."""
        params = {"product": "Testol 500 mg", "reason": "no_longer_available"}

        subject, body = email.render("CN-11", params)

        assert subject == '"Notify me" ended'
        assert "keep looking" not in body
        assert email.facts("CN-11", params)[-1] == "This medicine is no longer offered on DawaLink."

    @pytest.mark.parametrize("template", sorted(email.NEXT_STEPS))
    def test_no_email_carries_a_link_or_an_address(self, template: str) -> None:
        _, body = email.render(template, {"order_ref": "R-7K3Q2F", "product": "Testol"})

        assert "http" not in body
        assert "www." not in body

    def test_the_lines_of_one_notification_are_all_different(self) -> None:
        """The app's list draws each line under its own text as a key."""
        for template in email.SUBJECTS:
            lines = email.facts(template, OFFER | {"paused_until": OFFER["offer_expires_at"]})
            assert len(lines) == len(set(lines)), template


class TestMomentsAndMoney:
    def test_a_midnight_deadline_is_the_day_before_at_24(self) -> None:
        """B#39: a pharmacy open until midnight. 00:00 on Thursday would send the client
        on Thursday, a day late: the ticket says Wednesday 24:00, and so does the email."""
        _, body = email.render(
            "CN-3", {"order_ref": "R-7K3Q2F", "pickup_by": "2026-11-18T22:00:00+00:00"}
        )

        assert "Pick up by: Wed 18 Nov, 24:00" in body.splitlines()

    def test_a_minute_after_midnight_is_the_new_day(self) -> None:
        _, body = email.render(
            "CN-3", {"order_ref": "R-7K3Q2F", "pickup_by": "2026-11-18T22:01:00+00:00"}
        )

        assert "Pick up by: Thu 19 Nov, 00:01" in body.splitlines()

    @pytest.mark.parametrize(
        ("lbp", "rate", "shown"),
        [
            (600_000, 89_500, "600,000 LBP (about $6.7)"),
            # Exactly half way: up, as the website's toFixed(1) rounds it.
            (225, 100, "225 LBP (about $2.3)"),
            (245, 100, "245 LBP (about $2.5)"),
            (110_500_000, 1_000, "110,500,000 LBP (about $110,500.0)"),
        ],
    )
    def test_dollars_have_one_decimal_like_the_website(
        self, lbp: int, rate: int, shown: str
    ) -> None:
        """B#31: the ticket says "about $2.4", so its email must not say "$2.44"."""
        _, body = email.render("CN-3", {"order_ref": "R-7K3Q2F", "price_lbp": lbp}, Decimal(rate))

        assert f"Price per pack: {shown}" in body.splitlines()


class TestSmtpSender:
    def test_it_hands_the_message_to_the_local_mail_catcher(self) -> None:
        """No user name: no TLS and no login, as mailpit expects (docs/12 §2)."""
        with FakeSmtpServer() as server:
            email.SmtpSender("127.0.0.1", server.port, "DawaLink <no-reply@example.test>").send(
                "someone@example.test", "Hello", "The body."
            )

        (message,) = server.seen.messages
        assert (message["To"], message["Subject"]) == ("someone@example.test", "Hello")
        assert str(message.get_payload()).strip() == "The body."
        assert "STARTTLS" not in server.seen.commands
        assert "AUTH" not in server.seen.commands

    def test_with_a_login_it_asks_for_tls_first_then_logs_in(self, tmp_path: Path) -> None:
        """A#1: Amazon SES refuses a plain connection and a login in clear."""
        certificate, key = make_certificate(tmp_path)
        with FakeSmtpServer(tls=server_context(certificate, key), password="right") as server:
            sender = email.SmtpSender(
                "127.0.0.1",
                server.port,
                "DawaLink <no-reply@example.test>",
                user="smtp-user",
                password="right",
                starttls=True,
                tls=client_context(certificate),
            )
            sender.send("someone@example.test", "Hello", "The body.")

        assert server.seen.logins == [Login("smtp-user", "right", over_tls=True)]
        assert server.seen.commands.index("STARTTLS") < server.seen.commands.index("AUTH")
        assert len(server.seen.messages) == 1

    def test_a_certificate_it_cannot_trust_sends_nothing(self, tmp_path: Path) -> None:
        """The system's own check: the password never goes to a server that isn't SES."""
        certificate, key = make_certificate(tmp_path)
        with FakeSmtpServer(tls=server_context(certificate, key), password="right") as server:
            sender = email.SmtpSender(
                "127.0.0.1",
                server.port,
                "DawaLink <no-reply@example.test>",
                user="smtp-user",
                password="right",
                starttls=True,
            )
            with pytest.raises(email.MailServerDown, match="SSLCertVerificationError"):
                sender.send("someone@example.test", "Hello", "The body.")

        assert server.seen.logins == []
        assert server.seen.messages == []

    def test_a_refused_login_stops_the_pass_and_says_so(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Every email would be refused the same way: it is the server's problem, not one
        email's (FX-7), and someone must fix the settings."""
        with FakeSmtpServer(password="right") as server:
            sender = email.SmtpSender(
                "127.0.0.1",
                server.port,
                "DawaLink <no-reply@example.test>",
                user="smtp-user",
                password="wrong",
            )
            with pytest.raises(email.MailServerDown, match="SMTPAuthenticationError"):
                sender.send("someone@example.test", "Hello", "The body.")

        assert "MAIL" not in server.seen.commands
        (entry,) = logged(caplog, "email_login_refused")
        assert "wrong" not in str(entry)

    @pytest.mark.parametrize("hang_up_at", ["EHLO", "MAIL", "DATA"])
    def test_a_server_that_goes_away_is_reported_as_down(self, hang_up_at: str) -> None:
        with FakeSmtpServer(hang_up_at=hang_up_at) as server:
            sender = email.SmtpSender("127.0.0.1", server.port, "DawaLink <no@example.test>")
            with pytest.raises(email.MailServerDown, match="SMTPServerDisconnected"):
                sender.send("someone@example.test", "Hello", "The body.")

        assert server.seen.messages == []

    def test_a_refused_address_fails_that_email_only(self) -> None:
        """FX-9: in the SES sandbox an address that isn't verified is refused. The others
        must still go, so this is not `MailServerDown`."""
        with FakeSmtpServer(refuses=frozenset({"unknown@example.test"})) as server:
            sender = email.SmtpSender("127.0.0.1", server.port, "DawaLink <no@example.test>")
            with pytest.raises(smtplib.SMTPRecipientsRefused):
                sender.send("unknown@example.test", "Hello", "The body.")
            sender.send("someone@example.test", "Hello", "The body.")

        assert [message["To"] for message in server.seen.messages] == ["someone@example.test"]

    def test_a_server_it_cannot_reach_is_reported_as_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*_: object, **__: object) -> None:
            raise ConnectionRefusedError

        monkeypatch.setattr(smtplib, "SMTP", refuse)

        with pytest.raises(email.MailServerDown, match="ConnectionRefusedError"):
            email.SmtpSender("mail.test", 1025, "DawaLink <no-reply@example.test>").send(
                "someone@example.test", "Hello", "The body."
            )


class TestThroughARealServer:
    """The outbox and the SMTP sender together: SENT means the server took it."""

    def test_a_sent_email_reached_the_server(self, world: World) -> None:
        client = world.make.client()
        queue(world, client)
        with FakeSmtpServer() as server:
            sender = email.SmtpSender("127.0.0.1", server.port, "DawaLink <no@example.test>")
            assert world.clock_tasks(mailer=sender).send_emails() == 1

        (message,) = server.seen.messages
        assert message["To"] == address(world, client)
        assert outbox(world, client).state == "SENT"

    def test_a_server_that_goes_away_leaves_the_email_to_try_again(self, world: World) -> None:
        client = world.make.client()
        queue(world, client)
        with FakeSmtpServer(hang_up_at="DATA") as server:
            sender = email.SmtpSender("127.0.0.1", server.port, "DawaLink <no@example.test>")
            assert world.clock_tasks(mailer=sender).send_emails() == 0

        row = outbox(world, client)
        assert (row.state, row.attempts, row.last_error) == ("FAILED", 1, "SMTPServerDisconnected")


AWS_MAIL = {
    "app_env": "aws",
    # What the rest of an AWS setting needs, so that only the mail settings are judged.
    "website_url": "https://website.example.org",
    "app_secret_key": "kU3n8Qz1rT6vW0yB4dF7hJ2mP5sX9cL0-test-only",
    "smtp_host": "email-smtp.eu-west-1.amazonaws.com",
    "smtp_port": 587,
    "smtp_user": "AKIA-TEST-USER",
    "smtp_password": "a-test-only-smtp-password",
    "email_from": "DawaLink <no-reply@dawalink.example.org>",
}


class TestTheWorkersSender:
    """A#1: what the worker sends email with, from its settings."""

    def settings(self, tmp_path: Path, **overrides: object) -> Settings:
        return make_settings("postgresql+psycopg://unused@127.0.0.1/none", tmp_path, **overrides)

    def test_locally_without_a_server_emails_are_only_logged(self, tmp_path: Path) -> None:
        assert isinstance(mailer(self.settings(tmp_path, smtp_host=None)), email.LogSender)

    def test_the_local_mail_catcher_gets_no_tls_and_no_login(self, tmp_path: Path) -> None:
        with FakeSmtpServer() as server:
            sender = mailer(self.settings(tmp_path, smtp_host="127.0.0.1", smtp_port=server.port))
            sender.send("someone@example.test", "Hello", "The body.")

        assert len(server.seen.messages) == 1
        assert "STARTTLS" not in server.seen.commands

    def test_a_user_name_turns_starttls_on(self, tmp_path: Path) -> None:
        """Before any login: here the server's test certificate isn't trusted, so nothing
        more happens, which is what must happen with a certificate nobody vouches for."""
        certificate, key = make_certificate(tmp_path)
        settings = self.settings(
            tmp_path, smtp_host="127.0.0.1", smtp_user="smtp-user", smtp_password="right"
        )
        with FakeSmtpServer(tls=server_context(certificate, key), password="right") as server:
            sender = mailer(settings.model_copy(update={"smtp_port": server.port}))
            with pytest.raises(email.MailServerDown):
                sender.send("someone@example.test", "Hello", "The body.")

        assert "STARTTLS" in server.seen.commands
        assert server.seen.logins == []

    def test_starttls_can_be_switched_off_locally(self, tmp_path: Path) -> None:
        """A local server with a login and no certificate."""
        with FakeSmtpServer(password="right") as server:
            settings = self.settings(
                tmp_path,
                smtp_host="127.0.0.1",
                smtp_port=server.port,
                smtp_user="smtp-user",
                smtp_password="right",
                smtp_starttls=False,
            )
            mailer(settings).send("someone@example.test", "Hello", "The body.")

        assert server.seen.logins == [Login("smtp-user", "right", over_tls=False)]

    def test_in_aws_a_full_setting_gives_a_real_sender(self, tmp_path: Path) -> None:
        assert isinstance(mailer(self.settings(tmp_path, **AWS_MAIL)), email.SmtpSender)

    @pytest.mark.parametrize(
        ("change", "named"),
        [
            ({"smtp_host": None}, "SMTP_HOST"),
            ({"smtp_port": 1025}, "SMTP_PORT"),
            ({"smtp_port": 465}, "SMTP_PORT"),
            ({"smtp_user": None}, "SMTP_USER and SMTP_PASSWORD"),
            ({"smtp_password": None}, "SMTP_USER and SMTP_PASSWORD"),
            ({"smtp_starttls": False}, "SMTP_STARTTLS"),
            ({"email_from": "DawaLink <no-reply@dawalink.invalid>"}, "EMAIL_FROM"),
            ({"email_from": "nobody"}, "EMAIL_FROM"),
        ],
    )
    def test_in_aws_the_worker_refuses_to_start_without_a_real_sender(
        self, tmp_path: Path, change: dict[str, object], named: str
    ) -> None:
        """An email only written to the log would be recorded as SENT there."""
        settings = self.settings(tmp_path, **(AWS_MAIL | change))

        with pytest.raises(ConfigError, match=named) as refused:
            mailer(settings)

        assert "a-test-only-smtp-password" not in str(refused.value)

    def test_the_default_sender_address_is_refused_in_aws(self, tmp_path: Path) -> None:
        values = {key: value for key, value in AWS_MAIL.items() if key != "email_from"}

        with pytest.raises(ConfigError, match="EMAIL_FROM"):
            mailer(self.settings(tmp_path, **values))


def test_an_email_that_cannot_be_written_never_blocks_the_others(world: World) -> None:
    """It fails on its own, is retried, and is given up: the emails behind it still go."""
    broken, fine, mailer = world.make.client(), world.make.client(), FakeMailer()
    tx = world.tx()
    notify(tx, broken, Template.RESERVED, {"order_ref": "R-7K3Q2F", "pickup_by": "soon"}, event="a")
    world.settle(tx)
    queue(world, fine)
    tasks = world.clock_tasks(mailer=mailer)

    assert tasks.send_emails() == 1

    assert [to for to, _, _ in mailer.sent] == [address(world, fine)]
    row = outbox(world, broken)
    assert (row.state, row.attempts, row.last_error) == ("FAILED", 1, "ValueError")
