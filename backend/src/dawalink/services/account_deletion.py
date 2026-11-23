"""A client deletes their own account (docs/04 R-AU10; the owner, 2026-11-20).

The client types their password again, and in **one transaction**:
1. everything they have going ends, in the order a suspension uses and for the same
   reason (`admin_clients.end_what_they_have`), but as the client's own acts: their
   requests and watches end, then their reservations are cancelled and the pharmacies are
   told as for any cancel. No missed pickup is counted;
2. what is personal is erased at once: the name, the phone, the date of birth, where they
   live, their last searches, the email (replaced by one nobody can type), the network
   address they signed up from, and the locations kept on their requests and watches;
3. every login and every link ends, so every device is logged out; nothing in flight can
   act for them any more (an agent turn, a follow-up, a card in a chat);
4. the open escalations and flags about them close.

The user row itself stays, emptied: reservations, the books and the audit log point at
it, and after this nothing leads from them to a person. What the app's login may not
delete (the chats, the notifications, the emails) is deleted by the clean-up a moment
later (`daily.empty_deleted_account`, a task of the clock check). **No email is sent**
about it: the address is gone.
"""

import uuid

from sqlalchemy import delete, select, update

from dawalink.db.models import (
    AbuseFlag,
    Claim,
    Conversation,
    EmailOutbox,
    Escalation,
    Proposal,
    SearchHistory,
    SourcingRequest,
)
from dawalink.domain.accounts import CLIENT_MACHINE, ClientStatus
from dawalink.domain.state_machine import Actor, TransitionNotAllowed
from dawalink.domain.vocabulary import (
    ConversationStatus,
    EscalationState,
    FlagState,
    FlagSubject,
    OutboxState,
)
from dawalink.services import admin_clients, audit, auth, clients
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

# Written on what an admin had open about the client: the reason it closed.
CLOSED_BY_DELETION = "The client deleted their account."
_REASON = "the client deleted their account"


def delete_own_account(tx: Tx, client_id: uuid.UUID, *, password: str) -> bool:
    """The client deletes their account. **Returns False if the password is wrong**, after
    counting it like a failed login (R-AU2): the caller commits that count, then answers.
    Nothing else changed, and the client stays logged in.

    The caller holds a password slot, taken before this transaction opened.
    """
    # The client's profile is the first lock, as in every flow that changes what a client
    # has going (docs/05 §6). Taking the user's row first would wait for the profile while
    # holding a lock that a reservation's notification needs (its key on `users`): a
    # deadlock with the clock check or a pharmacy's tap.
    client = clients.profile(tx, client_id, lock=True)
    user = auth.confirm_password(tx, client_id, password)
    if user is None:
        return False
    before = ClientStatus(client.status)
    try:
        CLIENT_MACHINE.check(before, ClientStatus.DELETED, Actor.CLIENT)
    except TransitionNotAllowed:
        # Suspended (a suspended client can't log in, so only a race gets here).
        raise ServiceError(Code.ACCOUNT_SUSPENDED, "This account is suspended.") from None

    ended = admin_clients.end_what_they_have(tx, client_id, admin_id=None, reason=_REASON)

    client.status = ClientStatus.DELETED.value
    client.deleted_at = tx.real_now
    clients.erase(tx, client)
    tx.session.execute(delete(SearchHistory).where(SearchHistory.client_id == client_id))
    auth.close_login(tx, user)
    _stop_what_is_in_flight(tx, client_id)
    _erase_kept_locations(tx, client_id)
    escalations_closed = _close_escalations(tx, client_id)
    flags_closed = _close_flags(tx, client_id)
    _drop_emails(tx, client_id)
    audit.record(
        tx,
        Actor.CLIENT,
        "client.deleted",
        "client",
        client_id,
        actor_id=client_id,
        before={"status": before.value},
        after={
            "status": client.status,
            "orders_cancelled": ended.orders_cancelled,
            "requests_closed": ended.requests_closed,
            "watches_ended": ended.watches_ended,
            "escalations_closed": escalations_closed,
            "flags_closed": flags_closed,
        },
    )
    return True


