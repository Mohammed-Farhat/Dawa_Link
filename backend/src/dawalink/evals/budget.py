"""Durable experiment-wide accounting. All amounts are integer micro-dollars.

Reservations survive crashes and ambiguous provider failures; never silently release
unknown charges. This intentionally stops early rather than risking the $25 ceiling.
"""

import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dawalink.agent.llm.base import LLMRejected, ModelReply, Prompt
from dawalink.agent.llm.claude import ClaudeModel

CAPS = {
    "baseline": 4_000_000,
    "screening": 6_000_000,
    "expanded": 10_000_000,
    "heldout": 3_000_000,
    "retries": 2_000_000,
}
TOTAL = 25_000_000
# Full 1M input at 5m-cache-write long-context rate, plus 8000 output tokens.
# https://platform.claude.com/docs/en/models/haiku-5-5/overview (2026-11-18)
HAIKU_RESERVATION = 645_000


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, run TEXT NOT NULL, stage TEXT NOT NULL,
                held INTEGER NOT NULL, actual INTEGER, status TEXT NOT NULL,
                created TEXT DEFAULT CURRENT_TIMESTAMP)""")
            db.execute("""CREATE TABLE IF NOT EXISTS call_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL,
                kind TEXT NOT NULL, details TEXT NOT NULL,
                created TEXT DEFAULT CURRENT_TIMESTAMP)""")

    def record(self, call: str, kind: str, details: dict[str, Any]) -> None:
        import json

        with self.connect() as db:
            db.execute(
                "INSERT INTO call_events(call_id,kind,details) VALUES(?,?,?)",
                (call, kind, json.dumps(details, sort_keys=True)),
            )

    def reconcile(self, call: str, actual: int, *, evidence_sha256: str) -> None:
        """Apply verified external billing evidence; never erase an uncertain call.

        The caller must verify the receipt belongs to this call before invoking this.
        Unknown or merely estimated charges must retain their reservations.
        """
        import json

        if not re.fullmatch(r"[a-f0-9]{64}", evidence_sha256):
            raise ValueError("a verified billing evidence SHA-256 is required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT held,status FROM calls WHERE id=?", (call,)).fetchone()
            if not row or row[1] != "uncertain" or not 0 <= actual <= row[0]:
                raise ValueError("invalid reconciliation; reservation retained")
            db.execute(
                "INSERT INTO call_events(call_id,kind,details) VALUES(?,?,?)",
                (
                    call,
                    "billing_reconciliation",
                    json.dumps(
                        {
                            "prior_held_microusd": row[0],
                            "actual_microusd": actual,
                            "evidence_sha256": evidence_sha256,
                        },
                        sort_keys=True,
                    ),
                ),
            )
            db.execute(
                "UPDATE calls SET held=?,actual=?,status='reconciled' WHERE id=?",
                (actual, actual, call),
            )

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def reserve(self, run: str, stage: str, amount: int = HAIKU_RESERVATION) -> str:
        if stage not in CAPS or amount <= 0:
            raise ValueError("invalid stage or reservation")
        call = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total, local = db.execute(
                "SELECT COALESCE(SUM(held),0), COALESCE(SUM(CASE WHEN stage=? "
                "THEN held ELSE 0 END),0) FROM calls",
                (stage,),
            ).fetchone()
            if total + amount > TOTAL or local + amount > CAPS[stage]:
                raise LLMRejected("evaluation budget reservation refused")
            db.execute(
                "INSERT INTO calls(id,run,stage,held,status) VALUES(?,?,?,?,?)",
                (call, run, stage, amount, "reserved"),
            )
        return call

    def settle(self, call: str, actual: int) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT held,status FROM calls WHERE id=?", (call,)).fetchone()
            if not row or row[1] != "reserved" or not 0 <= actual <= row[0]:
                raise ValueError("invalid settlement; reservation retained")
            db.execute(
                "UPDATE calls SET held=?,actual=?,status='settled' WHERE id=?",
                (actual, actual, call),
            )

    def uncertain(self, call: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE calls SET status='uncertain' WHERE id=? AND status='reserved'", (call,)
            )

    def totals(self) -> dict[str, int]:
        with self.connect() as db:
            row = db.execute(
                "SELECT COALESCE(SUM(actual),0), COALESCE(SUM(held),0), COUNT(*) FROM calls"
            ).fetchone()
        return {"known_spend_microusd": row[0], "committed_microusd": row[1], "calls": row[2]}


class EvaluationModel(ClaudeModel):
    """Same agent/model request; budget wrapper used only by evaluation runners."""

    def __init__(self, **kwargs: Any) -> None:
        if kwargs.get("model") != "claude-haiku-5-5":
            raise ValueError("Only the frozen Haiku model has verified evaluation pricing")
        path, run = os.environ.get("EVAL_LEDGER"), os.environ.get("EVAL_RUN_ID")
        if not path or not run:
            raise ValueError("Paid evaluations require EVAL_LEDGER and EVAL_RUN_ID")
        self.ledger = Ledger(Path(path))
        self.run_id = run
        self.stage = os.environ.get("EVAL_STAGE", "baseline")
        super().__init__(**kwargs)
        # Observe responses before the unchanged adapter parses or rejects them.
        # SDK retries must remain off: each transmitted attempt needs its own reserve.
        if getattr(self._client, "max_retries", 0) != 0:
            raise ValueError("Evaluation SDK retries must be disabled")
        self._client = SimpleNamespace(  # type: ignore[assignment]
            messages=_RecordedMessages(self._client.messages, self.ledger, self.run_id, self.stage)
        )

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        return super().complete(prompt, timeout_s=timeout_s)


class _RecordedMessages:
    def __init__(self, messages: Any, ledger: Ledger, run: str, stage: str) -> None:
        self.messages, self.ledger, self.run, self.stage = messages, ledger, run, stage

    def create(self, **kwargs: Any) -> Any:
        # Request construction and budget refusal happen before transmission.
        call = self.ledger.reserve(self.run, self.stage)
        started = time.monotonic()
        try:
            response = self.messages.create(**kwargs)
            used = response.usage
            cached = used.cache_read_input_tokens or 0
            written = used.cache_creation_input_tokens or 0
            plain, output = used.input_tokens, used.output_tokens
            if any(type(n) is not int or n < 0 for n in (plain, output, cached, written)):
                raise ValueError("invalid provider usage; reservation retained")
            # Round up; long-context threshold applies to all input including cached tokens.
            factor = 5 if plain + cached + written > 100_000 else 1
            from decimal import ROUND_CEILING, Decimal

            amount = (
                Decimal(plain) * Decimal("0.10")
                + Decimal(output) * Decimal("0.50")
                + Decimal(cached) * Decimal("0.01")
                + Decimal(written) * Decimal("0.125")
            ) * factor
            self.ledger.settle(call, int(amount.to_integral_value(rounding=ROUND_CEILING)))
            self.ledger.record(
                call,
                "provider_response",
                {
                    "request_id": _safe_id(getattr(response, "_request_id", None)),
                    "input_tokens": plain,
                    "output_tokens": output,
                    "cached_tokens": cached,
                    "cache_write_tokens": written,
                    "seconds": round(time.monotonic() - started, 3),
                },
            )
            return response
        except BaseException as exc:
            self.ledger.uncertain(call)
            status = getattr(exc, "status_code", None)
            self.ledger.record(
                call,
                "provider_failure",
                {
                    "error_type": type(exc).__name__,
                    "status": status if type(status) is int else None,
                    "request_id": _safe_id(getattr(exc, "request_id", None)),
                    "seconds": round(time.monotonic() - started, 3),
                },
            )
            raise


def _safe_id(value: object) -> str | None:
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"req_[a-zA-Z0-9_-]{1,120}", value)
        else None
    )
