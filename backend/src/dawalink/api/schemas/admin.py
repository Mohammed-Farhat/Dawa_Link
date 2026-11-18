"""What the admin's console is sent and answers with (docs/06 §6.10; docs/03 §3).

Nothing here carries a client's name, email or phone: an admin reads those through one
audited endpoint only (A-D3). A pharmacy's details are a business's, and are shown.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from dawalink.api.schemas.accounts import OpeningRange, PinIn
from dawalink.api.schemas.common import DistrictId, In, Out, Pin

PharmacyStatusName = Literal["PENDING", "APPROVED", "REJECTED", "SUSPENDED"]
EscalationStateName = Literal["OPEN", "IN_PROGRESS", "RESOLVED"]
EscalationReasonName = Literal[
    "client_asked_human",
    "emergency_claim",
    "cannot_resolve",
    "window_ending",
    "suspicious",
    "complaint",
]
ReportStateName = Literal["NEW", "DISMISSED", "CONFIRMED"]
ReportReasonName = Literal["wrong_medicine", "wrong_information", "not_helpful", "unsafe", "other"]
ReportCategoryName = Literal["understanding", "decision", "safety", "language", "other"]


class AdminOverview(Out):
    """What needs an admin's attention (AS-2)."""

    pharmacies_waiting: int
    # Approved pharmacies that moved their address or pin, and no admin has looked since.
    pins_to_check: int
    escalations_open: int
    emergency_claims: int
    reports_new: int
    flags_open: int
    flags_high: int
    # No-shows a client contests: each waits for an admin's look (R-N3).
    contests_waiting: int
    # The demo clock's screen exists only in demo mode (R-DEMO).
    demo_mode: bool


# --- Pharmacies (AS-3, AS-4) ----------------------------------------------------------------


class AdminPharmacyRow(Out):
    id: uuid.UUID
    name: str
    status: PharmacyStatusName
    info_requested: bool
    pin_to_check: bool
    district: str
    license_number: str
    created_at: datetime
    approved_at: datetime | None


class AdminPharmacies(Out):
    items: list[AdminPharmacyRow]
    next_cursor: str | None


class OtherPharmacy(Out):
    id: uuid.UUID
    name: str
    status: PharmacyStatusName


class AdminPharmacy(Out):
    """One pharmacy as the admin checks it: what it typed, its pin, and what the checks
    found."""

    id: uuid.UUID
    name: str
    status: PharmacyStatusName
    status_reason: str | None
    info_requested: bool
    # The login's email: a business contact.
    email: str
    phone: str
    license_number: str
    address: str
    district: str
    district_id: int
    location: Pin
    # An admin has looked at the pin on the map (at approval, or by moving it).
    pin_checked: bool
    pickup_days: int
    hours: list[OpeningRange]
    # Sent back with [Approve]: the approval is of the details shown here.
    version: str
    # Other pharmacies registered at the same address.
    same_address: list[OtherPharmacy]
    # When the pharmacy last changed its own phone number, if it did.
    phone_changed_at: datetime | None
    # When it last changed its own address or pin, and whether the pin waits for a look.
    moved_at: datetime | None
    pin_to_check: bool
    created_at: datetime
    approved_at: datetime | None
    # AS-4: boxes clients can see now, the last change to its stock, and its reservations
    # of the last 30 days that ended at the counter, by how they ended.
    live_listings: int
    last_inventory_update: datetime | None
    handed_over_30d: int
    not_available_30d: int


class Approve(In):
    version: str = Field(min_length=1, max_length=64)


class WithReason(In):
    """An admin's action and why. An empty reason is `REASON_REQUIRED`."""

    reason: str = Field(default="", max_length=300)


class AdminPharmacyEdit(In):
    """An admin corrects a pharmacy's details (SM-1). Only what is sent changes."""

    reason: str = Field(default="", max_length=300)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    license_number: str | None = Field(default=None, min_length=1, max_length=40)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    address: str | None = Field(default=None, min_length=1, max_length=300)
    district_id: DistrictId | None = None
    location: PinIn | None = None


# --- Escalations (AS-6) -----------------------------------------------------------------------


class EscalationNote(Out):
    """A later escalation of the same client, added to the open one (SM-9)."""

    reason: str
    summary: str
    at: datetime | None


class EscalationRow(Out):
    id: uuid.UUID
    # An ID, never a name: it opens the client's page (status, counts, contests).
    client_id: uuid.UUID
    reason: EscalationReasonName
    state: EscalationStateName
    # Written by the agent, with no personal details.
    summary: str
    request_ref: str | None
    notes: list[EscalationNote]
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


class Escalations(Out):
    items: list[EscalationRow]
    next_cursor: str | None


class ThreadMessage(Out):
    """One message of the conversation, as it is stored: without personal details."""

    seq: int
    author: Literal["client", "agent", "system", "admin"]
    text: str | None
    # What the cards under it were ("reserve", "plan", "status"), never their content.
    cards: list[str]
    created_at: datetime


