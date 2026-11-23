"""What the admin's console is sent and answers with (docs/06 §6.10; docs/03 §3).

Nothing here carries a client's name, email or phone: an admin reads those through one
audited endpoint only (A-D3). A pharmacy's details are a business's, and are shown.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from dawalink.api.schemas.accounts import OpeningRange, PinIn
from dawalink.api.schemas.common import CountedPage, DistrictId, In, Out, Pin
from dawalink.domain.audit_actions import AuditAction

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


class AdminPharmacies(CountedPage):
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
    # An ID, never a name: it opens the client's page.
    client_id: uuid.UUID
    reason: EscalationReasonName
    state: EscalationStateName
    # Written by the agent, or by code for a contested no-show: no personal details.
    summary: str
    request_ref: str | None
    notes: list[EscalationNote]
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None
    # Every reason of the case, the first one first, each once: "Missed pickup
    # contested", "Asked for a person"…
    reasons: list[EscalationReasonName]
    # The newest ask: what the list shows, and when it came (the app's clock).
    last_summary: str
    last_asked_at: datetime
    # The team's last reply, on the app's clock. None before any (or for a reply sent
    # before replies were remembered).
    last_replied_at: datetime | None
    # The client asked again after the team's last reply: "New ask since your reply".
    new_ask_since_reply: bool
    # The client wrote in a chat the team replied in, after the team's last reply there:
    # when the newest such message was stored. Such a case is listed first.
    client_wrote_at: datetime | None
    # While the client's chat is with the team: when the assistant answers again by
    # itself if nobody closes the case (N-55). None when no chat is with the team.
    hold_ends_at: datetime | None


class Escalations(CountedPage):
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
    # The first message of another chat of the case (a later ask, or a reply that went
    # to the chat the client had then): the page marks where it starts.
    starts_another_chat: bool


class ContestedReservation(Out):
    """An expired reservation the client says they picked up (R-N3)."""

    id: uuid.UUID
    ref: str
    product: str
    pharmacy: str
    expired_at: datetime | None
    contested_at: datetime
    # False once an admin cleared it: it no longer counts as a missed pickup, and has
    # nothing left to clear (R-N3).
    counts_as_no_show: bool


class EscalationDetail(Out):
    escalation: EscalationRow
    # Empty when there is no chat to show: the case came from a button, not from a
    # chat, or the chat was deleted after its 30 days.
    thread: list[ThreadMessage]
    # What this case's contested missed pickup is about: the reservation the client
    # pressed [I picked it up] on, with the other boxes of its trip, cleared or not.
    # Empty on a case of another kind. A complaint made before cases remembered their
    # reservation shows the contested reservations its summary names.
    contested: list[ContestedReservation]


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
    # The reported reply, whole, and the client's message it answered: enough to judge
    # it from the list. Both without personal details, like every stored message.
    reply: str
    asked: str | None
    created_at: datetime


class AnswerReports(CountedPage):
    items: list[AnswerReportRow]
    next_cursor: str | None


class AnswerReportDetail(Out):
    report: AnswerReportRow
    conversation_kind: str
    reply: ReportedLine
    context: list[ReportedLine]
    run: ReportedRun | None


class ConfirmReport(In):
    """[Real problem]. The console sends nothing with it: a confirmed report is a
    regression case, filed under "other" unless a category is given."""

    category: ReportCategoryName = "other"
    add_to_regression: bool = True


class RegressionCases(Out):
    """Confirmed reports added to the regression set, as the team copies them into the
    repo (docs/08 §5)."""

    cases: list[dict[str, Any]]


# --- The audit log (AS-11) --------------------------------------------------------------------


# The families of the "Kind" filter (`domain/audit_actions.py`, `KINDS`).
AuditKindName = Literal[
    "pharmacies",
    "stock",
    "reservations",
    "clients",
    "requests",
    "escalations",
    "reports",
    "flags",
    "accounts",
    "clock",
]


class AuditWho(Out):
    """Who did it. An admin by their name and a pharmacy by its approved name; **a client
    by an ID only, never a name** (BLD-D45); the assistant and the system by what they are."""

    kind: Literal["admin", "pharmacy", "client", "agent", "system"]
    name: str | None
    # The pharmacy's or the client's ID, for the link to their page.
    id: uuid.UUID | None


class AuditSubject(Out):
    """The page of the console the event is about. None when there is none: a
    registration whose email was never confirmed, a row deleted since, an admin's login."""

    kind: Literal["pharmacy", "client", "escalation", "reports", "clock"]
    id: uuid.UUID | None


