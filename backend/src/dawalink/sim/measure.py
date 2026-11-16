"""What a simulated day achieved, read from the database when it is over (docs/08 E2).

The same code measures every contender, from the same tables: a reservation counts
whoever made it happen.
"""

import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from dawalink.db.models import AgentRun, InventoryItem, Order, Pharmacy
from dawalink.domain.numbers import (
    EARLY_RELEASE_MAX_DAYS,
    MAX_TURNS_PER_REQUEST,
    NEAR_EXPIRY_MAX_DAYS,
)
from dawalink.domain.pricing import early_release_suggested_price_lbp
from dawalink.services import travel
from dawalink.sim.engine import Decision, Sim
from dawalink.sim.scenario import Need

# A reservation that held until the client came, or didn't come. One that a pharmacy
# marked "not available", or that was cancelled, never secured anything.
SECURED = ("RESERVED", "PICKED_UP", "EXPIRED_NO_SHOW")


@dataclass(frozen=True)
class NeedResult:
    """One client's need, and what became of it."""

    n: int
    client_n: int
    medicines: int
    units_wanted: int
    # Units reserved before the 6-hour window closed, and still reserved at the end.
    units_secured: int
    # Minutes from the request to the last unit, when everything was secured.
    minutes_to_secure: int | None
    taps: int
    messages: int
    reservations: int
    # Reservations at a pharmacy this client can't really use (closed when free, too far).
    cant_work: int
    # Extra minutes of travel against the best pharmacy that works, summed over reservations.
    extra_minutes: int
    travel_minutes: int
    other_brand_units: int
    # Reserved, and nobody came before the pharmacy closed.
    no_shows: int
    # Reserved boxes that expire before the client's last day of use: must be 0 (R-F1).
    boxes_that_dont_last: int
    # Cards to reserve that this client couldn't use, and those among them that came
    # after the client had written why (the contender didn't adapt).
    unusable_cards: int = 0
    unusable_after_told: int = 0

    @property
    def fulfilled(self) -> bool:
        return self.units_secured >= self.units_wanted


def _orders_by_client(sim: Sim) -> dict[uuid.UUID, list[tuple[Order, Any]]]:
    with sim.tx() as tx:
        rows = tx.session.execute(
            select(Order, InventoryItem.expiry_date)
            .join(InventoryItem, InventoryItem.id == Order.inventory_item_id)
            .where(Order.state.in_(SECURED))
        ).all()
    found: dict[uuid.UUID, list[tuple[Order, Any]]] = defaultdict(list)
    for order, expiry in rows:
        found[order.client_id].append((order, expiry))
    return found


def _units(order: Order) -> int:
    """The units this reservation held for the client: still held, handed over, or held
    until the pharmacy closed without anyone coming."""
    if order.state == "PICKED_UP":
        return order.qty_picked_up or 0
    if order.state == "EXPIRED_NO_SHOW":
        return order.qty_requested
    return order.qty_locked


