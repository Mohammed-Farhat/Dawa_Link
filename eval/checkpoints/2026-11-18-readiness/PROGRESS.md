# Resume checkpoint — pre-architecture

Reference: `1e17db0ea522622caaf8da41d60df4ef152ccec3`.
Branch: `test/agent-evaluation`. No architecture or prompt changes, commits,
pushes, merges, deployment, or held-out access. Original handoff preserved.

Authorized scope: shared harness repairs, free verification, baseline <= $4
within $25 aggregate. Stop before architecture experiments.

Completed: isolated PostgreSQL/Mailpit and synthetic accounts; scorer repairs;
exclusive traces and unique run/database names; template input fingerprint;
run manifests/source archives/completion records; atomic shared budget ledger;
seed-clustered bootstrap; frozen original + 60 challenge cases; free checks;
scripted native Safari chat -> clarification -> approval -> reservation -> pickup.
Original free checkpoint remains at `../2026-11-18-baseline/`.

Paid baseline STOPPED conservatively. Five-case pilot complete; four larger runs
incomplete. Ledger: 75 settled calls, known $0.045449; six uncertain calls retain
$3.87; total committed $3.915449. Next $0.645 reservation cannot fit $4.
DO NOT reset/delete/release ledger holds or move baseline calls to another stage.
No model-played conversations or paid simulation executed. Provider status/reason
was not retained by the wrapper, so exact failure cause/billing is unresolved.
All raw outcomes and source snapshots retained in
`eval/experiments/architecture-20261118/runs/`; canonical ledger is `budget.sqlite`.

Remaining before architecture: reconcile uncertain provider billing with evidence;
improve safe failure/request metadata and refusal usage accounting; complete fresh
baseline and 50-conversation review within authorized spending; execute remaining
browser cancellation/unavailable/sourcing-timeout journeys; address residual scorer
and fairness audit gaps in REPORT.md. Logout UI bug recorded, not fixed.
Browser connector is unavailable; native Safari was in active user use at resume.

Keys: only Anthropic key is in ignored root `.env` (0600), with LLM_PROVIDER=none.
Never print credentials or source root `.env` into free checks. `paid.py` reads
only the Anthropic key into memory. Routing/Langfuse disabled. Keep all evidence.

Verification complete: final backend 1968 passed; frontend 151 passed; lint,
types/build and full free evaluation gate passed. REPORT.md and CHECKS.md saved.
All 35 partial answer rows reviewed; 50-conversation review remains incomplete.
Residual quantity negative control still fails (wrong final quantity accepted).
Native browser edge journeys remain pending. Architecture gate is NOT satisfied.
Use `check.py` with a NEW
evidence name every time; it refuses existing files and sets synthetic local.env.
Temporary API/web and isolated Compose are stopped; no volumes deleted. Ledger
snapshot and run integrity hashes are in evidence/integrity.json. Read REPORT.md
and CHECKS.md for exact findings and commands.
