# Evaluation checkpoints

Each dated folder preserves the commands, outputs and findings from that checkout.
Reports describe historical code, not necessarily the latest main branch. Never
overwrite evidence or treat a partial run as a completed evaluation.

Before using a checkpoint's local runner, copy its synthetic settings:

```sh
cp eval/checkpoints/2026-11-18-reconciliation/local.env.example eval/checkpoints/2026-11-18-reconciliation/local.env
```

Use the corresponding directory for other checkpoints. `local.env` is ignored;
the example contains disposable local logins and no paid API keys. The evaluation
Compose file uses separate loopback ports and a dedicated data volume. Check the
report before starting databases. Root .env must never be sourced by free checks.

The canonical spending ledger is
`eval/experiments/architecture-20261118/budget.sqlite`; its uncertain reservations
remain part of committed spending. Do not reset or replace it. SQLite copies in
checkpoint evidence are immutable snapshots, not new spending ledgers.

The untracked project handoff document is intentionally outside these commits.