def need_result(sim: Sim, need: Need, orders: list[tuple[Order, Any]]) -> NeedResult:
    wanted = {sim.medicine_of[line.product_id]: line for line in need.lines}
    secured: dict[str, int] = defaultdict(int)
    last = None
    decisions: list[Decision] = []
    dont_last = 0
    no_shows = 0
    for order, expiry in orders:
        medicine = sim.medicine_of.get(order.product_id)
        reserved_at = order.reserved_at
        if medicine not in wanted or reserved_at is None or reserved_at > sim.window_ends(need):
            continue
        secured[medicine] += _units(order)
        no_shows += order.state == "EXPIRED_NO_SHOW"
        last = reserved_at if last is None else max(last, reserved_at)
        if order.id in sim.decisions:
            decisions.append(sim.decisions[order.id])
        if order.pickup_day is not None:
            last_day_of_use = order.pickup_day + timedelta(days=order.days_of_use - 1)
            dont_last += expiry < last_day_of_use
    units_wanted = sum(line.qty for line in need.lines)
    units_secured = sum(min(secured[medicine], line.qty) for medicine, line in wanted.items())
    complete = units_secured >= units_wanted and last is not None
    return NeedResult(
        n=need.n,
        client_n=need.client.n,
        medicines=len(need.lines),
        units_wanted=units_wanted,
        units_secured=units_secured,
        minutes_to_secure=int((last - need.at).total_seconds() // 60)
        if complete and last
        else None,
        taps=sim.taps[need.n],
        messages=sim.messages[need.n],
        reservations=len(decisions),
        cant_work=sum(not decision.works for decision in decisions),
        extra_minutes=sum(
            max(decision.minutes - decision.best_minutes, 0)
            for decision in decisions
            if decision.works and decision.best_minutes is not None
        ),
        travel_minutes=sum(decision.minutes for decision in decisions),
        other_brand_units=sum(decision.units for decision in decisions if decision.other_brand),
        no_shows=no_shows,
        boxes_that_dont_last=dont_last,
        unusable_cards=sim.unusable_cards[need.n],
        unusable_after_told=sim.unusable_after_told[need.n],
    )


def results(sim: Sim) -> list[NeedResult]:
    by_client = _orders_by_client(sim)
    return [
        need_result(sim, need, by_client.get(need.client.id, [])) for need in sim.scenario.needs
    ]


def summary(needs: list[NeedResult]) -> dict[str, float | int]:
    """The day in a few numbers. Confidence intervals come from `evals.stats`, over seeds."""
    wanted = sum(need.units_wanted for need in needs)
    secured = sum(need.units_secured for need in needs)
    done = sorted(need.minutes_to_secure for need in needs if need.minutes_to_secure is not None)
    reservations = sum(need.reservations for need in needs)
    return {
        "needs": len(needs),
        "units_wanted": wanted,
        "units_secured": secured,
        "fulfillment": round(secured / wanted, 4) if wanted else 0.0,
        "needs_fulfilled": round(sum(need.fulfilled for need in needs) / len(needs), 4)
        if needs
        else 0.0,
        "median_minutes_to_secure": done[len(done) // 2] if done else -1,
        "taps_per_need": round(sum(need.taps for need in needs) / len(needs), 2) if needs else 0.0,
        "messages_per_need": round(sum(need.messages for need in needs) / len(needs), 2)
        if needs
        else 0.0,
        "reservations": reservations,
        "cant_work": sum(need.cant_work for need in needs),
        "extra_minutes_per_reservation": (
            round(sum(need.extra_minutes for need in needs) / reservations, 2)
            if reservations
            else 0.0
        ),
        "travel_minutes_per_unit": (
            round(sum(need.travel_minutes for need in needs) / secured, 2) if secured else 0.0
        ),
        "other_brand_units": sum(need.other_brand_units for need in needs),
        "no_shows": sum(need.no_shows for need in needs),
        "boxes_that_dont_last": sum(need.boxes_that_dont_last for need in needs),
        "unusable_cards": sum(need.unusable_cards for need in needs),
        "unusable_after_told": sum(need.unusable_after_told for need in needs),
    }


def room_for_early_release(sim: Sim) -> dict[str, int]:
    """How many of the units nobody secured could early release have served, at best?

    For each missing unit: is there, at the end of the day, a private box of that medicine
    in the early-release zone (R-E2), at a pharmacy within the automatic reach of the
    client, at a suggested price inside their budget? It is an upper bound: it ignores
    whether the pharmacy would answer, and whether the client could go there. It says how
    much room the simulated world leaves for the agent's asks, whoever the contender is.
    """
    by_client = _orders_by_client(sim)
    missing_units = could_ask = 0
    with sim.tx() as tx:
        first = tx.today + timedelta(days=NEAR_EXPIRY_MAX_DAYS)
        last = tx.today + timedelta(days=EARLY_RELEASE_MAX_DAYS)
        private = tx.session.execute(
            select(
                InventoryItem.product_id,
                InventoryItem.pharmacy_id,
                InventoryItem.qty_on_hand - InventoryItem.qty_reserved,
            )
            .join(Pharmacy, Pharmacy.id == InventoryItem.pharmacy_id)
            .where(
                Pharmacy.status == "APPROVED",
                InventoryItem.qty_on_hand - InventoryItem.qty_reserved >= 1,
                InventoryItem.expiry_date > first,
                InventoryItem.expiry_date <= last,
            )
        ).all()
        boxes: dict[uuid.UUID, list[tuple[uuid.UUID, int]]] = defaultdict(list)
        for product_id, pharmacy_id, units in private:
            boxes[product_id].append((pharmacy_id, units))
        for need in sim.scenario.needs:
            secured: dict[str, int] = defaultdict(int)
            for order, _ in by_client.get(need.client.id, []):
                at = order.reserved_at
                if at is not None and at <= sim.window_ends(need):
                    secured[sim.medicine_of.get(order.product_id, "")] += _units(order)
            for line in need.lines:
                missing = line.qty - min(secured[sim.medicine_of[line.product_id]], line.qty)
                if missing <= 0:
                    continue
                missing_units += missing
                budget = sim.budget_lbp(line)
                price = early_release_suggested_price_lbp(sim.prices[line.product_id])
                held = boxes.get(line.product_id, [])
                if not held or (budget is not None and price > budget):
                    continue
                ways = travel.travel_to(
                    tx, sim.location_of(need.client), [pharmacy for pharmacy, _ in held]
                )
                near = sum(units for pharmacy, units in held if travel.within_reach(ways[pharmacy]))
                could_ask += min(missing, near)
    return {"units_missing": missing_units, "early_release_could_serve": could_ask}


def turns(sim: Sim) -> dict[str, float | int]:
    """The agent runtime's own record of the day (`agent_runs`): empty for the search baseline.

    A run with a turn that fell back to a fixed text, or with a request that used all of its
    turns, did not measure the contender: it is reported, never averaged in silently.
    """
    with sim.tx() as tx:
        runs = tx.session.execute(
            select(
                AgentRun.outcome,
                AgentRun.guardrails,
                AgentRun.tool_calls,
                AgentRun.tool_errors,
                AgentRun.llm_calls,
                AgentRun.cost_usd,
            )
        ).all()
        per_request = tx.session.execute(
            select(func.count())
            .where(AgentRun.request_id.is_not(None))
            .group_by(AgentRun.request_id)
        ).scalars()
        at_the_cap = sum(count >= MAX_TURNS_PER_REQUEST for count in per_request)
    if not runs:
        return {}
    return {
        "turns": len(runs),
        "turns_not_ok": sum(run.outcome != "ok" for run in runs),
        "turns_with_a_guard": sum(bool(run.guardrails) for run in runs),
        # Which guards, and in how many turns each (a turn can meet several).
        "guards": dict(Counter(name for run in runs for name in run.guardrails or [])),
        "tool_calls": sum(run.tool_calls for run in runs),
        "tool_errors": sum(run.tool_errors for run in runs),
        "model_calls": sum(run.llm_calls for run in runs),
        "cost_usd": float(sum(run.cost_usd for run in runs)),
        "requests_at_the_turn_cap": at_the_cap,
        "trips_not_from_the_road_table": sim.straight_trips,
    }


def as_rows(needs: list[NeedResult]) -> list[dict[str, Any]]:
    return [asdict(need) | {"fulfilled": need.fulfilled} for need in needs]
