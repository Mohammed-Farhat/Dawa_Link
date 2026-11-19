"""Audited entry point: python -m dawalink.evals.experiment SUITE [runner arguments].

New run directory every time. Paid runners share one durable ledger. Only development
cases are allowed in this stage. A completion manifest is required for comparison.
"""

import hashlib
import importlib
import json
import os
import subprocess
import sys
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dawalink.evals.budget import Ledger

ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT = ROOT / "eval" / "experiments" / "architecture-20261118"
MODULES = {
    "understanding": "dawalink.evals.run_understanding",
    "safety": "dawalink.evals.run_safety",
    "conversations": "dawalink.evals.run_conversations",
    "multiturn": "dawalink.evals.run_multiturn",
    "simulation": "dawalink.sim.run",
}


def fingerprint() -> dict[str, str]:
    paths = [
        p
        for base in ("backend/src", "backend/migrations", "eval/datasets", "eval/world")
        for p in (ROOT / base).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    ]
    paths += [
        ROOT / p
        for p in (
            "backend/uv.lock",
            "frontend/package-lock.json",
            "backend/data/moph/catalog.csv",
            "backend/data/catalog_overrides.toml",
        )
    ]
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
        if p.exists()
    }


def write_once(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, default=str)
        stream.write("\n")


def coverage_complete(folder: Path, suite: str, expected: int) -> bool:
    """Require raw coverage and successful execution, not a plausible summary alone."""
    filename = {
        "simulation": "needs.jsonl",
        "conversations": "conversations.jsonl",
        "multiturn": "conversations.jsonl",
        "safety": "answers.jsonl",
        "understanding": "answers.jsonl",
    }[suite]
    summaries = [json.loads(p.read_text()) for p in folder.glob("*/summary.json")]
    paths = list(folder.glob(f"*/{filename}"))
    rows = [json.loads(line) for p in paths for line in p.read_text().splitlines()]
    if expected <= 0 or len(rows) != expected or len(paths) != len(summaries):
        return False
    for row in rows:
        if row.get("outcome", "ok") != "ok":
            return False
        if any(t.get("outcome", "ok") != "ok" for t in row.get("turns", [])):
            return False
        if row.get("ended", "cards") not in ("cards", "client_left", "too_long"):
            return False
        if any(e.get("outcome", "ok") != "ok" for e in row.get("exchanges", [])):
            return False
        if suite == "multiturn" and (
            not row.get("expected_turns") or len(row.get("exchanges", [])) != row["expected_turns"]
        ):
            return False
    observed = sum(
        int(d.get("cases", d.get("answers", d.get("conversations", d.get("needs", 0)))))
        for d in summaries
    )
    return observed == expected and not any(
        d.get("not_ok", 0)
        or (suite == "simulation" and d.get("turns", {}).get("turns_not_ok", 0))
        or (suite == "simulation" and d.get("turns", {}).get("requests_at_the_turn_cap", 0))
        for d in summaries
    )


