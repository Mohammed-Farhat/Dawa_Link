"""One budget for a whole run: the agent, the played client and the judge together.

The app's own daily cap (docs/04 N-46) is counted per database, and every scenario has a
database of its own, so it can't stop a run. Here every model call of the run is metered
in one place, and a call is refused once the run's limit is reached.
"""

import threading
from collections import defaultdict
from decimal import Decimal

from dawalink.agent.llm.base import ChatModel, LLMRejected, ModelReply, Prompt, cost_usd


class BudgetSpent(LLMRejected):
    """The run's limit is reached: no further model call is made."""


class Spend:
    """What a run has cost so far, by part ("agent", "client", "judge"). Thread-safe."""

    def __init__(self, max_usd: Decimal) -> None:
        self.max_usd = max_usd
        self._by_part: dict[str, Decimal] = defaultdict(Decimal)
        self._lock = threading.Lock()

    def add(self, part: str, usd: Decimal) -> None:
        with self._lock:
            self._by_part[part] += usd

    @property
    def total(self) -> Decimal:
        with self._lock:
            return sum(self._by_part.values(), Decimal(0))

    def by_part(self) -> dict[str, float]:
        with self._lock:
            return {part: float(usd) for part, usd in sorted(self._by_part.items())}

    @property
    def spent(self) -> bool:
        return self.total >= self.max_usd


class Metered:
    """A model whose every call is counted in the run's budget, and refused once it is spent."""

    def __init__(self, inner: ChatModel, spend: Spend, part: str) -> None:
        self.name = inner.name
        self._inner = inner
        self._spend = spend
        self._part = part
        self.usd = Decimal(0)  # what this wrapper's calls cost: one scenario's share
        self.calls = 0

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        if self._spend.spent:
            raise BudgetSpent("The run's budget is spent.")
        reply = self._inner.complete(prompt, timeout_s=timeout_s)
        cost = cost_usd(self._inner.name, reply.usage)
        self._spend.add(self._part, cost)
        self.usd += cost
        self.calls += 1
        return reply
