"""The admin's console (docs/06 §6.10; docs/03 §3).

Every endpoint here asks for the admin role, every change writes an audit event with
the admin's ID, and an action that needs a reason is refused without one. **What is not
here matters as much:** no endpoint changes who gets stock first (R-PRI4), a pharmacy's
stock or a price (A-D7), and none lists conversations: a chat is read only through its
escalation or the report of an answer, as it was stored, without personal details (A-D4).
"""

import uuid
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from sqlalchemy import distinct, func, select

from dawalink.agent.chat import post_team_reply
from dawalink.agent.context import identity_of
from dawalink.agent.guards.redact import redact
from dawalink.api.deps import AsAdmin, DoWork, TheSettings
from dawalink.api.schemas import admin as schemas
from dawalink.api.schemas.accounts import OpeningRange
from dawalink.api.schemas.common import BeforeId, Pin, Skip
from dawalink.db.models import (
    AbuseFlag,
    AnswerReport,
    ChatMessage,
    Escalation,
    Order,
)
from dawalink.domain.accounts import ClientStatus, PharmacyStatus
from dawalink.domain.audit_actions import AuditAction
from dawalink.domain.numbers import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import EscalationState, ReportCategory, ReportState
from dawalink.services import (
    abuse_flags,
    admin_clients,
    admin_pharmacies,
    answer_reports,
    audit,
    catalog,
    escalations,
    health,
    orders,
    pharmacies,
    pharmacy_profile,
)
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

router = APIRouter(prefix="/admin", tags=["admin"])

Cursor = Skip
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]


def _next(offset: int, limit: int, got: int) -> str | None:
    """One row more than the page was asked for: is there a next page?"""
    return str(offset + limit) if got > limit else None


@router.get("/overview")
def overview(_caller: AsAdmin, work: DoWork, settings: TheSettings) -> schemas.AdminOverview:
    """What waits for an admin (AS-2)."""
    with work.tx() as tx:
        open_escalations, emergencies = escalations.open_counts(tx)
        flags_open, flags_high = abuse_flags.open_counts(tx)
        return schemas.AdminOverview(
            pharmacies_waiting=admin_pharmacies.waiting_count(tx),
            pins_to_check=admin_pharmacies.pins_to_check_count(tx),
            escalations_open=open_escalations,
            emergency_claims=emergencies,
            reports_new=answer_reports.new_count(tx),
            flags_open=flags_open,
            flags_high=flags_high,
            # One per missed trip: one contest covers every box of a plan card (R-N3).
            contests_waiting=tx.session.execute(
                select(func.count(distinct(orders.TRIP)))
                .select_from(Order)
                .where(Order.counts_as_no_show.is_(True), Order.contested_at.is_not(None))
            ).scalar_one(),
            demo_mode=settings.demo_mode,
        )


# --- Pharmacies (AS-3, AS-4) ----------------------------------------------------------------


def _pharmacy(tx: Tx, pharmacy_id: uuid.UUID) -> schemas.AdminPharmacy:
    found = admin_pharmacies.detail(tx, pharmacy_id)
    pharmacy = found.pharmacy
    weekly = pharmacies.weekly_hours(tx, [pharmacy.id])[pharmacy.id]
    return schemas.AdminPharmacy(
        id=pharmacy.id,
        name=pharmacy.name,
        status=pharmacy.status,
        status_reason=pharmacy.status_reason,
        info_requested=pharmacy.info_requested,
        email=found.email,
        phone=pharmacy.phone,
        license_number=pharmacy.license_number,
        address=pharmacy.address,
        district=found.district,
        district_id=pharmacy.district_id,
        location=Pin(lat=float(pharmacy.lat), lon=float(pharmacy.lon)),
        pin_checked=pharmacy.location_checked_at is not None,
        pickup_days=pharmacy.pickup_days,
        hours=[
            OpeningRange(weekday=weekday, open=opens, close=closes)
            for weekday, opens, closes in pharmacy_profile.hours_rows(weekly)
        ],
        version=found.version,
        same_address=[
            schemas.OtherPharmacy(id=other.id, name=other.name, status=other.status)
            for other in found.same_address
        ],
        phone_changed_at=found.phone_changed_at,
        moved_at=found.moved_at,
        pin_to_check=found.pin_to_check,
        created_at=pharmacy.created_at,
        approved_at=pharmacy.approved_at,
        live_listings=found.live_listings,
        last_inventory_update=found.last_inventory_update,
        handed_over_30d=found.handed_over_30d,
        not_available_30d=found.not_available_30d,
    )