class EscalationDetail(Out):
    escalation: EscalationRow
    thread: list[ThreadMessage]
    # The agent runs behind the thread's replies, newest first: what to look up in the
    # tracing tool.
    trace_ids: list[str]


class TeamReply(In):
    text: str = Field(min_length=1, max_length=500)


class Resolve(In):
    note: str = Field(default="", max_length=500)


# --- Reported answers (CS-9, AS-8) ------------------------------------------------------------


class ReportAnswer(In):
    """The client's thumbs-down on a reply."""

    reason: ReportReasonName
    comment: str | None = Field(default=None, max_length=500)


class AnswerReported(Out):
    id: uuid.UUID


class ReportedCard(Out):
    origin: str
    type: str
    title: str
    recommended: bool


class ReportedLine(Out):
    seq: int
    author: str
    text: str | None
    cards: list[ReportedCard]
    quick_replies: list[str]


class ReportedRun(Out):
    """The agent turn that wrote the reply."""

    id: str
    mode: str | None
    trigger: str | None
    model: str | None
    prompt_version: str | None
    outcome: str | None
    guardrails: list[str]
    trace_id: str | None


class AnswerReportRow(Out):
    id: uuid.UUID
    state: ReportStateName
    reason: str
    comment: str | None
    category: str | None
    in_regression: bool
    # The start of the reported reply.
    reply: str
    created_at: datetime


class AnswerReports(Out):
    items: list[AnswerReportRow]
    next_cursor: str | None


class AnswerReportDetail(Out):
    report: AnswerReportRow
    conversation_kind: str
    reply: ReportedLine
    context: list[ReportedLine]
    run: ReportedRun | None


class ConfirmReport(In):
    category: ReportCategoryName
    add_to_regression: bool = False


class RegressionCases(Out):
    """Confirmed reports added to the regression set, as the team copies them into the
    repo (docs/08 §5)."""

    cases: list[dict[str, Any]]


# --- The audit log (AS-11) --------------------------------------------------------------------


class AuditRow(Out):
    id: int
    occurred_at: datetime
    actor_type: str
    actor_id: uuid.UUID | None
    entity_type: str
    entity_id: uuid.UUID | None
    action: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None


class AuditPage(Out):
    items: list[AuditRow]
    next_cursor: str | None


# --- Clients (AS-5) ---------------------------------------------------------------------------

ClientStatusName = Literal["UNVERIFIED", "ACTIVE", "PAUSED", "SUSPENDED"]


class AdminClientRow(Out):
    """A client as an admin sees one: a status and counts, no name and no contact."""

    id: uuid.UUID
    status: ClientStatusName
    paused_until: datetime | None
    district: str | None
    open_orders: int
    no_shows: int
    open_requests: int
    contested: int


class AdminClients(Out):
    items: list[AdminClientRow]
    next_cursor: str | None


class ContestedReservation(Out):
    """An expired reservation the client says they picked up (R-N3)."""

    id: uuid.UUID
    ref: str
    product: str
    pharmacy: str
    expired_at: datetime | None
    contested_at: datetime


class AdminClient(Out):
    client: AdminClientRow
    contested: list[ContestedReservation]


class ClientContact(Out):
    """Read through one audited endpoint only (A-D3)."""

    full_name: str
    email: str
    phone: str | None


# --- Abuse flags (AS-7) -----------------------------------------------------------------------


class AbuseFlagRow(Out):
    id: uuid.UUID
    subject_type: Literal["client", "pharmacy"]
    subject_id: uuid.UUID
    rule: str
    severity: Literal["low", "high"]
    # Counts and IDs only.
    evidence: dict[str, Any]
    state: Literal["OPEN", "DISMISSED", "ACTIONED"]
    action: str | None
    created_at: datetime


class AbuseFlags(Out):
    items: list[AbuseFlagRow]
    next_cursor: str | None


class FlagAction(In):
    action: Literal["warn", "suspend"]
    reason: str = Field(default="", max_length=300)


# --- The catalog (AS-9) -----------------------------------------------------------------------


class CatalogProduct(Out):
    id: uuid.UUID
    code: int
    name: str
    strength: str | None
    form: str | None
    pack: str | None
    manufacturer: str | None
    public_price_lbp: int
    prescription_required: bool
    # Never shown to a client or a pharmacy (R-C6).
    controlled: bool
    # How many products are "the same medicine" as this one, itself included; 0 when it
    # has no key.
    same_medicine: int


class CatalogProducts(Out):
    items: list[CatalogProduct]
    next_cursor: str | None


class CatalogImportRow(Out):
    id: uuid.UUID
    file_name: str
    source_date: date
    lbp_per_usd: float
    rows_total: int
    rows_imported: int
    imported_at: datetime


class CatalogImports(Out):
    items: list[CatalogImportRow]


# --- Health (AS-2, AS-10) ---------------------------------------------------------------------


class AdminHealth(Out):
    """The agent's and the system's numbers over the last `days` days, and the alerts
    that fire right now (R-AL)."""

    days: int
    agent: dict[str, Any]
    requests: dict[str, Any]
    marketplace: dict[str, Any]
    system: dict[str, Any]
    alerts: list[str]
