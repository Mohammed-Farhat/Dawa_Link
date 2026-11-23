# Reconciled development protocol

This supplements, without replacing, the original
[protocol](../../experiments/architecture-20261118/PROTOCOL.md). No architecture
comparison or held-out access is authorized here.

- Reference agent/prompt: `1e17db0ea522622caaf8da41d60df4ef152ccec3`, current loop,
  prompt v1.13. Harness code differs; exact per-run source archives/hashes identify it.
- Model: `claude-haiku-5-5`, medium effort, 8,000 output tokens; no temperature/top-p
  override. Played client uses the same model, low effort. Fixed multi-turn cases
  require no played-client call. No new paid runs were executed in this checkpoint.
- Cases: `EVAL_DATASET=reviewed` selects frozen 210 understanding and 100 safety
  development cases. Safety rows expand each case's configured attack positions.
  Multi-turn suite uses the separate frozen eight cases / 24 turns. Hashes in
  `reconciliation-freeze.json` are verified before selection. Earlier dataset freezes
  remain intact. Fixed conversations and original/challenge overlapping cases must
  not be pooled as independent new evidence.
- Clock/world: 2026-11-16 Asia/Beirut, simulation seed 1 / 100 requests in this
  checkpoint. Per-run initial-input hashes include actual stock and scheduled events.
  Actual applied arrivals and random draws/delays are in events.jsonl. Answer delays
  remain 1–3 minutes; card reactions 5–30. Conditional events depend on actions.
- Accounting: one durable experiment ledger, $4 baseline and $25 aggregate. Preserve
  uncertain/in-flight reservations. All provider requests, retries and played-client
  calls use the evaluation wrapper. Frozen local rates are estimates of token charges;
  unresolved provider failures require attributable external evidence, not guesses.
- Artifacts: new run ID and database every invocation; exclusive output files;
  manifest, source archive/diff, raw rows/traces, hashes and completion status. A run
  requires complete successful execution coverage and no unsettled own calls to
  be complete. Quality failure still counts as an executed answer and is reported.
- Scoring: retain existing acceptance targets from the original protocol; p95 is
  nearest rank. Quantity understanding, valid proposal quantity and complete basket
  are separate. Safety execution failures are separate from violations and passes.
  Automatic language/factuality results require manual review; candidate flags are
  not a complete semantic grader. Do not silently rescore historical runs.
- Review: independent label agreement remains outstanding. Future baseline review
  covers every safety flag and 50 conversations sampled with a recorded seed and
  IDs from the complete fresh conversation population. No such population exists yet.
  Do not use held-out cases for tuning; new challenger comparisons need identical
  cases/settings/worlds and seed-clustered paired intervals in a later stage.

Free simulation command, from repository root (always use a new evidence name):

```sh
python3 eval/checkpoints/2026-11-18-reconciliation/check.py NEW-NAME backend env EVAL_DATASET=reviewed python -m dawalink.evals.experiment simulation --contender search --seeds 1 --requests 100 --save
```

Repeat the contender argument for `rules` and `rules_asking`. No provider keys are
loaded by this wrapper. Paid execution must use the existing shared ledger and
read only the required ignored key into memory after the spending gate permits it;
never source the root .env or reset the ledger. No paid resume command is to be
executed while the six holds prevent the next reservation.