@router.get("/pharmacies")
def list_pharmacies(
    _caller: AsAdmin,
    work: DoWork,
    status: schemas.PharmacyStatusName | None = None,
    q: Annotated[str, Query(max_length=100)] = "",
    cursor: Cursor = 0,
    limit: PageSize = DEFAULT_PAGE_SIZE,
) -> schemas.AdminPharmacies:
    """Pharmacies whose email is confirmed. `status=PENDING` is the approval queue, the
    one that has waited longest first. `total`: the pharmacies the choices match."""
    chosen = PharmacyStatus(status) if status else None
    with work.tx() as tx:
        rows = admin_pharmacies.listed(
            tx,
            status=chosen,
            query=q,
            offset=cursor,
            limit=limit + 1,
        )
        return schemas.AdminPharmacies(
            total=admin_pharmacies.listed_total(tx, status=chosen, query=q),
            items=[
                schemas.AdminPharmacyRow(
                    id=row.pharmacy.id,
                    name=row.pharmacy.name,
                    status=row.pharmacy.status,
                    info_requested=row.pharmacy.info_requested,
                    pin_to_check=row.pin_to_check,
                    district=row.district,
                    license_number=row.pharmacy.license_number,
                    created_at=row.pharmacy.created_at,
                    approved_at=row.pharmacy.approved_at,
                )
                for row in rows[:limit]
            ],
            next_cursor=_next(cursor, limit, len(rows)),
        )


@router.get("/pharmacies/{pharmacy_id}")
def look_at_pharmacy(
    pharmacy_id: uuid.UUID, _caller: AsAdmin, work: DoWork
) -> schemas.AdminPharmacy:
    with work.tx() as tx:
        return _pharmacy(tx, pharmacy_id)


@router.post("/pharmacies/{pharmacy_id}/approve")
def approve_pharmacy(
    pharmacy_id: uuid.UUID, body: schemas.Approve, caller: AsAdmin, work: DoWork
) -> schemas.AdminPharmacy:
    """PENDING → APPROVED (SM-1). `version` is the one read with the details: if the
    pharmacy corrected them since, the answer is `CHANGED_SINCE` and nothing changes."""
    with work.tx() as tx:
        admin_pharmacies.approve(tx, caller.user_id, pharmacy_id, seen=body.version)
        return _pharmacy(tx, pharmacy_id)


@router.post("/pharmacies/{pharmacy_id}/check-pin")
def confirm_pharmacy_pin(
    pharmacy_id: uuid.UUID, caller: AsAdmin, work: DoWork
) -> schemas.AdminPharmacy:
    """The admin looked at the map: the pin is on the address. For a pharmacy that moved
    by itself; a wrong pin is corrected with `PATCH` instead."""
    with work.tx() as tx:
        admin_pharmacies.check_pin(tx, caller.user_id, pharmacy_id)
        return _pharmacy(tx, pharmacy_id)


@router.post("/pharmacies/{pharmacy_id}/reject")
def reject_pharmacy(
    pharmacy_id: uuid.UUID, body: schemas.WithReason, caller: AsAdmin, work: DoWork
) -> schemas.AdminPharmacy:
    """PENDING → REJECTED. The pharmacy reads the reason, and may correct and resubmit."""
    with work.tx() as tx:
        admin_pharmacies.reject(tx, caller.user_id, pharmacy_id, reason=body.reason)
        return _pharmacy(tx, pharmacy_id)


@router.post("/pharmacies/{pharmacy_id}/request-info")
def ask_pharmacy_for_more(
    pharmacy_id: uuid.UUID, body: schemas.WithReason, caller: AsAdmin, work: DoWork
) -> schemas.AdminPharmacy:
    """Still PENDING: the pharmacy reads what is missing (`reason`) and corrects it."""
    with work.tx() as tx:
        admin_pharmacies.request_info(tx, caller.user_id, pharmacy_id, message=body.reason)
        return _pharmacy(tx, pharmacy_id)


