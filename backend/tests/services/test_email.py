"""Sending the email outbox (docs/04 SM-12; docs/09 FX-7)."""

import smtplib
import uuid
from decimal import Decimal
from typing import Any

import pytest

from dawalink.domain.orders import OrderSource
from dawalink.services import email, orders
from dawalink.services.notify import Template, notify
from dawalink.services.orders import ReserveLine
from tests.conftest import logged
from tests.services.conftest import World


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
        assert subject == "Your watch ended without stock"
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
            "Price per pack: 600,000 LBP (about $6.70)",
            "Pharmacy: Test Pharmacy",
            "Address: 1 Test Street",
            "Open on the pickup day: 08:00-21:00",
            "Pick up by: Tue 20 Oct, 21:00",
            "Prescription needed: bring it to the pharmacy.",
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
        assert {template.value for template in Template} == set(email.SUBJECTS)


class TestSmtpSender:
    def test_it_hands_the_message_to_the_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handed: list[Any] = []

        class Server:
            def __init__(self, host: str, port: int, timeout: float) -> None:
                handed.append((host, port, timeout))

            def __enter__(self) -> "Server":
                return self

            def __exit__(self, *error: object) -> None:
                return None

            def send_message(self, message: Any) -> None:
                handed.append(message)

        monkeypatch.setattr(smtplib, "SMTP", Server)

        email.SmtpSender("mail.test", 1025, "DawaLink <no-reply@example.test>").send(
            "someone@example.test", "Hello", "The body."
        )

        where, message = handed
        assert where == ("mail.test", 1025, 10)
        assert (message["To"], message["Subject"]) == ("someone@example.test", "Hello")
        assert message.get_content().strip() == "The body."

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