def _stop_what_is_in_flight(tx: Tx, client_id: uuid.UUID) -> None:
    """Nothing may act for a deleted account once this transaction commits (R-AU10).

    Its conversations are put away: no turn is waiting or scheduled on them any more, and
    a turn that is running loses its lease, so it saves nothing at its next step. Its open
    cards expire, so a tap on one is refused even before the logins that ended refuse it.
    """
    tx.session.execute(
        update(Conversation)
        .where(Conversation.client_id == client_id)
        .values(
            status=ConversationStatus.ARCHIVED.value,
            pending_turn_at=None,
            followup_at=None,
            turn_lease_until=None,
            turn_owner=None,
            loc_lat=None,
            loc_lon=None,
            loc_source=None,
            loc_area_id=None,
            loc_set_at=None,
        )
    )
    tx.session.execute(
        update(Proposal)
        .where(
            Proposal.client_id == client_id,
            Proposal.used_at.is_(None),
            Proposal.expires_at > tx.now,
        )
        .values(expires_at=tx.now)
    )


def _erase_kept_locations(tx: Tx, client_id: uuid.UUID) -> None:
    """Requests and watches are kept, and their location would otherwise stay for 30 days
    after they closed (N-43): it goes now."""
    tx.session.execute(
        update(SourcingRequest)
        .where(SourcingRequest.client_id == client_id, SourcingRequest.loc_lat.is_not(None))
        .values(loc_lat=None, loc_lon=None, loc_source=None)
    )
    tx.session.execute(
        update(Claim)
        .where(Claim.client_id == client_id, Claim.loc_lat.is_not(None))
        .values(loc_lat=None, loc_lon=None)
    )


def _close_escalations(tx: Tx, client_id: uuid.UUID) -> int:
    """The client's open case closes: there is nobody left to answer (SM-9)."""
    found = (
        tx.session.execute(
            select(Escalation)
            .where(
                Escalation.client_id == client_id,
                Escalation.state != EscalationState.RESOLVED.value,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    for escalation in found:
        before = escalation.state
        escalation.state = EscalationState.RESOLVED.value
        escalation.resolution_note = CLOSED_BY_DELETION
        escalation.resolved_at = tx.now
        audit.record(
            tx,
            Actor.CLIENT,
            "escalation.resolve",
            "escalation",
            escalation.id,
            actor_id=client_id,
            before={"state": before},
            after={"state": escalation.state},
            reason=_REASON,
        )
    return len(found)


def _close_flags(tx: Tx, client_id: uuid.UUID) -> int:
    """The flags about the client that nobody handled close: there is no account left to
    look at (SM-11). DISMISSED, with no admin and no action: nobody acted on them."""
    found = (
        tx.session.execute(
            select(AbuseFlag)
            .where(
                AbuseFlag.subject_type == FlagSubject.CLIENT.value,
                AbuseFlag.subject_id == client_id,
                AbuseFlag.state == FlagState.OPEN.value,
            )
            .order_by(AbuseFlag.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    for flag in found:
        flag.state, flag.resolved_at = FlagState.DISMISSED.value, tx.now
        audit.record(
            tx,
            Actor.SYSTEM,
            "abuse_flag.dismiss",
            "abuse_flag",
            flag.id,
            before={"state": FlagState.OPEN.value},
            after={"state": flag.state, "action": None},
            reason=_REASON,
        )
    return len(found)


def _drop_emails(tx: Tx, client_id: uuid.UUID) -> None:
    """No email goes to a deleted account (R-AU10): the ones still waiting, those that
    ending their things just queued included, are dropped."""
    tx.session.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.user_id == client_id,
            EmailOutbox.state.in_((OutboxState.QUEUED.value, OutboxState.FAILED.value)),
        )
        .values(state=OutboxState.DROPPED.value, last_error=None)
    )
