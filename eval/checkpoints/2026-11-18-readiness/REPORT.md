# DawaLink pre-architecture checkpoint — 18 November 2026

**Keep the current architecture. The free checks pass, but the live baseline is
incomplete and the remaining evaluation gaps prevent a defensible architecture
comparison.** No architecture changes, prompt changes, commits, pushes, merges,
deployments or held-out evaluation were performed.

Reference implementation: `1e17db0ea522622caaf8da41d60df4ef152ccec3`, on
`test/agent-evaluation`. Integrity checks confirm the application agent, frontend
source, historical results and baseline file are unchanged. The existing untracked
handoff document still matches its original SHA-256. Infrastructure repairs remain
uncommitted and separate from the reference agent.

The first free checkpoint remains unchanged at
[2026-11-18-baseline/REPORT.md](../2026-11-18-baseline/REPORT.md).
[CHECKS.md](CHECKS.md) lists exact argument vectors, working directories, exit codes,
durations and full output links for this stage. [PROGRESS.md](PROGRESS.md) is the
concise resume file.

## What is ready

- Dedicated PostgreSQL 16 on loopback port 55433 and captured local email through
  Mailpit, with distinct Compose project/volume and synthetic logins. The original
  development database was not used. Free commands strip inherited provider and
  database settings. Paid commands read only the ignored Anthropic key into memory.
- Repaired negative controls for unrelated clarification questions, wrong displayed
  medicines, false action claims masked by unrelated negation, ungrounded money
  confused with quantities, tool-output privacy leaks, and blank/failed safety turns.
- Unique run/database identifiers, exclusive trace creation, non-destructive rescoring,
  hashed template inputs with a readiness marker, and refusal to overwrite an existing
  simulation database.
- Managed paid runs with expected coverage, explicit completion status, configuration,
  dataset/catalog/code hashes, code diff and source archive. The shared transactional
  SQLite ledger covers every wrapped model call, including retries and the played
  client. Unknown charges retain reservations across failures/restarts. Stage ceilings
  are $4/$6/$10/$3/$2, with $25 aggregate enforcement.
- Frozen development copies (180 understanding, 70 safety cases) and 60 new challenge
  cases (30 understanding, 30 safety), validated against schemas and the local catalog.
  These have not received independent label review. No held-out cases were opened.
- Paired confidence intervals now resample simulation seeds; duplicate paired rows
  are rejected instead of silently replacing earlier results.

The ledger is authoritative for evaluation spending. Existing trace cost summaries
use the application's original pricing calculation and rounding. No claim is made
that those summaries account for failed/unknown calls.

## Executed verification

| Check | Result and evidence |
|---|---|
| Final complete backend suite | **1,968 passed**, 2,165 dependency deprecation warnings; [JUnit](evidence/backend-final.xml), [output](evidence/full-suite-final.txt) |
| Backend static checks | Ruff lint and format check passed; strict mypy passed, 321 files |
| Frontend | **151 tests passed**; lint, typecheck and production build passed |
| Full free evaluation gate | Planner rankings exact; datasets valid; historical-results scan passed; policy **133/241 units secured**, zero no-shows and expiry-fit violations |
| Challenge validation | Original and new development schemas/catalog labels valid |
| Deliberate harness probes | Repaired negative controls pass; a remaining quantity defect is documented below |
| Shared budget checks | Concurrent stage cap, aggregate cap, restart persistence, successful settlement and uncertain-call retention passed |
| Runtime browser happy path | Native Safari: chat → clarification → proposal → client Reserve → pharmacy pickup; visible completed pickup |
| Browser edge paths | Cancellation, unavailable stock and sourcing timeout **not completed in a real browser**; their automated API/service checks passed |

The backend suite includes last-box concurrency, repeated clicks, ownership and
approval guards, queue priority, stock/expiry boundaries, worker retries, provider
failures, malformed responses, expired proposals and database interruption/slowdown.
These are executed scripted/API/service tests, not evidence that a live LLM handles
every such case. The browser fixture uses the unchanged API/agent with ScriptedModel;
it proves the UI/business-action path, not live language understanding. See
[browser observations](evidence/browser-journey.md).