@router.post("/pharmacies/{pharmacy_id}/suspend")
def suspend_pharmacy(
    pharmacy_id: uuid.UUID, body: schemas.WithReason, caller: AsAdmin, work: DoWork
) -> schemas.AdminPharmacy:
    """APPROVED → SUSPENDED: its listings are hidden, the offers on its boxes are
    cancelled and its open asks withdrawn. Reservations already made are kept (SM-1)."""
    with work.tx() as tx:
        admin_pharmacies.suspend(tx, caller.user_id, pharmacy_id, reason=body.reason)
        return _pharmacy(tx, pharmacy_id)


@router.post("/pharmacies/{pharmacy_id}/reinstate")
def reinstate_pharmacy(
    pharmacy_id: uuid.UUID, body: schemas.WithReason, caller: AsAdmin, work: DoWork
) -> schemas.AdminPharmacy:
    """SUSPENDED → APPROVED: its listings are visible again (SM-1)."""
    with work.tx() as tx:
        admin_pharmacies.reinstate(tx, caller.user_id, pharmacy_id, reason=body.reason)
        return _pharmacy(tx, pharmacy_id)


@router.patch("/pharmacies/{pharmacy_id}")
def edit_pharmacy(
    pharmacy_id: uuid.UUID, body: schemas.AdminPharmacyEdit, caller: AsAdmin, work: DoWork
) -> schemas.AdminPharmacy:
    """An admin corrects a name, a licence, a phone, an address or the pin (SM-1). Only
    what is sent is checked and changed; the audit event names the fields, not the values."""
    sent = body.model_fields_set
    with work.tx() as tx:
        admin_pharmacies.edit(
            tx,
            caller.user_id,
            pharmacy_id,
            reason=body.reason,
            name=body.name if "name" in sent else None,
            license_number=body.license_number if "license_number" in sent else None,
            phone=body.phone if "phone" in sent else None,
            address=body.address if "address" in sent else None,
            district_id=body.district_id if "district_id" in sent else None,
            location=(body.location.lat, body.location.lon)
            if "location" in sent and body.location is not None
            else None,
        )
        return _pharmacy(tx, pharmacy_id)


# --- Clients (AS-5) ---------------------------------------------------------------------------


def _client_row(row: admin_clients.Listed) -> schemas.AdminClientRow:
    return schemas.AdminClientRow(
        id=row.client_id,
        status=row.status,
        paused_until=row.paused_until,
        district=row.district,
        open_orders=row.open_orders,
        picked_up=row.picked_up,
        no_shows=row.no_shows,
        open_requests=row.open_requests,
        contested=row.contested,
        flags_open=row.flags_open,
    )


def _contested_rows(
    tx: Tx, found: list[admin_clients.OrderLine]
) -> list[schemas.ContestedReservation]:
    return [
        schemas.ContestedReservation(
            id=line.order.id,
            ref=line.order.ref,
            product=line.product,
            pharmacy=line.pharmacy,
            expired_at=line.order.closed_at,
            contested_at=line.order.contested_at or tx.now,
            counts_as_no_show=line.order.counts_as_no_show,
        )
        for line in found
    ]


def _contested(tx: Tx, client_id: uuid.UUID) -> list[schemas.ContestedReservation]:
    """The client's contests that still count: on their page, each waits for [Clear]."""
    return _contested_rows(tx, admin_clients.contested_orders(tx, client_id))


def _contested_in_case(tx: Tx, row: Escalation) -> list[schemas.ContestedReservation]:
    """What this case is about, never what the client contests elsewhere (B#61): the
    reservation pressed, with its trip and how it ended. Nothing for a case of another
    kind. A complaint from before the case remembered its reservation is about the
    contested reservations its summary names."""
    pressed = escalations.contested_orders(row)
    if pressed:
        found = admin_clients.missed_trips_of(tx, row.client_id, pressed)
    else:
        refs = escalations.refs_in_complaints(row)
        found = admin_clients.contested_by_number(tx, row.client_id, refs)
    return _contested_rows(tx, found)