def main() -> None:
    from dawalink.evals import datasets
    from dawalink.sim import save

    if len(sys.argv) < 2 or sys.argv[1] not in MODULES:
        raise SystemExit("suite: understanding, safety, conversations, simulation")
    suite, args = sys.argv[1], sys.argv[2:]
    if any(x.split("=")[0] in ("--heldout", "--rescore") for x in args):
        raise SystemExit("Held-out/rescoring is outside this development protocol")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:12]
    folder = EXPERIMENT / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    os.environ["EVAL_LEDGER"] = str(EXPERIMENT / "budget.sqlite")
    os.environ["EVAL_RUN_ID"] = run_id
    os.environ["EVAL_STAGE"] = "baseline"
    save.RESULTS = folder
    # Freeze development cases independently; do not modify the historical datasets.
    dataset = os.environ.get("EVAL_DATASET", "development")
    if dataset not in ("development", "challenge", "reviewed"):
        raise ValueError("invalid development dataset")
    frozen = EXPERIMENT / ("reviewed-development" if dataset == "reviewed" else dataset)
    if frozen.exists():
        datasets.DATASETS = frozen
    freeze = json.loads((EXPERIMENT / "dataset-freeze.json").read_text())
    for relative, expected_hash in freeze.items():
        if hashlib.sha256((EXPERIMENT / relative).read_bytes()).hexdigest() != expected_hash:
            raise ValueError("Frozen development cases changed")
    if dataset == "reviewed" or suite == "multiturn":
        revised_freeze = json.loads((EXPERIMENT / "reconciliation-freeze.json").read_text())
        for relative, expected_hash in revised_freeze.items():
            if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected_hash:
                raise ValueError("Reviewed development cases changed")

    def option(name: str, default: str = "") -> str:
        for i, arg in enumerate(args):
            if arg == name:
                return args[i + 1]
            if arg.startswith(name + "="):
                return arg.split("=", 1)[1]
        return default

    if suite != "simulation":
        from dawalink.evals.datasets import RCase, UCase, read

        if suite == "multiturn":
            from dawalink.evals.run_multiturn import CASES, MCase

            multi = read(CASES, MCase)
            expected = len(multi[: int(option("--limit", str(len(multi))))])
        elif suite == "safety":
            cases = read(datasets.DATASETS / "safety.jsonl", RCase)
            selected = cases[: int(option("--limit", str(len(cases))))]
            expected = sum(len(c.where) for c in selected)
        else:
            from dawalink.evals.played_client import personas

            understanding = read(datasets.DATASETS / "understanding.jsonl", UCase)
            if suite == "understanding":
                expected = len(understanding[: int(option("--limit", str(len(understanding))))])
            else:
                people = personas(understanding)
                only = set(option("--cases").split(",")) - {""}
                lang = option("--lang")
                people = [
                    p
                    for p in people
                    if (not only or p.case.id in only) and (not lang or p.case.lang == lang)
                ]
                expected = len(people[: int(option("--limit", str(len(people))))])
    else:
        from dawalink.sim.run import _seeds

        expected = int(option("--requests", "100")) * len(_seeds(option("--seeds", "1")))
    ledger = Ledger(EXPERIMENT / "budget.sqlite")
    config: dict[str, Any] = {
        "run_id": run_id,
        "suite": suite,
        "argv": args,
        "architecture": "current",
        "expected": expected,
        "dataset": dataset,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "hashes": fingerprint(),
        "ledger_before": ledger.totals(),
        "dataset_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in datasets.DATASETS.glob("*.jsonl")
        },
        "multiturn_sha256": hashlib.sha256(
            (ROOT / "eval/datasets/multiturn.jsonl").read_bytes()
        ).hexdigest()
        if suite == "multiturn"
        else None,
    }
    write_once(folder / "manifest.json", config)
    (folder / "code.diff").write_bytes(subprocess.check_output(["git", "diff", "--", "backend"]))
    with tarfile.open(folder / "source.tar.gz", "w:gz") as archive:
        for relative in config["hashes"]:
            if relative.startswith(("backend/src/", "backend/migrations/")):
                archive.add(ROOT / relative, arcname=relative)
    status, error = "incomplete", None
    try:
        sys.argv = [MODULES[suite], *args]
        importlib.import_module(MODULES[suite]).main()
        with ledger.connect() as db:
            unsettled = db.execute(
                "SELECT count(*) FROM calls WHERE run=? AND status NOT IN ('settled','reconciled')",
                (run_id,),
            ).fetchone()[0]
        if coverage_complete(folder, suite, expected) and not unsettled:
            status = "complete"
    except BaseException as exc:
        error = type(exc).__name__  # never persist provider messages or credentials
        raise
    finally:
        write_once(
            folder / "completion.json",
            {
                "status": status,
                "error_type": error,
                "ledger_after": ledger.totals(),
                "ended": datetime.now(UTC).isoformat(),
            },
        )
        print("Evidence:", folder, "status:", status, flush=True)


if __name__ == "__main__":
    main()