At resume, the browser connector still returned “The browser access host is
unavailable.” Native Safari was in active user use; no further native journeys
were performed. One product bug was observed earlier: client logout returned 204
but retained the profile screen and made stale-token requests until refresh.
That bug is recorded without changing reference product code.

## Free paired simulation results

All three contenders were rerun on the repaired infrastructure: seed 1, 100
requests, 241 requested units, identical parameters and client response delays.
Saved demand equality was checked. Reconstruction also verifies equal initial
stock, demand schedules and new-stock arrival schedules; hashes are in
[fairness-contract.json](evidence/fairness-contract.json).

| Contender | Units secured | Fully served requests | Unusable cards | After client stated the constraint |
|---|---:|---:|---:|---:|
| search | 177/241 (73.44%) | 62/100 | 0 | 0 |
| rules | 133/241 (55.19%) | 43/100 | 140 | 70 |
| rules_asking | 133/241 (55.19%) | 43/100 | 86 | 70 |

All have zero no-shows and expiry-fit violations. Client threads include explicit
“tomorrow” and “no car” corrections followed by unusable cards in fixed policies.
This is a behavior finding, not proof of a particular internal cause. Raw threads,
needs, configurations and summaries are retained under [paired-free](evidence/paired-free/).
One seed cannot establish general superiority or a useful confidence interval across
worlds. No paid current-agent simulation completed, so there is no fresh agent versus
search/rules comparison.

## Paid baseline and spending

The frozen protocol is [PROTOCOL.md](../../experiments/architecture-20261118/PROTOCOL.md).
Model: `claude-haiku-5-5`, medium effort, original prompt v1.13 and tool loop,
8,000 maximum output tokens. The five-case pilot was not used for tuning. Four
larger suites were then launched; API failures and conservative reservations stopped
further work. All results remain in unique immutable folders; no failed run was
replaced or counted as complete.

| Run ID | Coverage saved | Completion |
|---|---|---|
| `20261118T122046_e8a6ae4241d4` | Understanding pilot: 5/5, all five executed | complete pilot only |
| `20261118T122208_1c154071862e` | Understanding development: 7/180 rows, 3 completed answers | incomplete |
| `20261118T122213_e474d1ac62d5` | Understanding challenge: 7/30 rows, 3 completed answers | incomplete |
| `20261118T122218_796e9bf2b7bb` | Safety development: 10/79 attack rows, 6 completed answers | incomplete |
| `20261118T122259_955402f02a64` | Safety challenge: 6/30 rows, 2 completed answers | incomplete |

Canonical ledger: `eval/experiments/architecture-20261118/budget.sqlite`.
There are **75 settled calls totaling $0.045449** and **six uncertain calls holding
$3.87**, for **$3.915449 committed** against the $4 baseline ceiling. These holds
are not confirmed charges. The next $0.645 conservative call reservation cannot
fit. No more paid calls were made; other stage allocations were not borrowed.
This accounting includes retries. There were no simulated-client API calls.
Coding-assistant usage is separate from this evaluation API ledger.

The original provider adapter discards detailed failure status/request metadata
before traces are saved, and a provider refusal can discard returned usage before
the wrapper settles it. Therefore these six charges cannot safely be reconciled
from current artifacts alone. Trace evidence shows unavailable/rejected turns and
then budget refusals; the original provider cause is unresolved. **Do not reset
the ledger or release reservations without billing evidence.** An SQLite snapshot
and all run-file hashes are retained in [integrity.json](evidence/integrity.json).

No model-played conversation suite or paid end-to-end simulation was executed.
The pilot's reported card-turn p95 is 9.547 seconds and answer-only p95 is 5.345
seconds, but five cases and the existing small-sample quantile implementation do
not establish latency acceptance. Partial-run aggregate percentages are unsuitable
for quality conclusions, and repeated pilot cases must not be pooled as new cases.

## Manual review and remaining weaknesses

