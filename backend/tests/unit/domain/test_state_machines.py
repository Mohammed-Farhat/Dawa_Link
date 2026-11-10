"""Every state machine of docs/04 §3: who may make which change, and what can never change."""

import pytest

from dawalink.domain.accounts import (
    CLIENT_MACHINE,
    PHARMACY_MACHINE,
    ClientStatus,
    PharmacyStatus,
    client_can_cancel,
    client_can_reserve,
    client_can_search,
    client_can_use_assistant,
    pharmacy_can_manage_inventory,
    pharmacy_can_update_reservations,
)
from dawalink.domain.claims import CLAIM_MACHINE, LIVE_STATES, ClaimState
from dawalink.domain.early_release import (
    ASK_MACHINE,
    EARLY_RELEASE_MACHINE,
    AskState,
    EarlyReleaseState,
)
from dawalink.domain.orders import INITIAL_STATES, OPEN_STATES, ORDER_MACHINE, OrderState
from dawalink.domain.requests import (
    FINAL_ITEM_STATES,
    ITEM_MACHINE,
    REQUEST_MACHINE,
    ItemState,
    RequestState,
)
from dawalink.domain.state_machine import Actor, TransitionNotAllowed

A = Actor
Order = OrderState


@pytest.mark.parametrize(
    ("current", "target", "actor"),
    [
        (Order.OFFERED, Order.RESERVED, A.CLIENT),
        (Order.OFFERED, Order.OFFER_DECLINED, A.CLIENT),
        (Order.OFFERED, Order.OFFER_EXPIRED, A.SYSTEM),
        (Order.OFFERED, Order.OFFER_WITHDRAWN, A.SYSTEM),
        (Order.OFFERED, Order.CANCELLED_BY_SYSTEM, A.SYSTEM),
        (Order.RESERVED, Order.PICKED_UP, A.PHARMACY),
        (Order.RESERVED, Order.NOT_AVAILABLE, A.PHARMACY),
        (Order.RESERVED, Order.EXPIRED_NO_SHOW, A.SYSTEM),
        (Order.RESERVED, Order.CANCELLED_BY_CLIENT, A.CLIENT),
        (Order.RESERVED, Order.CANCELLED_BY_SYSTEM, A.SYSTEM),
    ],
)
def test_order_transitions_of_sm_5(current: Order, target: Order, actor: Actor) -> None:
    ORDER_MACHINE.check(current, target, actor)

    for other in Actor:
        allowed = ORDER_MACHINE.allows(current, target, other)
        assert allowed is (other is actor), f"{other} on {current} -> {target}"


def test_an_order_starts_reserved_by_a_tap_or_offered_by_the_system_or_a_pharmacy() -> None:
    assert {
        Order.RESERVED: frozenset({A.CLIENT}),
        Order.OFFERED: frozenset({A.SYSTEM, A.PHARMACY}),
    } == INITIAL_STATES


def test_terminal_orders_never_change() -> None:
    """INV-4: every state except OFFERED and RESERVED is final."""
    for state in OrderState:
        assert ORDER_MACHINE.is_terminal(state) is (state not in OPEN_STATES)


@pytest.mark.parametrize(
    ("current", "target", "actor"),
    [
        (Order.PICKED_UP, Order.RESERVED, A.PHARMACY),  # no undoing a pickup
        (Order.RESERVED, Order.PICKED_UP, A.CLIENT),  # only the pharmacy hands over
        (Order.RESERVED, Order.PICKED_UP, A.ADMIN),
        (Order.OFFERED, Order.PICKED_UP, A.PHARMACY),  # an offer must be accepted first
        (Order.EXPIRED_NO_SHOW, Order.PICKED_UP, A.PHARMACY),  # no late pickup
        (Order.OFFERED, Order.RESERVED, A.SYSTEM),  # only the client accepts an offer
    ],
)
def test_forbidden_order_changes_are_refused(current: Order, target: Order, actor: Actor) -> None:
    with pytest.raises(TransitionNotAllowed):
        ORDER_MACHINE.check(current, target, actor)