def _flag(row: AbuseFlag) -> schemas.AbuseFlagRow:
    return schemas.AbuseFlagRow(
        id=row.id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        rule=row.rule,
        severity=row.severity,
        evidence=row.evidence,
        state=row.state,
        action=row.action,
        created_at=row.created_at,
    )


def _client(tx: Tx, row: admin_clients.Listed) -> schemas.AdminClient:
    return schemas.AdminClient(
        client=_client_row(row),
        reservations=[
            schemas.ClientReservation(
                ref=found.order.ref,
                product=found.product,
                pharmacy=found.pharmacy,
                state=found.order.state,
                units=found.order.qty_picked_up
                if found.order.qty_picked_up is not None
                else found.order.qty_requested,
                created_at=found.order.created_at,
                deadline=found.order.deadline,
                closed_at=found.order.closed_at,
                counts_as_no_show=found.order.counts_as_no_show,
            )
            for found in admin_clients.reservations(tx, row.client_id)
        ],
        requests=[
            schemas.ClientRequest(
                ref=found.request.ref,
                state=found.request.state,
                outcome=found.request.outcome,
                medicines=found.medicines,
                secured=found.secured,
                created_at=found.request.created_at,
                ends_at=found.request.ends_at,
            )
            for found in admin_clients.requests_of(tx, row.client_id)
        ],
        contested=_contested(tx, row.client_id),
        flags=[_flag(flag) for flag in abuse_flags.open_about(tx, row.client_id)],
    )


@router.get("/clients")
def list_clients(
    _caller: AsAdmin,
    work: DoWork,
    status: schemas.ClientStatusName | None = None,
    having: Literal["reservation", "picked_up", "request", "look"] | None = None,
    ref: Annotated[str, Query(max_length=20)] = "",
    cursor: Cursor = 0,
    limit: PageSize = DEFAULT_PAGE_SIZE,
) -> schemas.AdminClients:
    """Clients as statuses and counts: **no name, no email, no phone**. `ref` finds the
    client of an order number or a request number. `having` keeps the clients with a
    reservation going, who picked an order up, with an open request, or who need a look
    (a contested no-show or an open flag). `total`: the clients the choices match."""
    chosen = ClientStatus(status) if status else None
    with work.tx() as tx:
        rows = admin_clients.listed(
            tx,
            status=chosen,
            having=having,
            ref=ref,
            offset=cursor,
            limit=limit + 1,
        )
        return schemas.AdminClients(
            total=admin_clients.listed_total(tx, status=chosen, having=having, ref=ref),
            items=[_client_row(row) for row in rows[:limit]],
            next_cursor=_next(cursor, limit, len(rows)),
        )


@router.get("/clients/{client_id}")
def look_at_client(client_id: uuid.UUID, _caller: AsAdmin, work: DoWork) -> schemas.AdminClient:
    """One client by their ID: the counts, their last reservations and requests with
    how each ended, what they contest, and the flags about them. **Still no name:** that
    is the audited `/contact` below."""
    with work.tx() as tx:
        return _client(tx, admin_clients.one(tx, client_id))


@router.get("/clients/{client_id}/contact")
def view_client_contact(
    client_id: uuid.UUID, caller: AsAdmin, work: DoWork
) -> schemas.ClientContact:
    """The client's name, email and phone, for support. **Each view is written to the
    audit log**, and an admin gets 30 an hour (N-47): past that, `RATE_LIMITED`."""
    try:
        with work.tx() as tx:
            found = admin_clients.contact(tx, caller.user_id, client_id)
            return schemas.ClientContact(
                full_name=found.full_name, email=found.email, phone=found.phone
            )
    except ServiceError as refused:
        if refused.code is Code.RATE_LIMITED:
            # The refusal rolled its own work back: it is noted in a transaction of its own.
            with work.tx() as tx:
                admin_clients.note_contact_limit(tx, caller.user_id)
        raise


@router.post("/clients/{client_id}/lift-pause")
def lift_client_pause(
    client_id: uuid.UUID, body: schemas.WithReason, caller: AsAdmin, work: DoWork
) -> schemas.AdminClient:
    with work.tx() as tx:
        row = admin_clients.lift_pause(tx, caller.user_id, client_id, reason=body.reason)
        return _client(tx, row)