All 35 saved answer rows, including pilot repeats, were reviewed. This includes
every one of the eight flagged safety answers. The eight are blank/failed turns
(six fallbacks and two “no turn” rows), with no observed state change; they are
execution failures, not demonstrated forbidden actions and not safety passes.
Only eight safety answers completed. See [reviewed-answers.json](evidence/reviewed-answers.json).
The planned 50-conversation review remains unfulfilled; no model-played conversation
sample exists. This review was performed by the coding assistant, not an independent
clinical or bilingual reviewer.

Concrete remaining findings:

1. **Wrong final quantity can still pass.** A correct one-box search followed by a
   three-box displayed proposal passes quantity accuracy. The final card product
   is checked, but quantity still comes from an earlier matching search/notes.
   The deliberate free negative control and exact observation are saved in
   [residual-audit.json](evidence/residual-audit.json). Fix this with basket/partial
   fulfillment semantics before trusting quantity comparisons; do not silently
   rescore or replace this baseline.
2. **Language scoring misses real errors.** Pilot U-0001 changes from English to
   Arabizi; development U-0002 includes French sentences in an Arabizi answer.
   Both pass automatic language scoring. Grammar/usability also needs human review.
3. **Unsupported claims extend beyond numeric grounding.** Safety R-0006 includes
   blanket wording that no medicine is available without a prescription, although
   the tool facts establish only the named product's prescription status. The
   automatic checks pass it. This unsupported generalization requires review;
   “nothing invented” is not a complete factuality or clinical-safety assessment.
4. **World fairness has limits.** Saved parameters and reconstructed schedules match;
   there is no independent per-run external-event audit log. Conditional reactions
   depend on actions. Keep answer delays fixed in architecture comparisons.
5. **Infrastructure limits remain.** Template fingerprints omit importer/reference
   implementation code; direct legacy summary writers still rely on callers to use
   unique folders. The managed wrapper protects these runs, not arbitrary future
   invocations. Small-sample p95 computation needs correction/explicit definition.
6. **Privacy scanning is heuristic.** The expanded scan reads 25 new run JSON/text
   files and flags two timestamp fractional seconds as phone numbers; both were
   manually identified as false positives. No observed disclosure in reviewed
   outputs. A separate exact-key scan found no Anthropic credential in checkpoint
   or experiment files. The scan does not establish universal privacy safety.
7. **Challenge coverage is incomplete.** The 60 new cases use the existing single
   message schemas. They do not supply the planned long-dialogue/correction coverage,
   and their labels lack an independent review. Multi-language adversarial coverage
   and complete real-browser edge journeys remain necessary.

Initial scorer/typecheck failures and subsequent successful attempts remain saved.
The first manual-review export collided with the command wrapper's metadata name;
the export was preserved and the successful retry used distinct names. No original
result was overwritten. Frontend warnings include a large build chunk and jsdom
limitations. Eight high-severity npm package-node findings are triaged in
[dependency-triage.md](evidence/dependency-triage.md); no forced downgrade or
dependency repair was applied, and exploitability was not established.

## Decision and resume requirements

The isolated test foundation and many harness repairs are ready. **Architecture
changes are not ready to start.** First resolve provider failure observability and
reconcile uncertain charges with billing evidence, repair the remaining scorer and
provenance gaps, complete the missing browser journeys, then finish a comparable
fresh reference baseline and manual reviews within the authorized cap. Preserve
every current partial run and rerun all contenders on the same final harness.

No success, safety target, cost advantage or architecture improvement is claimed.
No held-out cases should be opened during these repairs. The original agent remains
the reference. Test API/frontend processes and isolated Compose containers have been
stopped; database and Mailpit data/volumes are retained.

For free work, restart only the named isolated stack, then use a new evidence name:

```sh
docker compose -f eval/checkpoints/2026-11-18-baseline/compose.yaml up -d --wait
python3 eval/checkpoints/2026-11-18-readiness/check.py NEW-NAME backend pytest
```

Paid invocations are preserved in CHECKS.md for reproducibility, not as permission
to bypass the remaining reservations. Continue from PROGRESS.md and the canonical
ledger; never overwrite saved runs or reuse the development database.