def test_the_agent_can_never_move_an_order_a_request_a_claim_or_an_account() -> None:
    """INV-11 and docs/04 §7: the agent proposes; it has no part in these machines."""
    for machine in (
        ORDER_MACHINE,
        REQUEST_MACHINE,
        CLAIM_MACHINE,
        EARLY_RELEASE_MACHINE,
        ASK_MACHINE,
        PHARMACY_MACHINE,
        CLIENT_MACHINE,
    ):
        assert Actor.AGENT not in machine.actors(), machine.name


def test_the_agent_only_moves_request_items_towards_a_card_or_a_wait() -> None:
    agent_moves = {
        (current, target)
        for (current, target), actors in ITEM_MACHINE.transitions.items()
        if Actor.AGENT in actors
    }

    assert agent_moves == {
        (ItemState.SEARCHING, ItemState.PROPOSED),
        (ItemState.SEARCHING, ItemState.WAITING),
        (ItemState.WAITING, ItemState.PROPOSED),
        (ItemState.WAITING, ItemState.SEARCHING),
    }


def test_only_a_client_tap_secures_an_item() -> None:
    for (_, target), actors in ITEM_MACHINE.transitions.items():
        if target is ItemState.SECURED:
            assert actors == frozenset({Actor.CLIENT})


def test_items_become_unavailable_only_by_the_system_and_cancelled_only_by_the_client() -> None:
    """R-RQ4: the agent never gives up on an item by itself."""
    for (_, target), actors in ITEM_MACHINE.transitions.items():
        if target is ItemState.UNAVAILABLE:
            assert actors == frozenset({Actor.SYSTEM})
        if target is ItemState.CANCELLED:
            assert actors == frozenset({Actor.CLIENT})


def test_a_secured_item_reopens_when_its_reservation_is_marked_not_available() -> None:
    ITEM_MACHINE.check(ItemState.SECURED, ItemState.WAITING, Actor.PHARMACY)
    assert ItemState.SECURED in FINAL_ITEM_STATES
    assert ITEM_MACHINE.is_terminal(ItemState.UNAVAILABLE)
    assert ITEM_MACHINE.is_terminal(ItemState.CANCELLED)


def test_a_request_closes_once_and_stays_closed() -> None:
    REQUEST_MACHINE.check(RequestState.OPEN, RequestState.CLOSED, Actor.SYSTEM)
    REQUEST_MACHINE.check(RequestState.OPEN, RequestState.CLOSED, Actor.CLIENT)
    assert REQUEST_MACHINE.is_terminal(RequestState.CLOSED)


def test_claim_transitions_of_sm_7() -> None:
    C = ClaimState
    CLAIM_MACHINE.check(C.ACTIVE, C.OFFER_PENDING, Actor.SYSTEM)
    CLAIM_MACHINE.check(C.ACTIVE, C.OFFER_PENDING, Actor.PHARMACY)
    CLAIM_MACHINE.check(C.OFFER_PENDING, C.FULFILLED, Actor.CLIENT)
    CLAIM_MACHINE.check(C.FULFILLED, C.ACTIVE, Actor.PHARMACY)
    CLAIM_MACHINE.check(C.OFFER_PENDING, C.EXPIRED, Actor.SYSTEM)
    CLAIM_MACHINE.check(C.ACTIVE, C.CANCELLED, Actor.CLIENT)

    assert frozenset({C.ACTIVE, C.OFFER_PENDING}) == LIVE_STATES
    assert CLAIM_MACHINE.is_terminal(C.EXPIRED)
    assert CLAIM_MACHINE.is_terminal(C.CANCELLED)
    assert not CLAIM_MACHINE.allows(C.FULFILLED, C.CANCELLED, Actor.CLIENT)


