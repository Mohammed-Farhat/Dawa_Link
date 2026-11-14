"""The rest of the constraints, each with a test that tries to break it (docs/05 §10).

`test_schema.py` checks that no constraint is left without a test in this folder.
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, insert, text
from sqlalchemy.exc import IntegrityError

from dawalink.db.models import (
    AbuseFlag,
    AnswerReport,
    ChatMessage,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    EmailOutbox,
    EmailVerificationToken,
    Escalation,
    InventoryUpload,
    InventoryUploadRow,
    Notification,
    PharmacyHours,
    PricingTier,
    Session,
    TravelTimeCache,
)
from tests.db import factories as make
from tests.db.factories import NOW, TODAY


def refused(db: Connection, action: Callable[[], Any], constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint), db.begin_nested():
        action()


def add(db: Connection, model: type, **values: Any) -> None:
    db.execute(insert(model).values(**values))


def twice(db: Connection, action: Callable[[], Any], constraint: str) -> None:
    """The first time is fine; the second breaks the unique rule."""
    action()
    refused(db, action, constraint)


class TestAccountsAndPlaces:
    def test_a_name_has_two_to_eighty_characters(self, db: Connection) -> None:
        refused(db, lambda: make.user(db, full_name="A"), "ck_users_full_name_length")
        refused(db, lambda: make.user(db, full_name="A" * 81), "ck_users_full_name_length")

    def test_failed_logins_are_counted_from_zero(self, db: Connection) -> None:
        refused(db, lambda: make.user(db, failed_logins=-1), "ck_users_failed_logins_not_negative")

    def test_a_login_token_is_stored_once(self, db: Connection) -> None:
        user = make.user(db)
        session = {"user_id": user, "token_hash": b"same-hash", "expires_at": NOW}

        twice(db, lambda: add(db, Session, **session), "uq_sessions_token_hash")
        twice(
            db,
            lambda: add(db, EmailVerificationToken, **session),
            "uq_email_verification_tokens_token_hash",
        )

    def test_a_pin_is_a_real_place(self, db: Connection) -> None:
        refused(db, lambda: make.pharmacy(db, lat=95), "ck_pharmacies_pin_in_range")
        refused(db, lambda: make.pharmacy(db, lon=-181), "ck_pharmacies_pin_in_range")

    def test_a_license_and_a_phone_belong_to_one_pharmacy(self, db: Connection) -> None:
        make.pharmacy(db, license_number="L-1", phone="+961 00 111111")

        refused(db, lambda: make.pharmacy(db, license_number="L-1"), "uq_pharmacies_license_number")
        refused(db, lambda: make.pharmacy(db, phone="+961 00 111111"), "uq_pharmacies_phone")

    def test_opening_minutes_start_at_midnight(self, db: Connection) -> None:
        hours = {"pharmacy_id": make.pharmacy(db), "weekday": 0, "seq": 1, "close_minute": 600}

        refused(
            db,
            lambda: add(db, PharmacyHours, **hours, open_minute=-1),
            "ck_pharmacy_hours_open_minute_range",
        )

    def test_a_district_name_is_used_once(self, db: Connection) -> None:
        refused(
            db,
            lambda: db.execute(
                text(
                    "INSERT INTO districts (id, name, governorate, ref_lat, ref_lon) "
                    "VALUES (99, 'Beirut', 'Beirut', 33.9, 35.5)"
                )
            ),
            "uq_districts_name",
        )


class TestCatalogAndStock:
    def test_a_public_price_is_never_negative(self, db: Connection) -> None:
        refused(
            db,
            lambda: make.product(db, public_price_lbp=-1),
            "ck_products_public_price_not_negative",
        )

    def test_a_tier_is_a_valid_range_with_a_percentage(self, db: Connection) -> None:
        refused(
            db,
            lambda: add(db, PricingTier, min_days=600, max_days=500, discount_pct=10),
            "ck_pricing_tiers_days_in_order",
        )
        refused(
            db,
            lambda: add(db, PricingTier, min_days=500, max_days=600, discount_pct=101),
            "ck_pricing_tiers_discount_is_a_percentage",
        )

    def test_a_staged_row_has_no_negative_quantity(self, db: Connection) -> None:
        upload = db.execute(
            insert(InventoryUpload)
            .values(
                pharmacy_id=make.pharmacy(db),
                status="VALIDATED",
                file_name="stock.csv",
                created_by=make.user(db, "pharmacist"),
            )
            .returning(InventoryUpload.id)
        ).scalar_one()
        row = {
            "upload_id": upload,
            "row_no": 1,
            "product_id": make.product(db),
            "batch": "B1",
            "expiry_date": TODAY,
        }

        refused(
            db,
            lambda: add(db, InventoryUploadRow, **row, quantity=-1),
            "ck_inventory_upload_rows_quantity_not_negative",
        )

    def test_a_travel_time_is_never_negative(self, db: Connection) -> None:
        cached = {
            "pharmacy_id": make.pharmacy(db),
            "origin_cell": "33.894,35.502",
            "mode": "car",
            "km": 1.2,
            "source": "road",
            "computed_at": NOW,
        }

        refused(
            db,
            lambda: add(db, TravelTimeCache, **cached, minutes=-1),
            "ck_travel_time_cache_minutes_not_negative",
        )


class TestOrdersAndNeeds:
    def test_units_picked_up_never_exceed_units_asked_for(self, db: Connection) -> None:
        refused(
            db,
            lambda: make.order(db, "PICKED_UP", qty_picked_up=5),
            "ck_orders_qty_picked_up_range",
        )

    def test_a_budget_is_never_negative(self, db: Connection) -> None:
        request = make.request(db)

        refused(db, lambda: make.claim(db, max_price_lbp=-1), "ck_claims_max_price_not_negative")
        refused(
            db,
            lambda: make.request_item(db, request, max_price_lbp=-1),
            "ck_request_items_max_price_not_negative",
        )

    def test_a_request_item_has_one_claim(self, db: Connection) -> None:
        item = make.request_item(db, make.request(db))

        twice(
            db,
            lambda: make.claim(db, "REQUEST_ITEM", request_item_id=item),
            "uq_claims_request_item_id",
        )

    def test_one_tap_makes_one_request_and_a_number_is_used_once(self, db: Connection) -> None:
        client = make.client(db)
        make.request(db, client_id=client, idempotency_key="tap-1", ref="Q-4HX9TM")

        refused(
            db,
            lambda: make.request(db, client_id=client, idempotency_key="tap-1"),
            "uq_sourcing_requests_client_id_idempotency_key",
        )
        refused(db, lambda: make.request(db, ref="Q-4HX9TM"), "uq_sourcing_requests_ref")

    def early_release_request(self, db: Connection, **values: Any) -> Any:
        client = values.pop("client_id", None) or make.client(db)
        defaults = {
            "client_id": client,
            "claim_id": make.claim(db, client_id=client),
            "product_id": make.product(db),
            "qty": 1,
            "idempotency_key": "ask-1",
        }
        return db.execute(
            insert(EarlyReleaseRequest)
            .values(**defaults | values)
            .returning(EarlyReleaseRequest.id)
        ).scalar_one()

    def test_one_tap_makes_one_early_release_request(self, db: Connection) -> None:
        client = make.client(db)
        self.early_release_request(db, client_id=client)

        refused(
            db,
            lambda: self.early_release_request(db, client_id=client),
            "uq_early_release_requests_client_id_idempotency_key",
        )

    def test_a_need_has_one_open_early_release_request(self, db: Connection) -> None:
        claim = make.claim(db)
        self.early_release_request(db, claim_id=claim, idempotency_key="a")

        refused(
            db,
            lambda: self.early_release_request(db, claim_id=claim, idempotency_key="b"),
            "uq_early_release_requests_one_open_per_claim",
        )
        self.early_release_request(db, claim_id=claim, idempotency_key="c", state="UNFULFILLED")

    def test_an_ask_goes_to_a_pharmacy_once_and_an_acceptance_has_its_terms(
        self, db: Connection
    ) -> None:
        pharmacy = make.pharmacy(db)
        ask = {
            "er_request_id": self.early_release_request(db),
            "pharmacy_id": pharmacy,
            "inventory_item_id": make.item(db, pharmacy_id=pharmacy, days_left=200),
            "product_id": make.product(db),
            "respond_by": NOW + timedelta(hours=2),
        }
        other = ask | {"pharmacy_id": make.pharmacy(db)}

        refused(
            db,
            lambda: add(db, EarlyReleaseAsk, **other, state="ACCEPTED"),
            "ck_early_release_asks_accepted_has_its_terms",
        )
        refused(
            db,
            lambda: add(db, EarlyReleaseAsk, **other, accepted_qty=0),
            "ck_early_release_asks_accepted_qty_positive",
        )
        refused(
            db,
            lambda: add(db, EarlyReleaseAsk, **other, accepted_price_lbp=-1),
            "ck_early_release_asks_accepted_price_not_negative",
        )
        twice(
            db,
            lambda: add(db, EarlyReleaseAsk, **ask),
            "uq_early_release_asks_er_request_id_pharmacy_id",
        )


class TestConversationsAndOperations:
    def test_a_request_thread_points_at_its_request_and_only_one_does(self, db: Connection) -> None:
        client = make.client(db)
        request = make.request(db, client_id=client)

        refused(
            db,
            lambda: make.conversation(db, kind="request"),
            "ck_conversations_request_only_for_its_kind",
        )
        refused(
            db,
            lambda: make.conversation(db, request_id=request),
            "ck_conversations_request_only_for_its_kind",
        )
        twice(
            db,
            lambda: make.conversation(db, client_id=client, kind="request", request_id=request),
            "uq_conversations_request_id",
        )

    def test_turn_attempts_are_counted_from_zero(self, db: Connection) -> None:
        refused(
            db,
            lambda: make.conversation(db, turn_attempts=-1),
            "ck_conversations_turn_attempts_not_negative",
        )

    def test_messages_are_numbered_once_per_conversation(self, db: Connection) -> None:
        message = {
            "conversation_id": make.conversation(db),
            "seq": 1,
            "author": "client",
            "kind": "text",
        }

        twice(db, lambda: add(db, ChatMessage, **message), "uq_chat_messages_conversation_id_seq")

    def test_a_message_sent_twice_by_the_website_is_stored_once(self, db: Connection) -> None:
        """docs/06 §6.6: the same `client_message_id` can't be stored twice in a conversation."""
        conversation, sent = make.conversation(db), uuid.uuid4()
        numbers = iter(range(1, 9))

        def send() -> Any:
            return add(
                db,
                ChatMessage,
                conversation_id=conversation,
                seq=next(numbers),
                author="client",
                kind="text",
                client_message_id=sent,
            )

        twice(db, send, "uq_chat_messages_conversation_id_client_message_id")

    def test_free_text_from_people_has_a_length_limit(self, db: Connection) -> None:
        client = make.client(db)

        refused(
            db,
            lambda: add(
                db,
                AnswerReport,
                client_id=client,
                reason="wrong",
                comment="x" * 501,
                snapshot={},
            ),
            "ck_answer_reports_comment_length",
        )
        refused(
            db,
            lambda: add(db, Escalation, client_id=client, reason="complaint", summary="x" * 301),
            "ck_escalations_summary_length",
        )

    def test_the_same_event_is_notified_and_emailed_once(self, db: Connection) -> None:
        """R-NT: one per event per recipient."""
        user = make.user(db)
        email = {
            "user_id": user,
            "template": "CN-3",
            "dedupe_key": "order-1:CN-3",
            "next_attempt_at": NOW,
        }
        notification = {"user_id": user, "type": "CN-3", "dedupe_key": "order-1:CN-3"}

        twice(db, lambda: add(db, EmailOutbox, **email), "uq_email_outbox_dedupe_key")
        twice(db, lambda: add(db, Notification, **notification), "uq_notifications_dedupe_key")
        refused(
            db,
            lambda: add(db, EmailOutbox, **email | {"dedupe_key": "other", "attempts": -1}),
            "ck_email_outbox_attempts_not_negative",
        )

    def test_a_second_flag_for_the_same_thing_joins_the_open_one(self, db: Connection) -> None:
        flag = {
            "subject_type": "client",
            "subject_id": make.client(db),
            "rule": "no_show_pause",
            "severity": "low",
        }

        twice(db, lambda: add(db, AbuseFlag, **flag), "uq_abuse_flags_one_open")
        add(db, AbuseFlag, **flag | {"state": "DISMISSED"})
