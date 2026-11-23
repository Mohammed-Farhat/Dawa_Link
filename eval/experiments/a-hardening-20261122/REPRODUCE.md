# Reproduction and restart

Run from the repository root on test/agent-evaluation. Preserve the dirty checkout;
never reset/clean it. candidate6-source-pin.json is a reproduction snapshot, not final
held-out freeze or permission to spend. It records all runtime/configuration hashes,
prompt1.16 and model claude-haiku-5-5/medium. Historical source is retained in each
run's source.tar.gz and in the separate architecture preservation commit bdc5c16.

## Offline verification

From backend, use the existing ignored integration local.env, never print its values:

```bash
set -a
source ../eval/checkpoints/2026-11-19-git-integration/local.env
set +a
.venv/bin/pytest -ra
.venv/bin/ruff check src tests migrations
.venv/bin/ruff format --check src tests migrations
.venv/bin/mypy
```

The current integrated logs are evidence/candidate6-full-{backend-tests,lint,types}.txt.
Do not rerun an unchanged full suite routinely. Individual repair regression commands
and source hashes are recorded in candidate6-*-checks.json alongside targeted logs.

From repository root:

```bash
python3 eval/experiments/a-hardening-20261122/audit.py
python3 eval/experiments/a-hardening-20261122/summarize_validation.py --help
```

The audit reads the canonical ledger and historical seal; it never releases holds.
The validation summary reconstructs candidate5 original outcomes, not rescored
candidate6 acceptance. Accepted cases/labels remain unchanged in development-v2.

## Free product baselines

Sequentially, with no database test running, from backend (catalog paths are relative):

```bash
.venv/bin/python ../eval/experiments/a-hardening-20261122/free_sim.py --architecture current --stage expanded --contender search --seeds 1 --requests 100 --save
.venv/bin/python ../eval/experiments/a-hardening-20261122/free_sim.py --architecture current --stage expanded --contender rules --seeds 1 --requests 100 --save
.venv/bin/python ../eval/experiments/a-hardening-20261122/free_sim.py --architecture current --stage expanded --contender rules_asking --seeds 1 --requests 100 --save
```

The wrapper permits only free contenders and removes provider/routing/tracing keys.
Every invocation creates a distinct run archive. Inspect existing run IDs before
repeating anything. Compare exact archived runs using:

```bash
python3 eval/experiments/a-hardening-20261122/compare_simulations.py OUTPUT_JSON RUN_ID RUN_ID RUN_ID
```

OUTPUT_JSON must not already exist. Without a paid A run, this yields descriptive
baseline results and no A-minus-baseline estimates. Protocol SIMULATION_METHODS.md
separates strict complete pairs from full-world outcomes retaining execution failures.

## Paid and external prerequisites

STOP_PAID remains armed. The candidate5 queue is terminal and must not be restarted.
Do not call paid_v5/validate_candidate5 with current source. Candidate6 has not been
live-validated. Billing evidence or explicit revised authorization must resolve the
new uncertainty before a prospective candidate6 paid protocol can be activated;
never silently allow the new hold, replay original failures, or reallocate stages.

After resolution, first preflight bounded fresh-world development batches for all352
accepted cases/369 contexts or conversations, with separate model-played coverage,
then prioritize the first100-request A simulation before optional seeds/stresses.
Keep each candidate's original outcomes separate. A single seed has no cross-world
confidence interval. Include simulated clients and browser calls in the same ledger.

review-pack-20261123 is the pending owner/teammate pack; assistant judgments are not
independent acceptance. Suitable held-out cases/provenance and resolved development
regressions/review findings are prerequisites for final freeze before opening content.
DEMO.md describes prepared synthetic live journeys, not completed live verification.
No push, deployment or main merge is part of this handoff.
