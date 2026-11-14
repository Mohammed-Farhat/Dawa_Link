"""The agent's budgets and its circuit breaker (docs/04 R-AS, N-38, N-46; docs/07 §8).

Everything here is counted from the `agent_runs` table, never from a process's memory:
the API and the worker are separate processes, and they must agree on whether the
assistant is available.
"""

import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from dawalink.db.models import AgentRun, Conversation
from dawalink.domain.clock import at_beirut
from dawalink.domain.numbers import (
    BREAKER_FAILURES,
    BREAKER_OPEN_FOR,
    BREAKER_WINDOW,
    DAILY_SPEND_CAP_SHARE,
    DAILY_TOKEN_BUDGET_PER_CLIENT,
    MAX_TURNS_PER_REQUEST,
)
from dawalink.domain.vocabulary import RunOutcome
from dawalink.services.context import Tx


def _today_starts(tx: Tx) -> datetime:
    return at_beirut(tx.today, time(0, 0))


def _month_starts(tx: Tx) -> datetime:
    return at_beirut(tx.today.replace(day=1), time(0, 0))


def tokens_today(tx: Tx, client_id: uuid.UUID) -> int:
    """The tokens this client's turns used since midnight in Beirut."""
    return tx.session.execute(
        select(func.coalesce(func.sum(AgentRun.tokens_in + AgentRun.tokens_out), 0))
        .join(Conversation, Conversation.id == AgentRun.conversation_id)
        .where(Conversation.client_id == client_id, AgentRun.started_at >= _today_starts(tx))
    ).scalar_one()


def over_daily_budget(tx: Tx, client_id: uuid.UUID) -> bool:
    """R-AS: over it, the assistant is paused for this client until midnight."""
    return tokens_today(tx, client_id) >= DAILY_TOKEN_BUDGET_PER_CLIENT


def midnight(tx: Tx) -> datetime:
    """When a client's daily budget starts again."""
    return at_beirut(tx.today + timedelta(days=1), time(0, 0))


def _spent(tx: Tx, since: datetime) -> Decimal:
    return tx.session.execute(
        select(func.coalesce(func.sum(AgentRun.cost_usd), 0)).where(AgentRun.started_at >= since)
    ).scalar_one()


def spend_cap_reached(tx: Tx, monthly_budget_usd: Decimal) -> str | None:
    """ "month" or "day" when everyone's LLM spending has reached a global cap (N-46)."""
    if _spent(tx, _month_starts(tx)) >= monthly_budget_usd:
        return "month"
    if _spent(tx, _today_starts(tx)) >= monthly_budget_usd * DAILY_SPEND_CAP_SHARE / 100:
        return "day"
    return None


def month_spent_share(tx: Tx, monthly_budget_usd: Decimal) -> Decimal:
    """How much of the month's budget is used, from 0 to 1 and beyond: for the 80% alert."""
    if monthly_budget_usd <= 0:
        return Decimal(1)
    return _spent(tx, _month_starts(tx)) / monthly_budget_usd


def breaker_open(tx: Tx) -> bool:
    """N-38: three turns lost to the model within five minutes close it for two minutes.

    While it is open no model call is made, so nothing new fails; when the two minutes
    are over the next turn is tried, and one more failure opens it again at once.
    """
    ended = (
        tx.session.execute(
            select(AgentRun.ended_at)
            .where(AgentRun.outcome == RunOutcome.FALLBACK.value, AgentRun.ended_at.is_not(None))
            .order_by(AgentRun.ended_at.desc())
            .limit(BREAKER_FAILURES)
        )
        .scalars()
        .all()
    )
    failed = [moment for moment in ended if moment is not None]
    if len(failed) < BREAKER_FAILURES:
        return False
    newest, oldest = failed[0], failed[-1]
    return newest - oldest <= BREAKER_WINDOW and tx.now < newest + BREAKER_OPEN_FOR


def too_many_turns(tx: Tx, request_id: uuid.UUID) -> bool:
    """R-RQ10: above this many turns on one request, a person takes over."""
    turns = tx.session.execute(
        select(func.count()).select_from(AgentRun).where(AgentRun.request_id == request_id)
    ).scalar_one()
    return turns >= MAX_TURNS_PER_REQUEST
