"""How the agent and the system are doing (docs/03 AS-2, AS-10; docs/04 R-AL).

Everything here is counted from our own tables, over the last days of the app's clock:
`agent_runs` for the agent, the orders and requests for what it achieved, and the rows
the worker should already have handled for the system. No personal data is read.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from dawalink.db.models import (
    AgentRun,
    AppState,
    Conversation,
    EarlyReleaseAsk,
    EmailOutbox,
    Escalation,
    Order,
    SourcingRequest,
)
from dawalink.domain.orders import OrderState
from dawalink.services.clock import OFFSET_KEY
from dawalink.services.context import Tx

# R-AL: when each alert fires.
ERROR_RATE_ALERT = 0.05
ERROR_RATE_OVER = timedelta(minutes=15)
SPEND_ALERT_SHARE = Decimal("0.8")
DEAD_EMAILS_ALERT = 10
CLOCK_LATE_ALERT = timedelta(minutes=2)
TURN_ATTEMPTS_ALERT = 4


@dataclass(frozen=True)
class Health:
    days: int
    agent: dict[str, Any]
    requests: dict[str, Any]
    marketplace: dict[str, Any]
    system: dict[str, Any]
    # The alerts that fire right now, as codes the console words.
    alerts: list[str]


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _agent(tx: Tx, since: datetime) -> dict[str, Any]:
    runs = AgentRun.started_at > since
    row = tx.session.execute(
        select(
            func.count(),
            func.percentile_cont(0.5).within_group(AgentRun.latency_ms),
            func.percentile_cont(0.95).within_group(AgentRun.latency_ms),
            func.count().filter(AgentRun.outcome == "error"),
            func.count().filter(AgentRun.outcome == "fallback"),
            func.count().filter(AgentRun.outcome == "guardrail_blocked"),
            func.count().filter(func.jsonb_array_length(AgentRun.guardrails) > 0),
            func.coalesce(func.sum(AgentRun.tokens_in), 0),
            func.coalesce(func.sum(AgentRun.tokens_out), 0),
            func.coalesce(func.sum(AgentRun.cost_usd), 0),
            func.coalesce(func.sum(AgentRun.tool_calls), 0),
            func.coalesce(func.sum(AgentRun.tool_errors), 0),
        ).where(runs)
    ).one()
    latest = tx.session.execute(
        select(AgentRun.model, AgentRun.prompt_version)
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    ).one_or_none()
    turns = int(row[0])
    return {
        "turns": turns,
        "latency_p50_ms": int(row[1]) if row[1] is not None else None,
        "latency_p95_ms": int(row[2]) if row[2] is not None else None,
        "errors": int(row[3]),
        "error_rate": _share(int(row[3]), turns),
        "fallbacks": int(row[4]),
        "guardrail_blocked": int(row[5]),
        "guardrail_triggers": int(row[6]),
        "tokens_in": int(row[7]),
        "tokens_out": int(row[8]),
        "cost_usd": float(row[9]),
        "tool_calls": int(row[10]),
        "tool_errors": int(row[11]),
        "model": latest.model if latest else None,
        "prompt_version": latest.prompt_version if latest else None,
    }


def _requests(tx: Tx, since: datetime, cost_usd: float) -> dict[str, Any]:
    closed = tx.session.execute(
        select(SourcingRequest.outcome, func.count())
        .where(SourcingRequest.closed_at > since)
        .group_by(SourcingRequest.outcome)
    ).all()
    by_outcome = {str(outcome): int(count) for outcome, count in closed}
    total = sum(by_outcome.values())
    fulfilled = by_outcome.get("FULFILLED", 0)
    replans, replanned = tx.session.execute(
        select(func.count(), func.count(func.distinct(AgentRun.request_id))).where(
            AgentRun.started_at > since,
            AgentRun.request_id.is_not(None),
            AgentRun.trigger == "decision_event",
        )
    ).one()
    asked, accepted = tx.session.execute(
        select(func.count(), func.count().filter(EarlyReleaseAsk.state == "ACCEPTED")).where(
            EarlyReleaseAsk.created_at > since
        )
    ).one()
    escalations = tx.session.execute(
        select(Escalation.reason, func.count())
        .where(Escalation.created_at > since)
        .group_by(Escalation.reason)
    ).all()
    return {
        "closed": total,
        "by_outcome": by_outcome,
        # A request closes inside its 6 hours by construction: FULFILLED is "within the window".
        "fulfilled_share": _share(fulfilled, total),
        "replans": int(replans),
        "replans_per_request": round(int(replans) / int(replanned), 2) if replanned else None,
        "early_release_asked": int(asked),
        "early_release_accepted": int(accepted),
        "escalations_by_reason": {str(reason): int(count) for reason, count in escalations},
        "cost_per_fulfilled_usd": round(cost_usd / fulfilled, 4) if fulfilled else None,
    }


def _marketplace(tx: Tx, since: datetime) -> dict[str, Any]:
    row = tx.session.execute(
        select(
            func.count(),
            func.count().filter(Order.state == OrderState.PICKED_UP.value),
            func.count().filter(Order.state == OrderState.NOT_AVAILABLE.value),
            func.count().filter(Order.state == OrderState.EXPIRED_NO_SHOW.value),
            func.coalesce(func.sum(Order.qty_picked_up), 0),
        ).where(Order.reserved_at > since)
    ).one()
    reserved, ended = int(row[0]), int(row[1]) + int(row[2]) + int(row[3])
    return {
        "reservations": reserved,
        "picked_up": int(row[1]),
        "not_available": int(row[2]),
        "no_shows": int(row[3]),
        # Shares of the reservations that have ended one of these three ways.
        "picked_up_share": _share(int(row[1]), ended),
        "not_available_share": _share(int(row[2]), ended),
        "no_show_share": _share(int(row[3]), ended),
        "units_saved": int(row[4] or 0),
    }


def _system(tx: Tx) -> dict[str, Any]:
    now = tx.now
    # What the clock check should already have acted on: the oldest such row says how
    # late the worker is (R-T10). Nothing overdue: it is on time.
    overdue = [
        tx.session.execute(
            select(func.min(Order.deadline)).where(
                Order.state == OrderState.RESERVED.value, Order.deadline < now
            )
        ).scalar(),
        tx.session.execute(
            select(func.min(Order.offer_expires_at)).where(
                Order.state == OrderState.OFFERED.value, Order.offer_expires_at < now
            )
        ).scalar(),
        tx.session.execute(
            select(func.min(SourcingRequest.ends_at)).where(
                SourcingRequest.state == "OPEN", SourcingRequest.ends_at < now
            )
        ).scalar(),
    ]
    oldest = min((moment for moment in overdue if moment is not None), default=None)
    pending, oldest_turn, stuck = tx.session.execute(
        select(
            func.count(),
            func.min(Conversation.pending_turn_at),
            func.count().filter(Conversation.turn_attempts >= TURN_ATTEMPTS_ALERT),
        ).where(Conversation.pending_turn_at.is_not(None))
    ).one()
    failed, dead_last_hour = tx.session.execute(
        select(
            func.count().filter(EmailOutbox.state.in_(["FAILED", "DEAD"])),
            func.count().filter(
                EmailOutbox.state == "DEAD",
                EmailOutbox.created_at > tx.real_now - timedelta(hours=1),
            ),
        ).where(or_(EmailOutbox.state == "FAILED", EmailOutbox.state == "DEAD"))
    ).one()
    late = (now - oldest) if oldest else timedelta(0)
    # Right after the demo clock is moved forward, every deadline it jumped over is
    # "overdue" until the worker's next round, a few seconds later. The worker can't be
    # later than the time since the move: without this, a 6-hour jump would show
    # "6 hours late" and fire the alert in the middle of a demo.
    moved = tx.session.execute(
        select(AppState.updated_at).where(AppState.key == OFFSET_KEY)
    ).scalar()
    if moved is not None:
        late = min(late, max(tx.real_now - moved, timedelta(0)))
    return {
        "clock_check_late_s": int(late.total_seconds()),
        "turns_waiting": int(pending),
        "oldest_turn_waiting_s": int((now - oldest_turn).total_seconds()) if oldest_turn else 0,
        "turns_stuck": int(stuck),
        "emails_failed": int(failed),
        "emails_dead_last_hour": int(dead_last_hour),
    }


def _alerts(
    tx: Tx, system: dict[str, Any], monthly_budget_usd: Decimal
) -> tuple[list[str], dict[str, Any]]:
    """R-AL, evaluated now. Returns the alerts and the two numbers they are judged on."""
    recent = tx.session.execute(
        select(func.count(), func.count().filter(AgentRun.outcome == "error")).where(
            AgentRun.started_at > tx.now - ERROR_RATE_OVER
        )
    ).one()
    month_start = tx.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = tx.session.execute(
        select(func.coalesce(func.sum(AgentRun.cost_usd), 0)).where(
            AgentRun.started_at >= month_start
        )
    ).scalar_one()
    alerts = []
    if recent[0] and recent[1] / recent[0] > ERROR_RATE_ALERT:
        alerts.append("agent_error_rate")
    if monthly_budget_usd > 0 and Decimal(spent) > SPEND_ALERT_SHARE * monthly_budget_usd:
        alerts.append("llm_spend")
    if system["emails_dead_last_hour"] > DEAD_EMAILS_ALERT:
        alerts.append("dead_emails")
    if system["clock_check_late_s"] > CLOCK_LATE_ALERT.total_seconds():
        alerts.append("clock_check_late")
    if system["turns_stuck"]:
        alerts.append("agent_turn_stuck")
    return alerts, {
        "month_spend_usd": float(spent),
        "month_budget_usd": float(monthly_budget_usd),
    }


def read(tx: Tx, *, days: int = 7, monthly_budget_usd: Decimal = Decimal(0)) -> Health:
    since = tx.now - timedelta(days=days)
    agent = _agent(tx, since)
    system = _system(tx)
    alerts, spend = _alerts(tx, system, monthly_budget_usd)
    return Health(
        days=days,
        agent={**agent, **spend},
        requests=_requests(tx, since, agent["cost_usd"]),
        marketplace=_marketplace(tx, since),
        system=system,
        alerts=alerts,
    )