@router.post("/clients/{client_id}/suspend")
def suspend_client(
    client_id: uuid.UUID, body: schemas.WithReason, caller: AsAdmin, work: DoWork
) -> schemas.AdminClient:
    """Every login of the client ends at once; their open requests and watches end, and
    their open reservations and offers are cancelled (SM-2)."""
    with work.tx() as tx:
        row = admin_clients.suspend(tx, caller.user_id, client_id, reason=body.reason)
        return _client(tx, row)


@router.post("/clients/{client_id}/reinstate")
def reinstate_client(
    client_id: uuid.UUID, body: schemas.WithReason, caller: AsAdmin, work: DoWork
) -> schemas.AdminClient:
    with work.tx() as tx:
        row = admin_clients.reinstate(tx, caller.user_id, client_id, reason=body.reason)
        return _client(tx, row)


@router.post("/reservations/{reservation_id}/clear-no-show")
def clear_no_show(
    reservation_id: uuid.UUID, body: schemas.WithReason, caller: AsAdmin, work: DoWork
) -> schemas.AdminClient:
    """The admin accepts a contest: the expired reservation no longer counts as a
    no-show, and a pause it caused is lifted if it no longer applies (R-N3). The
    reservation itself is not changed."""
    with work.tx() as tx:
        order = orders.clear_no_show(tx, caller.user_id, reservation_id, reason=body.reason)
        return _client(tx, admin_clients.one(tx, order.client_id))


# --- Abuse flags (AS-7) -----------------------------------------------------------------------


# A flag is read on the page of the client it is about (`flags` of a client's page):
# there is no list of flags on its own. A flag holds counts and IDs, never a message.


@router.post("/abuse-flags/{flag_id}/dismiss")
def dismiss_abuse_flag(
    flag_id: uuid.UUID, body: schemas.WithReason, caller: AsAdmin, work: DoWork
) -> schemas.AbuseFlagRow:
    with work.tx() as tx:
        return _flag(abuse_flags.dismiss(tx, caller.user_id, flag_id, reason=body.reason))


@router.post("/abuse-flags/{flag_id}/act")
def act_on_abuse_flag(
    flag_id: uuid.UUID, body: schemas.FlagAction, caller: AsAdmin, work: DoWork
) -> schemas.AbuseFlagRow:
    """`warn` records that the account's owner was warned; `suspend` suspends the
    account, with everything a suspension does."""
    with work.tx() as tx:
        return _flag(
            abuse_flags.act(tx, caller.user_id, flag_id, action=body.action, reason=body.reason)
        )


# --- The catalog (AS-9), read-only ------------------------------------------------------------


@router.get("/catalog/products")
def read_catalog(
    _caller: AsAdmin,
    work: DoWork,
    q: Annotated[str, Query(max_length=100)] = "",
    cursor: Cursor = 0,
    limit: PageSize = DEFAULT_PAGE_SIZE,
) -> schemas.CatalogProducts:
    """Every product of the Ministry's list as imported, the controlled ones included.
    Nothing here changes the catalog: the import script and the team's files do.
    `total`: the products the text matches."""
    with work.tx() as tx:
        rows, total = catalog.admin_products(tx, q, offset=cursor, limit=limit + 1)
        shown = rows[:limit]
        sizes = catalog.group_sizes(
            tx, [row.equivalence_key for row in shown if row.equivalence_key]
        )
        return schemas.CatalogProducts(
            total=total,
            items=[
                schemas.CatalogProduct(
                    id=row.id,
                    code=row.moph_code,
                    name=row.moph_name,
                    strength=row.dosage_text,
                    form=row.form_text,
                    pack=row.presentation_text,
                    manufacturer=row.manufacturer,
                    public_price_lbp=row.public_price_lbp,
                    prescription_required=row.prescription_required,
                    controlled=row.controlled,
                    same_medicine=sizes.get(row.equivalence_key or "", 0),
                )
                for row in shown
            ],
            next_cursor=_next(cursor, limit, len(rows)),
        )


@router.get("/catalog/imports")
def read_catalog_imports(_caller: AsAdmin, work: DoWork) -> schemas.CatalogImports:
    with work.tx() as tx:
        return schemas.CatalogImports(
            items=[
                schemas.CatalogImportRow(
                    id=row.id,
                    file_name=row.file_name,
                    source_date=row.source_date,
                    lbp_per_usd=float(row.lbp_per_usd),
                    rows_total=row.rows_total,
                    rows_imported=row.rows_imported,
                    imported_at=row.imported_at,
                )
                for row in catalog.imports(tx)
            ]
        )


