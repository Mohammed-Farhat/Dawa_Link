"""What a simulated day leaves behind (docs/08 §5, §6.2; decision log BLD-D19).

One folder per run under `eval/results/`:
- `config.json`: the contender, the model, the prompt version, the seed, every assumption;
- `summary.json`: the day's numbers;
- `needs.jsonl`: one line per client's need, so two contenders can be compared client by
  client;
- `threads.jsonl`: what was written and shown in every request thread;
- `turns.jsonl`: every agent turn as it was traced: its tool calls with their arguments
  and answers, the reply, the tokens. Written turn by turn, so a run that stops halfway
  still leaves what it paid for.

Everything is invented (the clients, the pharmacies) or public (medicine names and public
prices). Nothing here is personal, and no coordinate is written: a trace holds what the
model saw, and the model never sees one (INV-24).
"""

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from datetime import time as clock_time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from dawalink.agent.prompts import PROMPT_VERSION
from dawalink.agent.tracing import TurnTrace
from dawalink.db.models import ChatMessage, Conversation, InventoryItem, Proposal
from dawalink.sim.engine import Sim
from dawalink.sim.params import Params

RESULTS = Path("../eval/results")


def write_artifacts(folder: Path, contents: dict[str, str]) -> None:
    """Refuse existing outputs before writing anything, including legacy entrypoints."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in contents:
        if Path(name).name != name:
            raise ValueError("an artifact must be a filename")
        if (folder / name).exists():
            raise FileExistsError(folder / name)
    for name, content in contents.items():
        with (folder / name).open("x", encoding="utf-8") as stream:
            stream.write(content)


def _plain(value: Any) -> Any:
    """JSON has no dates, decimals or ids."""
    if isinstance(value, datetime | date | clock_time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    raise TypeError(f"can't write {type(value).__name__}")


def _line(row: Any) -> str:
    return json.dumps(row, default=_plain, ensure_ascii=False, separators=(",", ":")) + "\n"


def initial_inputs(sim: Sim) -> dict[str, Any]:
    """Hash the actual world before play, including stock and scheduled external events.

    Coordinates are hashed in memory, never written. Reaction-time assumptions are
    included, so changing client timing cannot masquerade as an architecture effect.
    """

    def digest(value: Any) -> str:
        encoded = json.dumps(value, default=_plain, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    columns = (
        InventoryItem.id,
        InventoryItem.pharmacy_id,
        InventoryItem.product_id,
        InventoryItem.batch,
        InventoryItem.expiry_date,
        InventoryItem.qty_on_hand,
        InventoryItem.qty_reserved,
        InventoryItem.splittable,
        InventoryItem.listing_control,
        InventoryItem.price_override_lbp,
    )
    with sim.tx() as tx:
        stock = [
            list(row) for row in tx.session.execute(select(*columns).order_by(InventoryItem.id))
        ]
    return {
        "seed": sim.seed,
        "starts_at": sim.clock.now().isoformat(),
        "params": asdict(sim.params),
        "world_sha256": digest(asdict(sim.world)),
        "stock_sha256": digest(stock),
        "scenario_sha256": digest(asdict(sim.scenario)),
        "stock_rows": len(stock),
        "needs": len(sim.scenario.needs),
        "arrivals": len(sim.scenario.arrivals),
    }


def folder_for(contender: str, model: str | None, seed: int, params: Params, *, on: date) -> Path:
    """`2026-11-15_agent_claude-haiku-5-5_prompt-v1.5_seed1_n10`: what ran, on what, when."""
    with_a_model = [model, f"prompt-{PROMPT_VERSION}"] if model else []
    parts = [on.isoformat(), contender, *with_a_model, f"seed{seed}", uuid.uuid4().hex[:12]]
    return RESULTS / "_".join([*parts, f"n{params.requests}"])


class FileTracer:
    """Keeps every turn's trace as a line of `turns.jsonl`, as soon as the turn is over."""

    def __init__(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "turns.jsonl"
        self.path.open("x", encoding="utf-8").close()

    def new_trace_id(self) -> str:
        return uuid.uuid4().hex

    def send(self, trace: TurnTrace) -> None:
        turn = {
            "trace_id": trace.trace_id,
            "metadata": trace.metadata,
            "output": trace.output,
            "spans": [
                {
                    "name": span.name,
                    "kind": span.kind,
                    "seconds": round(span.ended - span.started, 3),
                    "input": span.input,
                    "output": span.output,
                    "metadata": span.metadata,
                }
                for span in trace.spans
            ],
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(_line(turn))


def threads(sim: Sim) -> list[dict[str, Any]]:
    """Every message of every request thread, oldest first, as the client's page has it.
    An agent's card is written out: its kind, what it holds and what became of it."""
    with sim.tx() as tx:
        rows = tx.session.execute(
            select(
                Conversation.request_id,
                ChatMessage.seq,
                ChatMessage.author,
                ChatMessage.kind,
                ChatMessage.text_redacted,
                ChatMessage.cards,
            )
            .join(Conversation, Conversation.id == ChatMessage.conversation_id)
            .where(Conversation.request_id.is_not(None))
            .order_by(ChatMessage.conversation_id, ChatMessage.seq)
        ).all()
        shown = {
            str(card_id): {"kind": kind, "tapped": used_at is not None, "holds": payload}
            for card_id, kind, used_at, payload in tx.session.execute(
                select(Proposal.id, Proposal.kind, Proposal.used_at, Proposal.payload)
            )
        }
    return [
        {
            "request": request_id,
            "seq": seq,
            "author": author,
            "kind": kind,
            "text": text,
            "cards": [shown.get(str(card), card) for card in cards or []]
            if author == "agent"
            else cards,
        }
        for request_id, seq, author, kind, text, cards in rows
    ]


def write(
    folder: Path,
    *,
    contender: str,
    model: str | None,
    seed: int,
    params: Params,
    summary: dict[str, Any],
    needs: list[dict[str, Any]],
    said: list[dict[str, Any]],
    more: dict[str, Any],
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    config = {
        "contender": contender,
        "model": model,
        "prompt_version": PROMPT_VERSION if model else None,
        "seed": seed,
        # Since 2026-11-15 a simulated client answers a question about their request
        # (decision log BLD-D27). Runs saved before that have no such line.
        "simulated_client": "answers questions",
        "params": asdict(params),
    }
    write_artifacts(
        folder,
        {
            "config.json": json.dumps(config, default=_plain, indent=2) + "\n",
            "summary.json": json.dumps(summary | more, default=_plain, indent=2) + "\n",
            "needs.jsonl": "".join(_line(need) for need in needs),
            "threads.jsonl": "".join(_line(row) for row in said),
        },
    )
