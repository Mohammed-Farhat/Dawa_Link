"""A contender that serves each need as a sourcing request (docs/08 E2: B1 and A).

The client starts a request, and the request's thread is worked by the agent's own
runtime: the same turns, tools, limits, guards and records as in the app. What decides
inside a turn is the model it is given:
- `RulesModel`: fixed rules, no AI (B1);
- a scripted model in tests, or Claude (A, the agent).

Nothing else differs between B1 and A: the same simulated client taps and writes, and the
engine plays the same pharmacies.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from dawalink.agent.llm import ChatModel
from dawalink.agent.pending import PendingTurns
from dawalink.agent.tracing import NoTracer, Tracer
from dawalink.agent.turn import Agent
from dawalink.sim.client import RequestClient
from dawalink.sim.engine import Sim
from dawalink.sim.scenario import Need

# Turns run until none is waiting. This many passes are far more than a moment needs.
MAX_PASSES = 20


@dataclass
class WithRequests:
    name: str
    model: ChatModel
    # The app's own monthly cap on the model's cost (docs/04 R-AS). Free models never reach it.
    monthly_budget_usd: Decimal = Decimal(100)
    client: RequestClient = field(default_factory=RequestClient)
    # Where every turn's trace goes: a run's `turns.jsonl`, or nowhere.
    tracer: Tracer = field(default_factory=NoTracer)
    _turns: PendingTurns | None = None

    def arrive(self, sim: Sim, need: Need) -> None:
        self.client.arrive(sim, need)

    def take_turns(self, sim: Sim) -> int:
        """Every turn that is due now, as the worker would run them. No routing service:
        road times come from the table the run was given (`eval/world/travel.json`)."""
        if self._turns is None:
            agent = Agent(
                sim.sessions,
                sim.clock,
                self.model,
                tracer=self.tracer,
                monthly_budget_usd=self.monthly_budget_usd,
            )
            self._turns = PendingTurns(agent, batch=50)
        ran = 0
        for _ in range(MAX_PASSES):
            done = self._turns.run_pending_turns()
            if done == 0:
                break
            ran += done
        return ran

    def react(self, sim: Sim) -> None:
        self.client.react(sim)