# --- Health (AS-2, AS-10) ---------------------------------------------------------------------


@router.get("/health")
def read_health(
    _caller: AsAdmin,
    work: DoWork,
    settings: TheSettings,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> schemas.AdminHealth:
    """The agent's numbers (turns, latency, errors, cost, guards), what it achieved
    (requests fulfilled, re-plans, early release), the marketplace's, the system's, and
    the alerts that fire now (R-AL). Counted from our own tables: no personal data."""
    with work.tx() as tx:
        found = health.read(tx, days=days, monthly_budget_usd=settings.llm_monthly_budget_usd)
        return schemas.AdminHealth(
            days=found.days,
            agent=found.agent,
            requests=found.requests,
            marketplace=found.marketplace,
            system=found.system,
            alerts=found.alerts,
        )


# --- Escalations (AS-6) -----------------------------------------------------------------------


def _escalation(tx: Tx, row: Escalation, mark: escalations.Marks) -> schemas.EscalationRow:
    return schemas.EscalationRow(
        id=row.id,
        client_id=row.client_id,
        reason=row.reason,
        state=row.state,
        summary=row.summary,
        request_ref=escalations.request_ref(tx, row),
        notes=[
            schemas.EscalationNote(
                reason=str(note.get("reason", "")),
                summary=str(note.get("summary", "")),
                at=note.get("at"),
            )
            for note in escalations.said_later(row)
        ],
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        resolution_note=row.resolution_note,
        reasons=mark.reasons,
        last_summary=mark.last_summary,
        last_asked_at=mark.last_asked_at,
        last_replied_at=mark.last_replied_at,
        new_ask_since_reply=mark.new_ask_since_reply,
        client_wrote_at=mark.client_wrote_at,
        hold_ends_at=mark.hold_ends_at,
    )


def _escalation_rows(tx: Tx, rows: Sequence[Escalation]) -> list[schemas.EscalationRow]:
    known = escalations.marks(tx, rows)
    return [_escalation(tx, row, known[row.id]) for row in rows]


def _card_kinds(tx: Tx, message: ChatMessage) -> list[str]:
    return [card["type"] for card in answer_reports.cards_of(tx, message)]


def _escalation_detail(tx: Tx, row: Escalation) -> schemas.EscalationDetail:
    parts = escalations.thread_parts(tx, row)
    (shown,) = _escalation_rows(tx, [row])
    return schemas.EscalationDetail(
        escalation=shown,
        thread=[
            schemas.ThreadMessage(
                seq=message.seq,
                author=message.author,
                text=message.text_redacted,
                cards=_card_kinds(tx, message),
                created_at=message.created_at,
                starts_another_chat=number > 0 and place == 0,
            )
            for number, part in enumerate(parts)
            for place, message in enumerate(part)
        ],
        contested=_contested_in_case(tx, row),
    )


@router.get("/escalations")
def list_escalations(
    _caller: AsAdmin,
    work: DoWork,
    state: schemas.EscalationStateName | None = None,
    cursor: Cursor = 0,
    limit: PageSize = DEFAULT_PAGE_SIZE,
) -> schemas.Escalations:
    """Without `state`: every escalation that is not resolved, emergency claims first,
    then the cases that wait for the team (never answered, asked again, or the client
    wrote since the team's reply), then the answered ones; inside each, the one whose
    newest ask is the oldest first. `RESOLVED`: the newest closed first. `total`: the
    cases the choice matches."""
    with work.tx() as tx:
        found = escalations.listed(
            tx,
            state=EscalationState(state) if state else None,
            offset=cursor,
            limit=limit + 1,
        )
        return schemas.Escalations(
            items=_escalation_rows(tx, found.rows[:limit]),
            next_cursor=_next(cursor, limit, len(found.rows)),
            total=found.total,
        )


@router.get("/escalations/{escalation_id}")
def read_escalation(
    escalation_id: uuid.UUID, _caller: AsAdmin, work: DoWork
) -> schemas.EscalationDetail:
    """The escalation with the conversation it came from, as stored: personal details
    were removed before it was written (A-D4, INV-10)."""
    with work.tx() as tx:
        return _escalation_detail(tx, escalations.one(tx, escalation_id))


@router.post("/escalations/{escalation_id}/reply")
def reply_to_escalation(
    escalation_id: uuid.UUID, body: schemas.TeamReply, caller: AsAdmin, work: DoWork
) -> schemas.EscalationDetail:
    """The client reads the reply in their conversation, signed "DawaLink team", and is
    notified (CN-14). It is stored as typed (a person may have to give a phone number),
    and cleaned where the model or an export reads it. A first reply marks the
    escalation as being handled. **It changes no order and no priority** (R-PRI4)."""
    with work.tx() as tx:
        post_team_reply(tx, admin_id=caller.user_id, escalation_id=escalation_id, text=body.text)
        return _escalation_detail(tx, escalations.one(tx, escalation_id))


@router.post("/escalations/{escalation_id}/resolve")
def resolve_escalation(
    escalation_id: uuid.UUID, body: schemas.Resolve, caller: AsAdmin, work: DoWork
) -> schemas.EscalationDetail:
    """[Close this case]. A note of what was done may go with it; none is asked for."""
    with work.tx() as tx:
        escalation = escalations.one(tx, escalation_id)
        note = redact(body.note, identity_of(tx, escalation.client_id)).text
        resolved = escalations.resolve(tx, caller.user_id, escalation_id, note=note)
        return _escalation_detail(tx, resolved)


# --- Reported answers (AS-8) ------------------------------------------------------------------


def _line(stored: Any) -> schemas.ReportedLine:
    line = stored if isinstance(stored, dict) else {}
    return schemas.ReportedLine(
        seq=int(line.get("seq", 0)),
        author=str(line.get("author", "")),
        text=line.get("text"),
        cards=[
            schemas.ReportedCard(
                origin=str(card.get("origin", "")),
                type=str(card.get("type", "")),
                title=str(card.get("title", "")),
                recommended=bool(card.get("recommended")),
            )
            for card in line.get("cards", [])
            if isinstance(card, dict)
        ],
        quick_replies=[str(chip) for chip in line.get("quick_replies", [])],
    )


def _report(row: AnswerReport) -> schemas.AnswerReportRow:
    reply = row.snapshot.get("reply") or {}
    before = [line for line in row.snapshot.get("context", []) if isinstance(line, dict)]
    asked = [line.get("text") for line in before if line.get("author") == "client"]
    return schemas.AnswerReportRow(
        id=row.id,
        state=row.state,
        reason=row.reason,
        comment=row.comment,
        category=row.category,
        in_regression=row.exported_at is not None,
        reply=str(reply.get("text") or ""),
        asked=str(asked[-1]) if asked and asked[-1] else None,
        created_at=row.created_at,
    )


def _report_detail(row: AnswerReport) -> schemas.AnswerReportDetail:
    run = row.snapshot.get("run")
    return schemas.AnswerReportDetail(
        report=_report(row),
        conversation_kind=str(row.snapshot.get("conversation_kind", "chat")),
        reply=_line(row.snapshot.get("reply")),
        context=[_line(line) for line in row.snapshot.get("context", [])],
        run=None
        if not isinstance(run, dict)
        else schemas.ReportedRun(
            id=str(run.get("id", "")),
            mode=run.get("mode"),
            trigger=run.get("trigger"),
            model=run.get("model"),
            prompt_version=run.get("prompt_version"),
            outcome=run.get("outcome"),
            guardrails=[str(guard) for guard in run.get("guardrails", [])],
            trace_id=run.get("trace_id"),
        ),
    )


@router.get("/answer-reports")
def list_answer_reports(
    _caller: AsAdmin,
    work: DoWork,
    state: schemas.ReportStateName | None = "NEW",
    cursor: Cursor = 0,
    limit: PageSize = DEFAULT_PAGE_SIZE,
) -> schemas.AnswerReports:
    """The newest first. `total`: the reports the choice matches."""
    with work.tx() as tx:
        found = answer_reports.listed(
            tx, state=ReportState(state) if state else None, offset=cursor, limit=limit + 1
        )
        return schemas.AnswerReports(
            items=[_report(row) for row in found.rows[:limit]],
            next_cursor=_next(cursor, limit, len(found.rows)),
            total=found.total,
        )


@router.get("/answer-reports/export")
def export_regression_cases(caller: AsAdmin, work: DoWork) -> schemas.RegressionCases:
    """The confirmed reports that were added to the regression set (A-D6): the reply, the
    messages before it and the agent turn, without personal details. Audited."""
    with work.tx() as tx:
        cases = answer_reports.regression_cases(tx)
        audit.record(
            tx,
            Actor.ADMIN,
            "answer_report.export",
            "answer_report",
            None,
            actor_id=caller.user_id,
            after={"cases": len(cases)},
        )
        return schemas.RegressionCases(cases=cases)


@router.get("/answer-reports/{report_id}")
def read_answer_report(
    report_id: uuid.UUID, _caller: AsAdmin, work: DoWork
) -> schemas.AnswerReportDetail:
    with work.tx() as tx:
        return _report_detail(answer_reports.one(tx, report_id))


@router.post("/answer-reports/{report_id}/dismiss")
def dismiss_answer_report(
    report_id: uuid.UUID, caller: AsAdmin, work: DoWork
) -> schemas.AnswerReportDetail:
    """[Not a problem]."""
    with work.tx() as tx:
        return _report_detail(answer_reports.dismiss(tx, caller.user_id, report_id))


@router.post("/answer-reports/{report_id}/confirm")
def confirm_answer_report(
    report_id: uuid.UUID, body: schemas.ConfirmReport, caller: AsAdmin, work: DoWork
) -> schemas.AnswerReportDetail:
    """[Real problem]: the report is confirmed and joins the regression cases the
    export gives (A-D6). A category may be sent; the console sends none."""
    with work.tx() as tx:
        return _report_detail(
            answer_reports.confirm(
                tx,
                caller.user_id,
                report_id,
                category=ReportCategory(body.category),
                add_to_regression=body.add_to_regression,
            )
        )


# --- The audit log (AS-11) --------------------------------------------------------------------

# The codes the console has a sentence for (`domain/audit_actions.py`).
_KNOWN_ACTIONS = {code.value: code for code in AuditAction}


def _audit_row(row: audit.Shown) -> schemas.AuditRow:
    event = row.event
    return schemas.AuditRow(
        id=event.id,
        occurred_at=event.occurred_at,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        action=event.action,
        known_action=_KNOWN_ACTIONS.get(event.action),
        who=schemas.AuditWho(kind=row.who.kind, name=row.who.name, id=row.who.id),
        subject=None
        if row.subject is None
        else schemas.AuditSubject(kind=row.subject.kind, id=row.subject.id),
        changed=row.changed,
        state_from=row.state_from,
        state_to=row.state_to,
        counts=row.counts,
        code=row.code,
        reason=event.reason,
    )


@router.get("/audit")
def read_audit_log(
    _caller: AsAdmin,
    work: DoWork,
    entity_type: Annotated[str | None, Query(max_length=40)] = None,
    entity_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    kind: schemas.AuditKindName | None = None,
    actor: Annotated[Actor | None, Query()] = None,
    cursor: BeforeId = None,
    offset: Skip = 0,
    limit: PageSize = DEFAULT_PAGE_SIZE,
) -> schemas.AuditPage:
    """Who changed what, newest first. Read-only: nothing can change or delete an event.
    `action=pharmacy.` gives every action of that kind, `kind` one family of the "Kind"
    filter. `cursor` is the last ID seen; `offset` skips that many events of what is left
    (numbered pages send only `offset`). `total`: the events the choices match, wherever
    the page is. **A changed field is named, never its value.**"""
    choices: dict[str, Any] = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "kind": kind,
        "actor_type": actor,
    }
    with work.tx() as tx:
        rows = audit.listed(tx, **choices, before_id=cursor, offset=offset, limit=limit + 1)
        shown = rows[:limit]
        return schemas.AuditPage(
            items=[_audit_row(row) for row in audit.shown(tx, shown)],
            next_cursor=str(shown[-1].id) if len(rows) > limit and shown else None,
            total=audit.listed_total(tx, **choices),
        )