def test_early_release_transitions_of_sm_6() -> None:
    EARLY_RELEASE_MACHINE.check(EarlyReleaseState.OPEN, EarlyReleaseState.FULFILLED, Actor.CLIENT)
    EARLY_RELEASE_MACHINE.check(EarlyReleaseState.OPEN, EarlyReleaseState.UNFULFILLED, Actor.SYSTEM)
    for state in (AskState.ACCEPTED, AskState.DECLINED):
        ASK_MACHINE.check(AskState.ASKED, state, Actor.PHARMACY)
    for state in (AskState.EXPIRED, AskState.WITHDRAWN):
        ASK_MACHINE.check(AskState.ASKED, state, Actor.SYSTEM)

    for state in AskState:
        assert ASK_MACHINE.is_terminal(state) is (state is not AskState.ASKED)


def test_pharmacy_account_transitions_of_sm_1() -> None:
    P = PharmacyStatus
    assert set(PHARMACY_MACHINE.transitions) == {
        (P.PENDING, P.APPROVED),
        (P.PENDING, P.REJECTED),
        (P.REJECTED, P.PENDING),
        (P.APPROVED, P.SUSPENDED),
        (P.SUSPENDED, P.APPROVED),
    }
    # Only an admin approves, rejects, suspends or reinstates; a pharmacy only resubmits.
    for (current, target), actors in PHARMACY_MACHINE.transitions.items():
        expected = Actor.PHARMACY if (current, target) == (P.REJECTED, P.PENDING) else Actor.ADMIN
        assert actors == frozenset({expected})


def test_client_account_transitions_of_sm_2() -> None:
    C = ClientStatus
    CLIENT_MACHINE.check(C.UNVERIFIED, C.ACTIVE, Actor.CLIENT)
    CLIENT_MACHINE.check(C.ACTIVE, C.PAUSED, Actor.SYSTEM)
    CLIENT_MACHINE.check(C.PAUSED, C.ACTIVE, Actor.SYSTEM)
    CLIENT_MACHINE.check(C.PAUSED, C.ACTIVE, Actor.ADMIN)
    CLIENT_MACHINE.check(C.ACTIVE, C.SUSPENDED, Actor.ADMIN)
    CLIENT_MACHINE.check(C.SUSPENDED, C.ACTIVE, Actor.ADMIN)

    assert not CLIENT_MACHINE.allows(C.ACTIVE, C.PAUSED, Actor.ADMIN)
    assert not CLIENT_MACHINE.allows(C.UNVERIFIED, C.PAUSED, Actor.SYSTEM)


@pytest.mark.parametrize(
    ("status", "search", "assistant", "reserve", "cancel"),
    [
        (ClientStatus.UNVERIFIED, True, False, False, False),
        (ClientStatus.ACTIVE, True, True, True, True),
        (ClientStatus.PAUSED, True, True, False, True),
        (ClientStatus.SUSPENDED, False, False, False, False),
    ],
)
def test_what_each_client_status_may_do(
    status: ClientStatus, search: bool, assistant: bool, reserve: bool, cancel: bool
) -> None:
    assert client_can_search(status) is search
    assert client_can_use_assistant(status) is assistant
    assert client_can_reserve(status) is reserve
    assert client_can_cancel(status) is cancel


@pytest.mark.parametrize(
    ("status", "inventory", "reservations"),
    [
        (PharmacyStatus.PENDING, False, False),
        (PharmacyStatus.REJECTED, False, False),
        (PharmacyStatus.APPROVED, True, True),
        (PharmacyStatus.SUSPENDED, False, True),  # existing reservations can still be picked up
    ],
)
def test_what_each_pharmacy_status_may_do(
    status: PharmacyStatus, inventory: bool, reservations: bool
) -> None:
    assert pharmacy_can_manage_inventory(status) is inventory
    assert pharmacy_can_update_reservations(status) is reservations