class AuditRow(Out):
    """One event of the log, as an admin reads it. **The values of the fields that
    changed are never here** (only their names): they stay in the table."""

    id: int
    occurred_at: datetime
    actor_type: str
    actor_id: uuid.UUID | None
    entity_type: str
    entity_id: uuid.UUID | None
    # The stored code, as it is: an event written before its sentence existed still shows.
    action: str
    # The same code when the console has a sentence for it (every code the backend
    # writes has one: a test says so), else None.
    known_action: AuditAction | None
    who: AuditWho
    subject: AuditSubject | None
    # The names of the fields that changed ("phone", "hours"), never their values.
    changed: list[str]
    # A move between two of the app's own states ("PENDING" to "APPROVED"); a request's
    # close gives how it ended. Never a text a person typed.
    state_from: str | None
    state_to: str | None
    # How many things the action ended or touched ("offers_cancelled": 3).
    counts: dict[str, int]
    # A code the app chose from a list of its own: an escalation's or a report's reason,
    # whether a wait is a watch or a request's medicine.
    code: str | None
    # The admin's reason (or the code's, for an automatic change).
    reason: str | None


class AuditPage(CountedPage):
    items: list[AuditRow]
    next_cursor: str | None


# --- Clients (AS-5) ---------------------------------------------------------------------------

# DELETED: the client deleted their account (R-AU10). Their page shows its ID, this
# status and their past reservations; nothing else is kept.
ClientStatusName = Literal["UNVERIFIED", "ACTIVE", "PAUSED", "SUSPENDED", "DELETED"]


class AdminClientRow(Out):
    """A client as an admin sees one: a status and counts, no name and no contact."""

    id: uuid.UUID
    status: ClientStatusName
    paused_until: datetime | None
    district: str | None
    open_orders: int
    picked_up: int
    no_shows: int
    open_requests: int
    contested: int
    flags_open: int


class AdminClients(CountedPage):
    items: list[AdminClientRow]
    next_cursor: str | None


class ClientReservation(Out):
    """One reservation of a client, as their page lists it."""

    ref: str
    product: str
    pharmacy: str
    state: Literal[
        "OFFERED",
        "RESERVED",
        "PICKED_UP",
        "NOT_AVAILABLE",
        "EXPIRED_NO_SHOW",
        "CANCELLED_BY_CLIENT",
        "CANCELLED_BY_SYSTEM",
    ]
    units: int
    created_at: datetime
    # Until when it can be collected, while it waits.
    deadline: datetime | None
    closed_at: datetime | None
    # A missed pickup an admin cleared no longer counts (R-N3).
    counts_as_no_show: bool


class ClientRequest(Out):
    """One sourcing request of a client, as their page lists it."""

    ref: str
    state: Literal["OPEN", "CLOSED"]
    outcome: str | None
    medicines: int
    secured: int
    created_at: datetime
    ends_at: datetime


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


class AdminClient(Out):
    """A client's page: what they have going, by an ID. The name is not here."""

    client: AdminClientRow
    reservations: list[ClientReservation]
    requests: list[ClientRequest]
    contested: list[ContestedReservation]
    # Raised by code about this client, not handled yet (R-AB).
    flags: list[AbuseFlagRow]


class ClientContact(Out):
    """Read through one audited endpoint only (A-D3)."""

    full_name: str
    email: str
    phone: str | None


# --- Abuse flags (AS-7) -----------------------------------------------------------------------


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


class CatalogProducts(CountedPage):
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
