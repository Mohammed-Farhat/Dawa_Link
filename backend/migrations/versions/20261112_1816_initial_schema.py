"""The first schema: 34 tables, their constraints and indexes, 5 functions and 3 triggers.

Built from docs/05_database.md. The table definitions were generated from the models in
dawalink/db/models; the extensions, functions and triggers below them are written by hand.

A migration is a frozen record: it imports nothing from the app, so later changes to the
rules can't silently change what this file created. Tests compare the literals in it
(zone bounds, state lists, the price formula) with the rules in dawalink/domain.

Revision ID: f508dadd13e7
Revises:
Create Date: 2026-11-12 18:16:22.854513
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f508dadd13e7"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The only two extensions: case-insensitive emails and fuzzy search (docs/05 §1).
EXTENSIONS = ("citext", "pg_trgm")

FUNCTIONS = (
    # The expiry zone for a number of days left (docs/04 SM-3, N-1, N-3). Never stored.
    """
    CREATE FUNCTION expiry_zone(days_left int, eligible boolean DEFAULT true)
    RETURNS text LANGUAGE sql IMMUTABLE AS $$
      SELECT CASE
        WHEN NOT eligible THEN 'NOT_ELIGIBLE'
        WHEN days_left < 0 THEN 'EXPIRED'
        WHEN days_left <= 180 THEN 'NEAR_EXPIRY'
        WHEN days_left <= 270 THEN 'EARLY_RELEASE'
        ELSE 'PRIVATE'
      END
    $$
    """,
    # What the client pays (docs/04 SM-3, R-PR, INV-5): the pharmacy's own price if it set
    # one, never above the public price; otherwise the system discount for the days left,
    # rounded down to 1,000 LBP. Whole-number maths only, exactly like domain/pricing.py.
    # NULL when no discount tier covers the days left (the box isn't in the published window).
    """
    CREATE FUNCTION effective_price_lbp(public_price bigint, override bigint, days_left int)
    RETURNS bigint LANGUAGE sql STABLE AS $$
      SELECT CASE
        WHEN override IS NOT NULL THEN LEAST(GREATEST(override, 0), public_price)
        ELSE (SELECT public_price * (100 - t.discount_pct) / 100 / 1000 * 1000
              FROM pricing_tiers t
              WHERE days_left BETWEEN t.min_days AND t.max_days)
      END
    $$
    """,
    # The expiry fit (docs/04 R-F1): the box is still valid on the last day of use.
    """
    CREATE FUNCTION fits(expiry date, pickup_day date, days_of_use int)
    RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
      SELECT expiry >= pickup_day + (days_of_use - 1)
    $$
    """,
    # The only definition of "visible to clients" (docs/04 INV-16). `p_today` always comes
    # from the app clock, never from the database's own date (docs/05 DB-D6).
    """
    CREATE FUNCTION visible_listings(p_today date)
    RETURNS TABLE (
      inventory_item_id uuid,
      pharmacy_id uuid,
      product_id uuid,
      expiry_date date,
      days_left int,
      qty_available int,
      price_lbp bigint
    ) LANGUAGE sql STABLE AS $$
      SELECT ii.id, ii.pharmacy_id, ii.product_id, ii.expiry_date,
             ii.expiry_date - p_today,
             ii.qty_on_hand - ii.qty_reserved,
             effective_price_lbp(
               p.public_price_lbp, ii.price_override_lbp, ii.expiry_date - p_today)
      FROM inventory_items ii
      JOIN products p ON p.id = ii.product_id
      JOIN pharmacies ph ON ph.id = ii.pharmacy_id
      WHERE ph.status = 'APPROVED'
        AND ii.listing_control = 'LIVE'
        AND NOT p.controlled
        AND ii.qty_on_hand - ii.qty_reserved >= 1
        AND ii.expiry_date BETWEEN p_today AND p_today + 180
    $$
    """,
    # A label for display only: 0 same district, 1 same governorate, 2 elsewhere.
    # Ranking uses travel time, computed in Python (docs/04 R-S3).
    """
    CREATE FUNCTION area_rank(client_district smallint, pharmacy_district smallint)
    RETURNS smallint LANGUAGE sql STABLE AS $$
      SELECT (CASE WHEN c.id = p.id THEN 0
                   WHEN c.governorate = p.governorate THEN 1
                   ELSE 2 END)::smallint
      FROM districts c, districts p
      WHERE c.id = client_district AND p.id = pharmacy_district
    $$
    """,
)

TRIGGERS = (
    # INV-4, INV-5, INV-15: a finished order never changes, and neither do an order's price
    # snapshot or a deadline that is already set. The one exception is a contested no-show
    # (docs/04 R-N3): `contested_at` may be set once and `counts_as_no_show` may be cleared.
    """
    CREATE FUNCTION orders_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.price_snapshot_lbp IS DISTINCT FROM OLD.price_snapshot_lbp THEN
        RAISE EXCEPTION 'orders: the price snapshot never changes (order %)', OLD.id
          USING ERRCODE = 'check_violation';
      END IF;
      IF OLD.deadline IS NOT NULL AND NEW.deadline IS DISTINCT FROM OLD.deadline THEN
        RAISE EXCEPTION 'orders: a deadline never changes once set (order %)', OLD.id
          USING ERRCODE = 'check_violation';
      END IF;
      IF OLD.state IN ('OFFERED', 'RESERVED') THEN
        RETURN NEW;
      END IF;
      IF OLD.state = 'EXPIRED_NO_SHOW'
         AND (to_jsonb(NEW) - 'contested_at' - 'counts_as_no_show' - 'updated_at')
           = (to_jsonb(OLD) - 'contested_at' - 'counts_as_no_show' - 'updated_at')
         AND (OLD.contested_at IS NULL OR NEW.contested_at IS NOT DISTINCT FROM OLD.contested_at)
         AND (NEW.counts_as_no_show = OLD.counts_as_no_show
              OR (OLD.counts_as_no_show AND NOT NEW.counts_as_no_show))
      THEN
        RETURN NEW;
      END IF;
      RAISE EXCEPTION 'orders: a finished order never changes (order %, state %)',
        OLD.id, OLD.state USING ERRCODE = 'check_violation';
    END
    $$
    """,
    """
    CREATE TRIGGER orders_guard BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION orders_guard()
    """,
    # INV-5: a pharmacy's own price is never above the product's public price.
    """
    CREATE FUNCTION inventory_items_price_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
      public_price bigint;
    BEGIN
      IF NEW.price_override_lbp IS NULL THEN
        RETURN NEW;
      END IF;
      SELECT p.public_price_lbp INTO public_price FROM products p WHERE p.id = NEW.product_id;
      IF NEW.price_override_lbp > public_price THEN
        RAISE EXCEPTION 'inventory_items: the price override % is above the public price %',
          NEW.price_override_lbp, public_price USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER inventory_items_price_guard
    BEFORE INSERT OR UPDATE OF price_override_lbp, product_id ON inventory_items
    FOR EACH ROW EXECUTE FUNCTION inventory_items_price_guard()
    """,
    # The audit log is append-only (docs/05 §3.8). Nobody updates a row. Only the retention
    # login deletes, and its task decides which rows are old enough from the app clock:
    # the database's own time is never used for a rule (docs/05 DB-D6).
    """
    CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND current_user = 'dawalink_retention' THEN
        RETURN OLD;
      END IF;
      RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = 'insufficient_privilege';
    END
    $$
    """,
    """
    CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
    """,
    """
    CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()
    """,
)

# Dropped in this order on the way down; the triggers go with their tables.
DROP_FUNCTIONS = (
    "audit_events_append_only()",
    "inventory_items_price_guard()",
    "orders_guard()",
    "area_rank(smallint, smallint)",
    "visible_listings(date)",
    "fits(date, date, int)",
    "effective_price_lbp(bigint, bigint, int)",
    "expiry_zone(int, boolean)",
)


def upgrade() -> None:
    for extension in EXTENSIONS:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")

    op.create_table(
        "app_state",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_state")),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "actor_type IN ('CLIENT', 'PHARMACY', 'ADMIN', 'AGENT', 'SYSTEM')",
            name=op.f("ck_audit_events_actor_type_values"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id", "occurred_at"],
        unique=False,
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"], unique=False)
    op.create_table(
        "catalog_imports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=False),
        sa.Column("lbp_per_usd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False),
        sa.Column("rows_imported", sa.Integer(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_imports")),
    )
    op.create_table(
        "districts",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("governorate", sa.Text(), nullable=False),
        sa.Column("ref_lat", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.Column("ref_lon", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_districts")),
        sa.UniqueConstraint("name", name=op.f("uq_districts_name")),
    )
    op.create_table(
        "pricing_tiers",
        sa.Column("min_days", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("max_days", sa.Integer(), nullable=False),
        sa.Column("discount_pct", sa.SmallInteger(), nullable=False),
        postgresql.ExcludeConstraint(
            (sa.text("int4range(min_days, max_days, '[]')"), "&&"),
            using="gist",
            name="ex_pricing_tiers_no_overlap",
        ),
        sa.CheckConstraint(
            "discount_pct BETWEEN 0 AND 100", name=op.f("ck_pricing_tiers_discount_is_a_percentage")
        ),
        sa.CheckConstraint(
            "min_days >= 0 AND min_days <= max_days", name=op.f("ck_pricing_tiers_days_in_order")
        ),
        sa.PrimaryKeyConstraint("min_days", name=op.f("pk_pricing_tiers")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_logins", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totp_secret", sa.LargeBinary(), nullable=True),
        sa.Column("totp_last_step", sa.BigInteger(), nullable=True),
        sa.Column("signup_ip_hash", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role <> 'admin' OR totp_secret IS NOT NULL", name=op.f("ck_users_admin_has_totp")
        ),
        sa.CheckConstraint(
            "role IN ('client', 'pharmacist', 'admin')", name=op.f("ck_users_role_values")
        ),
        sa.CheckConstraint(
            "char_length(full_name) BETWEEN 2 AND 80", name=op.f("ck_users_full_name_length")
        ),
        sa.CheckConstraint("failed_logins >= 0", name=op.f("ck_users_failed_logins_not_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "abuse_flags",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("state", sa.Text(), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "rule IN ('no_show_pause', 'guardrail_repeat')", name=op.f("ck_abuse_flags_rule_values")
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'high')", name=op.f("ck_abuse_flags_severity_values")
        ),
        sa.CheckConstraint(
            "state IN ('OPEN', 'DISMISSED', 'ACTIONED')", name=op.f("ck_abuse_flags_state_values")
        ),
        sa.CheckConstraint(
            "subject_type IN ('client', 'pharmacy')",
            name=op.f("ck_abuse_flags_subject_type_values"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["users.id"],
            name=op.f("fk_abuse_flags_resolved_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_abuse_flags")),
    )
    op.create_index(
        "uq_abuse_flags_one_open",
        "abuse_flags",
        ["subject_type", "subject_id", "rule"],
        unique=True,
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.create_table(
        "client_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'UNVERIFIED'"), nullable=False),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("district_id", sa.SmallInteger(), nullable=True),
        sa.Column(
            "alternatives_ok_default", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status <> 'PAUSED' OR paused_until IS NOT NULL",
            name=op.f("ck_client_profiles_paused_has_an_end"),
        ),
        sa.CheckConstraint(
            "status IN ('UNVERIFIED', 'ACTIVE', 'PAUSED', 'SUSPENDED')",
            name=op.f("ck_client_profiles_status_values"),
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name=op.f("fk_client_profiles_district_id_districts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_client_profiles_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_client_profiles")),
    )
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default=sa.text("'QUEUED'"), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('QUEUED', 'SENT', 'FAILED', 'DEAD')",
            name=op.f("ck_email_outbox_state_values"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_email_outbox_attempts_not_negative")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_email_outbox_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_outbox")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_email_outbox_dedupe_key")),
    )
    op.create_index(
        "ix_email_outbox_due",
        "email_outbox",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("state IN ('QUEUED', 'FAILED')"),
    )
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_email_verification_tokens_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_verification_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_verification_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_email_verification_tokens_user_id"),
        "email_verification_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_notifications_dedupe_key")),
    )
    op.create_index(
        "ix_notifications_user_created",
        "notifications",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "pharmacies",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("license_number", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("district_id", sa.SmallInteger(), nullable=False),
        sa.Column("lat", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.Column("lon", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.Column("location_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location_checked_by", sa.Uuid(), nullable=True),
        sa.Column("pickup_days", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("info_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'SUSPENDED')",
            name=op.f("ck_pharmacies_status_values"),
        ),
        sa.CheckConstraint(
            "lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180",
            name=op.f("ck_pharmacies_pin_in_range"),
        ),
        sa.CheckConstraint(
            "pickup_days BETWEEN 1 AND 3", name=op.f("ck_pharmacies_pickup_days_range")
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name=op.f("fk_pharmacies_district_id_districts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_checked_by"],
            ["users.id"],
            name=op.f("fk_pharmacies_location_checked_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_pharmacies_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pharmacies")),
        sa.UniqueConstraint("license_number", name=op.f("uq_pharmacies_license_number")),
        sa.UniqueConstraint("owner_user_id", name=op.f("uq_pharmacies_owner_user_id")),
        sa.UniqueConstraint("phone", name=op.f("uq_pharmacies_phone")),
    )
    op.create_index("ix_pharmacies_status", "pharmacies", ["status"], unique=False)
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("moph_code", sa.Integer(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("registration_number", sa.Text(), nullable=True),
        sa.Column("moph_name", sa.Text(), nullable=False),
        sa.Column("search_name", sa.Text(), nullable=False),
        sa.Column("brand_generic", sa.Text(), nullable=True),
        sa.Column("ingredients_raw", sa.Text(), nullable=True),
        sa.Column("dosage_text", sa.Text(), nullable=True),
        sa.Column("form_text", sa.Text(), nullable=True),
        sa.Column("presentation_text", sa.Text(), nullable=True),
        sa.Column("manufacturer", sa.Text(), nullable=True),
        sa.Column("form_group", sa.Text(), nullable=True),
        sa.Column("atc_code", sa.Text(), nullable=True),
        sa.Column("public_price_lbp", sa.BigInteger(), nullable=False),
        sa.Column("units_per_pack", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "prescription_required", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("controlled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("equivalence_key", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "brand_generic IN ('B', 'G', 'BioTech', 'BioHuman')",
            name=op.f("ck_products_brand_generic_values"),
        ),
        sa.CheckConstraint(
            "public_price_lbp >= 0", name=op.f("ck_products_public_price_not_negative")
        ),
        sa.CheckConstraint("units_per_pack >= 1", name=op.f("ck_products_units_per_pack_positive")),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["catalog_imports.id"],
            name=op.f("fk_products_import_id_catalog_imports"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("moph_code", name=op.f("uq_products_moph_code")),
    )
    op.create_index("ix_products_atc_code", "products", ["atc_code"], unique=False)
    op.create_index("ix_products_equivalence_key", "products", ["equivalence_key"], unique=False)
    op.create_index(op.f("ix_products_import_id"), "products", ["import_id"], unique=False)
    op.create_index(
        "ix_products_search_name_trgm",
        "products",
        ["search_name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"search_name": "gin_trgm_ops"},
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(
        "ix_sessions_user_live",
        "sessions",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "sourcing_requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.Text(), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("district_id", sa.SmallInteger(), nullable=True),
        sa.Column("loc_lat", sa.Numeric(precision=7, scale=3), nullable=True),
        sa.Column("loc_lon", sa.Numeric(precision=7, scale=3), nullable=True),
        sa.Column("loc_source", sa.Text(), nullable=True),
        sa.Column("alternatives_ok", sa.Boolean(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(state = 'CLOSED') = (outcome IS NOT NULL)",
            name=op.f("ck_sourcing_requests_closed_has_an_outcome"),
        ),
        sa.CheckConstraint(
            "loc_source IN ('shared', 'district')",
            name=op.f("ck_sourcing_requests_loc_source_values"),
        ),
        sa.CheckConstraint(
            "outcome IN ('FULFILLED', 'PARTIAL', 'UNFULFILLED', 'CANCELLED')",
            name=op.f("ck_sourcing_requests_outcome_values"),
        ),
        sa.CheckConstraint(
            "ref ~ '^Q-[2-9A-HJ-NP-Z]{6}$'", name=op.f("ck_sourcing_requests_ref_format")
        ),
        sa.CheckConstraint(
            "state IN ('OPEN', 'CLOSED')", name=op.f("ck_sourcing_requests_state_values")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["users.id"],
            name=op.f("fk_sourcing_requests_client_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name=op.f("fk_sourcing_requests_district_id_districts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sourcing_requests")),
        sa.UniqueConstraint(
            "client_id",
            "idempotency_key",
            name=op.f("uq_sourcing_requests_client_id_idempotency_key"),
        ),
        sa.UniqueConstraint("ref", name=op.f("uq_sourcing_requests_ref")),
    )
    op.create_index(
        "ix_sourcing_requests_client_open",
        "sourcing_requests",
        ["client_id"],
        unique=False,
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.create_index(
        "ix_sourcing_requests_ends_due",
        "sourcing_requests",
        ["ends_at"],
        unique=False,
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column(
            "case_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("loc_lat", sa.Numeric(precision=7, scale=3), nullable=True),
        sa.Column("loc_lon", sa.Numeric(precision=7, scale=3), nullable=True),
        sa.Column("loc_source", sa.Text(), nullable=True),
        sa.Column("loc_set_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("turn_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("turn_owner", sa.Text(), nullable=True),
        sa.Column("pending_turn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("turn_attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("followup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'request') = (request_id IS NOT NULL)",
            name=op.f("ck_conversations_request_only_for_its_kind"),
        ),
        sa.CheckConstraint(
            "kind IN ('chat', 'request')", name=op.f("ck_conversations_kind_values")
        ),
        sa.CheckConstraint(
            "loc_source IN ('shared', 'district')", name=op.f("ck_conversations_loc_source_values")
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')", name=op.f("ck_conversations_status_values")
        ),
        sa.CheckConstraint(
            "turn_attempts >= 0", name=op.f("ck_conversations_turn_attempts_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["users.id"],
            name=op.f("fk_conversations_client_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["sourcing_requests.id"],
            name=op.f("fk_conversations_request_id_sourcing_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("request_id", name=op.f("uq_conversations_request_id")),
    )
    op.create_index("ix_conversations_client_id", "conversations", ["client_id"], unique=False)
    op.create_index(
        "ix_conversations_followup",
        "conversations",
        ["followup_at"],
        unique=False,
        postgresql_where=sa.text("followup_at IS NOT NULL"),
    )
    op.create_index(
        "ix_conversations_last_activity", "conversations", ["last_activity_at"], unique=False
    )
    op.create_index(
        "ix_conversations_pending_turn",
        "conversations",
        ["pending_turn_at"],
        unique=False,
        postgresql_where=sa.text("pending_turn_at IS NOT NULL"),
    )
    op.create_index(
        "uq_conversations_one_active_chat",
        "conversations",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'chat' AND status = 'ACTIVE'"),
    )
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pharmacy_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch", sa.Text(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("qty_on_hand", sa.Integer(), nullable=False),
        sa.Column("qty_reserved", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("splittable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("listing_control", sa.Text(), server_default=sa.text("'LIVE'"), nullable=False),
        sa.Column("price_override_lbp", sa.BigInteger(), nullable=True),
        sa.Column("last_edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "listing_control IN ('LIVE', 'PAUSED')",
            name=op.f("ck_inventory_items_listing_control_values"),
        ),
        sa.CheckConstraint(
            "price_override_lbp IS NULL OR price_override_lbp >= 0",
            name=op.f("ck_inventory_items_price_override_not_negative"),
        ),
        sa.CheckConstraint(
            "qty_on_hand >= 0", name=op.f("ck_inventory_items_on_hand_not_negative")
        ),
        sa.CheckConstraint(
            "qty_reserved <= qty_on_hand", name=op.f("ck_inventory_items_reserved_within_on_hand")
        ),
        sa.CheckConstraint(
            "qty_reserved >= 0", name=op.f("ck_inventory_items_reserved_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["pharmacy_id"],
            ["pharmacies.id"],
            name=op.f("fk_inventory_items_pharmacy_id_pharmacies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_inventory_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_items")),
        sa.UniqueConstraint(
            "pharmacy_id",
            "product_id",
            "batch",
            "expiry_date",
            name=op.f("uq_inventory_items_pharmacy_id_product_id_batch_expiry_date"),
        ),
    )
    op.create_index(
        "ix_inventory_items_pharmacy_expiry",
        "inventory_items",
        ["pharmacy_id", "expiry_date"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_items_product_expiry",
        "inventory_items",
        ["product_id", "expiry_date"],
        unique=False,
    )
    op.create_table(
        "inventory_uploads",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pharmacy_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("rows_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rows_ok", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rows_error", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "errors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('VALIDATED', 'APPLIED', 'DISCARDED', 'FAILED')",
            name=op.f("ck_inventory_uploads_status_values"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_inventory_uploads_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pharmacy_id"],
            ["pharmacies.id"],
            name=op.f("fk_inventory_uploads_pharmacy_id_pharmacies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_uploads")),
    )
    op.create_index(
        op.f("ix_inventory_uploads_pharmacy_id"), "inventory_uploads", ["pharmacy_id"], unique=False
    )
    op.create_index(
        "uq_inventory_uploads_one_validated",
        "inventory_uploads",
        ["pharmacy_id"],
        unique=True,
        postgresql_where=sa.text("status = 'VALIDATED'"),
    )
    op.create_table(
        "pharmacy_hours",
        sa.Column("pharmacy_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.Column("open_minute", sa.SmallInteger(), nullable=False),
        sa.Column("close_minute", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "close_minute BETWEEN 1 AND 1440", name=op.f("ck_pharmacy_hours_close_minute_range")
        ),
        sa.CheckConstraint(
            "open_minute < close_minute", name=op.f("ck_pharmacy_hours_opens_before_it_closes")
        ),
        sa.CheckConstraint(
            "open_minute BETWEEN 0 AND 1439", name=op.f("ck_pharmacy_hours_open_minute_range")
        ),
        sa.CheckConstraint("seq BETWEEN 1 AND 2", name=op.f("ck_pharmacy_hours_seq_range")),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name=op.f("ck_pharmacy_hours_weekday_range")),
        sa.ForeignKeyConstraint(
            ["pharmacy_id"],
            ["pharmacies.id"],
            name=op.f("fk_pharmacy_hours_pharmacy_id_pharmacies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("pharmacy_id", "weekday", "seq", name=op.f("pk_pharmacy_hours")),
    )
    op.create_table(
        "product_ingredients",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_normalized", sa.Text(), nullable=False),
        sa.Column("strength_value", sa.Numeric(), nullable=True),
        sa.Column("strength_unit", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_ingredients_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("product_id", "position", name=op.f("pk_product_ingredients")),
    )
    op.create_index(
        "ix_product_ingredients_name_trgm",
        "product_ingredients",
        ["name_normalized"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name_normalized": "gin_trgm_ops"},
    )
    op.create_table(
        "request_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("qty_secured", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("days_of_use", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("max_price_lbp", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.Text(), server_default=sa.text("'SEARCHING'"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('SEARCHING', 'PROPOSED', 'WAITING', 'SECURED', 'UNAVAILABLE', 'CANCELLED')",
            name=op.f("ck_request_items_state_values"),
        ),
        sa.CheckConstraint("days_of_use >= 1", name=op.f("ck_request_items_days_of_use_positive")),
        sa.CheckConstraint(
            "max_price_lbp IS NULL OR max_price_lbp >= 0",
            name=op.f("ck_request_items_max_price_not_negative"),
        ),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 5", name=op.f("ck_request_items_position_range")
        ),
        sa.CheckConstraint("qty BETWEEN 1 AND 3", name=op.f("ck_request_items_qty_range")),
        sa.CheckConstraint(
            "qty_secured BETWEEN 0 AND qty", name=op.f("ck_request_items_qty_secured_range")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_request_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["sourcing_requests.id"],
            name=op.f("fk_request_items_request_id_sourcing_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_items")),
        sa.UniqueConstraint(
            "request_id", "position", name=op.f("uq_request_items_request_id_position")
        ),
    )
    op.create_table(
        "travel_time_cache",
        sa.Column("pharmacy_id", sa.Uuid(), nullable=False),
        sa.Column("origin_cell", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("km", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mode IN ('car', 'walk')", name=op.f("ck_travel_time_cache_mode_values")
        ),
        sa.CheckConstraint(
            "source IN ('road', 'straight')", name=op.f("ck_travel_time_cache_source_values")
        ),
        sa.CheckConstraint("minutes >= 0", name=op.f("ck_travel_time_cache_minutes_not_negative")),
        sa.ForeignKeyConstraint(
            ["pharmacy_id"],
            ["pharmacies.id"],
            name=op.f("fk_travel_time_cache_pharmacy_id_pharmacies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "pharmacy_id", "origin_cell", "mode", name=op.f("pk_travel_time_cache")
        ),
    )
    op.create_index(
        "ix_travel_time_cache_computed_at", "travel_time_cache", ["computed_at"], unique=False
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=10, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("tool_calls", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("tool_errors", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("retries", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("langfuse_trace_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "mode IN ('assistant', 'sourcing')", name=op.f("ck_agent_runs_mode_values")
        ),
        sa.CheckConstraint(
            "outcome IN ('ok', 'fallback', 'error', 'guardrail_blocked', 'budget_exceeded')",
            name=op.f("ck_agent_runs_outcome_values"),
        ),
        sa.CheckConstraint(
            "trigger IN ('client_message', 'request_submitted', 'decision_event', 'followup', 'window_check')",
            name=op.f("ck_agent_runs_trigger_values"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_agent_runs_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["sourcing_requests.id"],
            name=op.f("fk_agent_runs_request_id_sourcing_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index(
        "ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"], unique=False
    )
    op.create_index("ix_agent_runs_request_id", "agent_runs", ["request_id"], unique=False)
    op.create_index("ix_agent_runs_started_at", "agent_runs", ["started_at"], unique=False)
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("request_item_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column(
            "include_equivalents", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("equivalence_key", sa.Text(), nullable=True),
        sa.Column("district_id", sa.SmallInteger(), nullable=True),
        sa.Column("loc_lat", sa.Numeric(precision=7, scale=3), nullable=True),
        sa.Column("loc_lon", sa.Numeric(precision=7, scale=3), nullable=True),
        sa.Column("days_of_use", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("max_price_lbp", sa.BigInteger(), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("qty_missing", sa.Integer(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.Text(), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(kind = 'REQUEST_ITEM') = (request_item_id IS NOT NULL)",
            name=op.f("ck_claims_request_item_only_for_its_kind"),
        ),
        sa.CheckConstraint("kind IN ('WATCH', 'REQUEST_ITEM')", name=op.f("ck_claims_kind_values")),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'OFFER_PENDING', 'FULFILLED', 'EXPIRED', 'CANCELLED')",
            name=op.f("ck_claims_state_values"),
        ),
        sa.CheckConstraint("days_of_use >= 1", name=op.f("ck_claims_days_of_use_positive")),
        sa.CheckConstraint(
            "max_price_lbp IS NULL OR max_price_lbp >= 0",
            name=op.f("ck_claims_max_price_not_negative"),
        ),
        sa.CheckConstraint("qty BETWEEN 1 AND 3", name=op.f("ck_claims_qty_range")),
        sa.CheckConstraint(
            "qty_missing BETWEEN 0 AND qty", name=op.f("ck_claims_qty_missing_range")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["users.id"], name=op.f("fk_claims_client_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name=op.f("fk_claims_district_id_districts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_claims_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_item_id"],
            ["request_items.id"],
            name=op.f("fk_claims_request_item_id_request_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claims")),
        sa.UniqueConstraint("request_item_id", name=op.f("uq_claims_request_item_id")),
    )
    op.create_index(
        "ix_claims_client_live",
        "claims",
        ["client_id"],
        unique=False,
        postgresql_where=sa.text("state IN ('ACTIVE', 'OFFER_PENDING')"),
    )
    op.create_index(
        "ix_claims_ends_due",
        "claims",
        ["ends_at"],
        unique=False,
        postgresql_where=sa.text("state IN ('ACTIVE', 'OFFER_PENDING')"),
    )
    op.create_index(
        "ix_claims_matching",
        "claims",
        ["equivalence_key", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_index(
        "ix_claims_product_active",
        "claims",
        ["product_id"],
        unique=False,
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_index(
        "uq_claims_one_live_watch",
        "claims",
        ["client_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'WATCH' AND state IN ('ACTIVE', 'OFFER_PENDING')"),
    )
    op.create_table(
        "escalations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "notes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("state", sa.Text(), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('client_asked_human', 'emergency_claim', 'cannot_resolve', 'window_ending', 'suspicious', 'complaint')",
            name=op.f("ck_escalations_reason_values"),
        ),
        sa.CheckConstraint(
            "state IN ('OPEN', 'IN_PROGRESS', 'RESOLVED')", name=op.f("ck_escalations_state_values")
        ),
        sa.CheckConstraint(
            "char_length(summary) <= 300", name=op.f("ck_escalations_summary_length")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["users.id"],
            name=op.f("fk_escalations_client_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_escalations_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["sourcing_requests.id"],
            name=op.f("fk_escalations_request_id_sourcing_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["users.id"],
            name=op.f("fk_escalations_resolved_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escalations")),
    )
    op.create_index(
        "uq_escalations_one_open",
        "escalations",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("state <> 'RESOLVED'"),
    )
    op.create_table(
        "inventory_upload_rows",
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch", sa.Text(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "quantity >= 0", name=op.f("ck_inventory_upload_rows_quantity_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_inventory_upload_rows_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["inventory_uploads.id"],
            name=op.f("fk_inventory_upload_rows_upload_id_inventory_uploads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("upload_id", "row_no", name=op.f("pk_inventory_upload_rows")),
    )
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_tool_calls_agent_run_id_agent_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_tool_calls")),
    )
    op.create_index(
        "ix_agent_tool_calls_agent_run_id", "agent_tool_calls", ["agent_run_id"], unique=False
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text_redacted", sa.Text(), nullable=True),
        sa.Column("cards", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "author IN ('client', 'agent', 'system', 'admin')",
            name=op.f("ck_chat_messages_author_values"),
        ),
        sa.CheckConstraint(
            "kind IN ('text', 'card', 'timeline', 'event')",
            name=op.f("ck_chat_messages_kind_values"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_chat_messages_agent_run_id_agent_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_chat_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.UniqueConstraint(
            "conversation_id", "seq", name=op.f("uq_chat_messages_conversation_id_seq")
        ),
    )
    op.create_table(
        "claim_skips",
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("skip_until", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            name=op.f("fk_claim_skips_claim_id_claims"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_item_id"],
            ["inventory_items.id"],
            name=op.f("fk_claim_skips_inventory_item_id_inventory_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("claim_id", "inventory_item_id", name=op.f("pk_claim_skips")),
    )
    op.create_table(
        "early_release_requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column(
            "include_equivalents", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('OPEN', 'FULFILLED', 'UNFULFILLED', 'CANCELLED')",
            name=op.f("ck_early_release_requests_state_values"),
        ),
        sa.CheckConstraint("qty BETWEEN 1 AND 3", name=op.f("ck_early_release_requests_qty_range")),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            name=op.f("fk_early_release_requests_claim_id_claims"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["users.id"],
            name=op.f("fk_early_release_requests_client_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_early_release_requests_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_early_release_requests")),
        sa.UniqueConstraint(
            "client_id",
            "idempotency_key",
            name=op.f("uq_early_release_requests_client_id_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_early_release_requests_claim_id", "early_release_requests", ["claim_id"], unique=False
    )
    op.create_index(
        "ix_early_release_requests_client_open",
        "early_release_requests",
        ["client_id"],
        unique=False,
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.create_table(
        "proposals",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('reserve', 'reserve_group', 'accept_offer', 'cancel', 'request_summary', 'constraint_change', 'remove_item')",
            name=op.f("ck_proposals_kind_values"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_proposals_agent_run_id_agent_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["users.id"],
            name=op.f("fk_proposals_client_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_proposals_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposals")),
    )
    op.create_index("ix_proposals_client_id", "proposals", ["client_id"], unique=False)
    op.create_index("ix_proposals_conversation_id", "proposals", ["conversation_id"], unique=False)
    op.create_table(
        "answer_reports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.Text(), server_default=sa.text("'NEW'"), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('NEW', 'DISMISSED', 'CONFIRMED')",
            name=op.f("ck_answer_reports_state_values"),
        ),
        sa.CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 500",
            name=op.f("ck_answer_reports_comment_length"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["users.id"],
            name=op.f("fk_answer_reports_client_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            name=op.f("fk_answer_reports_message_id_chat_messages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name=op.f("fk_answer_reports_reviewed_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_answer_reports")),
    )
    op.create_index("ix_answer_reports_state", "answer_reports", ["state"], unique=False)
    op.create_table(
        "early_release_asks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("er_request_id", sa.Uuid(), nullable=False),
        sa.Column("pharmacy_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.Text(), server_default=sa.text("'ASKED'"), nullable=False),
        sa.Column("respond_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_qty", sa.Integer(), nullable=True),
        sa.Column("accepted_price_lbp", sa.BigInteger(), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state <> 'ACCEPTED' OR (accepted_qty IS NOT NULL AND accepted_price_lbp IS NOT NULL)",
            name=op.f("ck_early_release_asks_accepted_has_its_terms"),
        ),
        sa.CheckConstraint(
            "state IN ('ASKED', 'ACCEPTED', 'DECLINED', 'EXPIRED', 'WITHDRAWN')",
            name=op.f("ck_early_release_asks_state_values"),
        ),
        sa.CheckConstraint(
            "accepted_price_lbp IS NULL OR accepted_price_lbp >= 0",
            name=op.f("ck_early_release_asks_accepted_price_not_negative"),
        ),
        sa.CheckConstraint(
            "accepted_qty IS NULL OR accepted_qty >= 1",
            name=op.f("ck_early_release_asks_accepted_qty_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["er_request_id"],
            ["early_release_requests.id"],
            name=op.f("fk_early_release_asks_er_request_id_early_release_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_item_id"],
            ["inventory_items.id"],
            name=op.f("fk_early_release_asks_inventory_item_id_inventory_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pharmacy_id"],
            ["pharmacies.id"],
            name=op.f("fk_early_release_asks_pharmacy_id_pharmacies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_early_release_asks_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_early_release_asks")),
        sa.UniqueConstraint(
            "er_request_id",
            "pharmacy_id",
            name=op.f("uq_early_release_asks_er_request_id_pharmacy_id"),
        ),
    )
    op.create_index(
        "ix_early_release_asks_declined",
        "early_release_asks",
        ["pharmacy_id", "product_id", "answered_at"],
        unique=False,
        postgresql_where=sa.text("state = 'DECLINED'"),
    )
    op.create_index(
        "ix_early_release_asks_pharmacy_created",
        "early_release_asks",
        ["pharmacy_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_early_release_asks_respond_due",
        "early_release_asks",
        ["respond_by"],
        unique=False,
        postgresql_where=sa.text("state = 'ASKED'"),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("pharmacy_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("equivalence_key", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=True),
        sa.Column("request_item_id", sa.Uuid(), nullable=True),
        sa.Column("early_release_ask_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("qty_requested", sa.Integer(), nullable=False),
        sa.Column("qty_locked", sa.Integer(), nullable=False),
        sa.Column("qty_picked_up", sa.Integer(), nullable=True),
        sa.Column("pickup_day", sa.Date(), nullable=True),
        sa.Column("days_of_use", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("price_snapshot_lbp", sa.BigInteger(), nullable=False),
        sa.Column("offer_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "counts_as_no_show", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("contested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "close_reason IN ('not_available', 'client_cancel', 'declined', 'expired', 'withdrawn', 'system')",
            name=op.f("ck_orders_close_reason_values"),
        ),
        sa.CheckConstraint("ref ~ '^R-[2-9A-HJ-NP-Z]{6}$'", name=op.f("ck_orders_ref_format")),
        sa.CheckConstraint(
            "source IN ('search', 'assistant', 'request', 'watch', 'early_release')",
            name=op.f("ck_orders_source_values"),
        ),
        sa.CheckConstraint(
            "state <> 'OFFERED' OR offer_expires_at IS NOT NULL",
            name=op.f("ck_orders_offer_has_an_end"),
        ),
        sa.CheckConstraint(
            "state <> 'PICKED_UP' OR qty_picked_up IS NOT NULL",
            name=op.f("ck_orders_picked_up_has_a_quantity"),
        ),
        sa.CheckConstraint(
            "state <> 'RESERVED' OR deadline IS NOT NULL",
            name=op.f("ck_orders_reservation_has_a_deadline"),
        ),
        sa.CheckConstraint(
            "state <> 'RESERVED' OR pickup_day IS NOT NULL",
            name=op.f("ck_orders_reservation_has_a_pickup_day"),
        ),
        sa.CheckConstraint(
            "state IN ('OFFERED', 'RESERVED') OR qty_locked = 0",
            name=op.f("ck_orders_only_open_orders_hold_stock"),
        ),
        sa.CheckConstraint(
            "state IN ('OFFERED', 'RESERVED', 'PICKED_UP', 'NOT_AVAILABLE', 'EXPIRED_NO_SHOW', 'CANCELLED_BY_CLIENT', 'CANCELLED_BY_SYSTEM', 'OFFER_DECLINED', 'OFFER_EXPIRED', 'OFFER_WITHDRAWN')",
            name=op.f("ck_orders_state_values"),
        ),
        sa.CheckConstraint("days_of_use >= 1", name=op.f("ck_orders_days_of_use_positive")),
        sa.CheckConstraint(
            "price_snapshot_lbp >= 0", name=op.f("ck_orders_price_snapshot_not_negative")
        ),
        sa.CheckConstraint(
            "qty_locked BETWEEN 0 AND qty_requested", name=op.f("ck_orders_qty_locked_range")
        ),
        sa.CheckConstraint(
            "qty_picked_up IS NULL OR qty_picked_up BETWEEN 0 AND qty_requested",
            name=op.f("ck_orders_qty_picked_up_range"),
        ),
        sa.CheckConstraint("qty_requested > 0", name=op.f("ck_orders_qty_requested_positive")),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["claims.id"], name=op.f("fk_orders_claim_id_claims"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["users.id"], name=op.f("fk_orders_client_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["early_release_ask_id"],
            ["early_release_asks.id"],
            name=op.f("fk_orders_early_release_ask_id_early_release_asks"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_item_id"],
            ["inventory_items.id"],
            name=op.f("fk_orders_inventory_item_id_inventory_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pharmacy_id"],
            ["pharmacies.id"],
            name=op.f("fk_orders_pharmacy_id_pharmacies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_orders_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_item_id"],
            ["request_items.id"],
            name=op.f("fk_orders_request_item_id_request_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint(
            "client_id", "idempotency_key", name=op.f("uq_orders_client_id_idempotency_key")
        ),
        sa.UniqueConstraint("ref", name=op.f("uq_orders_ref")),
    )
    op.create_index("ix_orders_claim_id", "orders", ["claim_id"], unique=False)
    op.create_index(
        "ix_orders_client_open",
        "orders",
        ["client_id"],
        unique=False,
        postgresql_where=sa.text("state IN ('OFFERED', 'RESERVED')"),
    )
    op.create_index(
        "ix_orders_deadline_due",
        "orders",
        ["deadline"],
        unique=False,
        postgresql_where=sa.text("state = 'RESERVED'"),
    )
    op.create_index("ix_orders_group_id", "orders", ["group_id"], unique=False)
    op.create_index(
        "ix_orders_item_open",
        "orders",
        ["inventory_item_id"],
        unique=False,
        postgresql_where=sa.text("state IN ('OFFERED', 'RESERVED')"),
    )
    op.create_index(
        "ix_orders_offer_due",
        "orders",
        ["offer_expires_at"],
        unique=False,
        postgresql_where=sa.text("state = 'OFFERED'"),
    )
    op.create_index("ix_orders_pharmacy_state", "orders", ["pharmacy_id", "state"], unique=False)
    op.create_index("ix_orders_request_item_id", "orders", ["request_item_id"], unique=False)
    op.create_index(
        "uq_orders_one_offer_per_path",
        "orders",
        ["claim_id", "source"],
        unique=True,
        postgresql_where=sa.text("state = 'OFFERED'"),
    )

    for statement in (*FUNCTIONS, *TRIGGERS):
        op.execute(statement)


def downgrade() -> None:
    op.drop_index(
        "uq_orders_one_offer_per_path",
        table_name="orders",
        postgresql_where=sa.text("state = 'OFFERED'"),
    )
    op.drop_index("ix_orders_request_item_id", table_name="orders")
    op.drop_index("ix_orders_pharmacy_state", table_name="orders")
    op.drop_index(
        "ix_orders_offer_due", table_name="orders", postgresql_where=sa.text("state = 'OFFERED'")
    )
    op.drop_index(
        "ix_orders_item_open",
        table_name="orders",
        postgresql_where=sa.text("state IN ('OFFERED', 'RESERVED')"),
    )
    op.drop_index("ix_orders_group_id", table_name="orders")
    op.drop_index(
        "ix_orders_deadline_due",
        table_name="orders",
        postgresql_where=sa.text("state = 'RESERVED'"),
    )
    op.drop_index(
        "ix_orders_client_open",
        table_name="orders",
        postgresql_where=sa.text("state IN ('OFFERED', 'RESERVED')"),
    )
    op.drop_index("ix_orders_claim_id", table_name="orders")
    op.drop_table("orders")
    op.drop_index(
        "ix_early_release_asks_respond_due",
        table_name="early_release_asks",
        postgresql_where=sa.text("state = 'ASKED'"),
    )
    op.drop_index("ix_early_release_asks_pharmacy_created", table_name="early_release_asks")
    op.drop_index(
        "ix_early_release_asks_declined",
        table_name="early_release_asks",
        postgresql_where=sa.text("state = 'DECLINED'"),
    )
    op.drop_table("early_release_asks")
    op.drop_index("ix_answer_reports_state", table_name="answer_reports")
    op.drop_table("answer_reports")
    op.drop_index("ix_proposals_conversation_id", table_name="proposals")
    op.drop_index("ix_proposals_client_id", table_name="proposals")
    op.drop_table("proposals")
    op.drop_index(
        "ix_early_release_requests_client_open",
        table_name="early_release_requests",
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.drop_index("ix_early_release_requests_claim_id", table_name="early_release_requests")
    op.drop_table("early_release_requests")
    op.drop_table("claim_skips")
    op.drop_table("chat_messages")
    op.drop_index("ix_agent_tool_calls_agent_run_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_table("inventory_upload_rows")
    op.drop_index(
        "uq_escalations_one_open",
        table_name="escalations",
        postgresql_where=sa.text("state <> 'RESOLVED'"),
    )
    op.drop_table("escalations")
    op.drop_index(
        "uq_claims_one_live_watch",
        table_name="claims",
        postgresql_where=sa.text("kind = 'WATCH' AND state IN ('ACTIVE', 'OFFER_PENDING')"),
    )
    op.drop_index(
        "ix_claims_product_active",
        table_name="claims",
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.drop_index(
        "ix_claims_matching", table_name="claims", postgresql_where=sa.text("state = 'ACTIVE'")
    )
    op.drop_index(
        "ix_claims_ends_due",
        table_name="claims",
        postgresql_where=sa.text("state IN ('ACTIVE', 'OFFER_PENDING')"),
    )
    op.drop_index(
        "ix_claims_client_live",
        table_name="claims",
        postgresql_where=sa.text("state IN ('ACTIVE', 'OFFER_PENDING')"),
    )
    op.drop_table("claims")
    op.drop_index("ix_agent_runs_started_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_request_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_travel_time_cache_computed_at", table_name="travel_time_cache")
    op.drop_table("travel_time_cache")
    op.drop_table("request_items")
    op.drop_index(
        "ix_product_ingredients_name_trgm",
        table_name="product_ingredients",
        postgresql_using="gin",
        postgresql_ops={"name_normalized": "gin_trgm_ops"},
    )
    op.drop_table("product_ingredients")
    op.drop_table("pharmacy_hours")
    op.drop_index(
        "uq_inventory_uploads_one_validated",
        table_name="inventory_uploads",
        postgresql_where=sa.text("status = 'VALIDATED'"),
    )
    op.drop_index(op.f("ix_inventory_uploads_pharmacy_id"), table_name="inventory_uploads")
    op.drop_table("inventory_uploads")
    op.drop_index("ix_inventory_items_product_expiry", table_name="inventory_items")
    op.drop_index("ix_inventory_items_pharmacy_expiry", table_name="inventory_items")
    op.drop_table("inventory_items")
    op.drop_index(
        "uq_conversations_one_active_chat",
        table_name="conversations",
        postgresql_where=sa.text("kind = 'chat' AND status = 'ACTIVE'"),
    )
    op.drop_index(
        "ix_conversations_pending_turn",
        table_name="conversations",
        postgresql_where=sa.text("pending_turn_at IS NOT NULL"),
    )
    op.drop_index("ix_conversations_last_activity", table_name="conversations")
    op.drop_index(
        "ix_conversations_followup",
        table_name="conversations",
        postgresql_where=sa.text("followup_at IS NOT NULL"),
    )
    op.drop_index("ix_conversations_client_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(
        "ix_sourcing_requests_ends_due",
        table_name="sourcing_requests",
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.drop_index(
        "ix_sourcing_requests_client_open",
        table_name="sourcing_requests",
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.drop_table("sourcing_requests")
    op.drop_index(
        "ix_sessions_user_live",
        table_name="sessions",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_table("sessions")
    op.drop_index(
        "ix_products_search_name_trgm",
        table_name="products",
        postgresql_using="gin",
        postgresql_ops={"search_name": "gin_trgm_ops"},
    )
    op.drop_index(op.f("ix_products_import_id"), table_name="products")
    op.drop_index("ix_products_equivalence_key", table_name="products")
    op.drop_index("ix_products_atc_code", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_pharmacies_status", table_name="pharmacies")
    op.drop_table("pharmacies")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(
        op.f("ix_email_verification_tokens_user_id"), table_name="email_verification_tokens"
    )
    op.drop_table("email_verification_tokens")
    op.drop_index(
        "ix_email_outbox_due",
        table_name="email_outbox",
        postgresql_where=sa.text("state IN ('QUEUED', 'FAILED')"),
    )
    op.drop_table("email_outbox")
    op.drop_table("client_profiles")
    op.drop_index(
        "uq_abuse_flags_one_open",
        table_name="abuse_flags",
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.drop_table("abuse_flags")
    op.drop_table("users")
    op.drop_table("pricing_tiers")
    op.drop_table("districts")
    op.drop_table("catalog_imports")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("app_state")

    for function in DROP_FUNCTIONS:
        op.execute(f"DROP FUNCTION {function}")
    # The extensions stay: they belong to the database, not to this schema.
