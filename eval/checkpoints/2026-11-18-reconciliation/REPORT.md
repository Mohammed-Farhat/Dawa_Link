# Pre-architecture reconciliation — 18 November 2026

Free reconciliation is complete. Keep the current agent: the fresh paid baseline
and its manual review remain incomplete, so architecture comparison is not ready.
No additional paid evaluation calls were made during this reconciliation.

Reference: `1e17db0ea522622caaf8da41d60df4ef152ccec3`, branch
`test/agent-evaluation`. Agent architecture, prompts and business rules remain
unchanged. No commits, push, merge, deployment or held-out inspection. Historical
checkpoints, partial runs and the untracked handoff document are preserved.
See [final integrity evidence](evidence/final-integrity-v2.json),
[exact command index](CHECKS.md), [protocol](PROTOCOL.md), and [resume file](PROGRESS.md).

## Repairs and evidence

| Area | Result |
|---|---|
| Cost accounting | The evaluation-only provider wrapper records returned usage before refusal/parsing, reserves every SDK request, disables hidden SDK retries, and records only safe request ID/status/error type/duration on failure. Agent retries and model-played clients share the ledger. Unknown charges keep their holds. Audited reconciliation requires an external-evidence hash; no real adjustment was applied. |
| Final quantities | Scores actual displayed proposal items, distinguishing alternatives from a split multi-stop plan. Wrong/excess/missing quantities fail. Valid partial fulfillment is separate from complete fulfillment. Earlier correct search arguments cannot excuse a wrong card. |
| Price grounding | Matches amounts by product, pharmacy and currency, including actual Preview tool-response shapes. Quantities/client numbers cannot justify invented prices; swapped product/pharmacy prices fail negative controls. This is a harness repair, not evidence that a live agent invented prices. |
| Language/factuality | Candidate flags catch observed language switches and blanket prescription claims. Every output explicitly retains incomplete semantic checks and an unset manual verdict. Heuristics cannot certify general factual accuracy. |
| Safety | Failed/blank turns are execution failures, excluded from both safety passes and demonstrated violations. Actual forbidden state changes remain separately checked. |
| Timing | p95 uses nearest rank, including small samples. Historical summaries are not silently rewritten. |
| Provenance/results | Template fingerprint includes importer/reference implementation; unique run/database IDs, exclusive writers, raw coverage and completion checks, source archives and hashes. Failed/partial coverage cannot become complete merely because a command exits zero. |
| Simulation fairness | Actual initial stock/world/schedules and timing parameters are hashed before play. Actual stock arrivals and keyed random draws/delays are saved and compared; action-dependent event sets may differ. |

Relevant negative controls and budget concurrency/restart/refusal/parser tests are
in [test_readiness.py](../../../backend/tests/unit/evals/test_readiness.py), with
grounding and conversation tests alongside it. Their executed results are indexed
in [CHECKS.md](CHECKS.md). The application agent/provider files were not modified;
the accounting wrapper is confined to evaluation runners.

## Separate logout repair and browser verification

Logout previously cleared the entire query cache, detaching the mounted session
observer. A successful logout could leave the profile visible and stale requests
running until refresh. The fix cancels queries, explicitly sets the observed user
to null, and removes other cached data while retaining the session observer.
The [failing reproduction](evidence/logout-reproduction.txt) is preserved;
[successful and failed-response regressions](evidence/logout-fixed.txt) both pass.

Native Safari verified chat → clarification → proposal → client approval →
reservation → pharmacy pickup; cancellation; pharmacy unavailable with client
notification; and a six-hour sourcing timeout with the final closed-request UI.
Repeated logout immediately showed login without refresh. These journeys use the
unchanged agent/API with a scripted model and synthetic accounts: they establish
UI/business-action behavior, not live language understanding. The clock was
advanced only in the disposable fixture. [Observed steps](evidence/browser-journeys.md).

## Executed checks

| Check | Result |
|---|---|
| Full backend | **1,986 passed**, 2,175 dependency deprecation warnings; [JUnit](evidence/backend-final.xml), [output](evidence/final-backend.txt) |
| Latest simulation addition | **92 targeted tests passed**; [output](evidence/events-tests.txt). This follows the full suite above. |
| Backend static checks | Ruff lint/format passed; final strict mypy: **325 files**, [output](evidence/events-types.txt) |
| Frontend | **153 tests passed**, lint and TypeScript/production build passed. Build retains a >500 kB chunk warning; jsdom canvas warnings remain. |
| Free evaluation gate | Planner exact, datasets valid, 289 historical result files passed privacy scan; policy 133/241 units, zero no-shows/expiry-fit violations. [Output](evidence/free-gate.txt). Latest quick gate also passed after multi-turn additions. |
| Multi-turn integration | Four focused tests passed, including the unchanged agent against a real isolated database; current-turn corrections and execution versus quality failure checked. |
| Final paired audit | All three complete; identical code/input hashes, 180 identical successfully applied stock arrivals each, zero differences for shared draws. [Audit](evidence/event-audit-findings.json). |

The full backend suite includes last-box races, repeated actions, ownership,
approval and priority guards, expired proposals, malformed/provider failures,
worker retries and database interruptions. Passing scripted tests does not prove
that the live LLM succeeds on these cases.

Latest seed-1 runs have 100 requests / 241 requested units and identical timing:

| Contender / immutable run ID | Units secured | Fully served | Unusable cards / after constraint stated |
|---|---:|---:|---:|
| search — `20261118T173120_8802618a6095` | 177 (73.44%) | 62% | 0 / 0 |
| rules — `20261118T173119_c88ce825ede3` | 133 (55.19%) | 43% | 140 / 70 |
| rules_asking — `20261118T173119_bde18996e9e1` | 133 (55.19%) | 43% | 86 / 70 |

All have zero no-shows and expiry-fit violations. Shared draws compared: 105
search/rules, 105 search/rules_asking, 547 rules/rules_asking; all equal. Conditional
draw sets differ because policies take different actions. One seed gives no useful
cross-world confidence claim. There is still no completed paid agent simulation.
Earlier runs were retained, not replaced.

## Cases, observed agent failures and unresolved gaps

Reviewed copies combine 180 original + 30 challenge understanding cases and
70 original + 30 challenge safety cases. Corrected U-1012's language label and
added actual no-state-change checks to 12 adversarial cases. Original copies are
unchanged. Eight new fixed conversations / 24 turns cover partial answers,
quantity/budget/day/transport corrections, dropped medicines, conflicting requests
and an eight-turn conversation. These exercise current-turn proposals against
updated cumulative facts. [Label review](evidence/development-label-audit.json).

Frozen hashes: [reconciliation-freeze.json](../../experiments/architecture-20261118/reconciliation-freeze.json).
Use `EVAL_DATASET=reviewed`; no held-out cases were opened. The same coding session
authored/reviewed these labels; independent agreement is outstanding. New challenge
understanding and multi-turn coverage is heavily Concor-centered; adversarial
language coverage is English-heavy. Fixed conversation messages do not adapt to
answers and do not replace the model-played suite or human review.

The earlier [manual review](../2026-11-18-readiness/evidence/reviewed-answers.json)
covered all 35 saved rows and all eight safety flags. Those flags were six fallbacks
and two no-turn rows: execution failures, not demonstrated violations or passes.
Only eight safety answers completed. Genuine observed issues remain in the
unchanged reference: English → Arabizi, unwanted French, and an unsupported
blanket prescription claim. The harness now raises review candidates; this work
does not fix those agent behaviors. No 50-conversation sample exists yet.

## Spending and architecture gate

Canonical ledger: `eval/experiments/architecture-20261118/budget.sqlite`.
All 81 original call rows remain identical to the backup: 75 settled calls with
**$0.045449 usage-derived cost**, plus six uncertain **$3.87 reservations**, totaling
**$3.915449 committed** of the $4 baseline ceiling. $3.87 is six × $0.645 holds,
not confirmed charges. A further $0.645 reservation cannot fit. No holds were
released, no other allocation borrowed, no API calls added. An additive event table
supports future audited adjustments; the entire database is not claimed byte-identical.

[Billing inventory](evidence/billing-inventory.json) records affected call/run IDs
and UTC times. Existing failures lack reliable provider request/usage metadata;
their actual charges cannot be established locally. Provider billing/usage evidence
attributable to those calls is needed to adjust them. An aggregate invoice that
cannot distinguish unrelated account traffic is insufficient on its own.

After evidence permits the next reservation, run a new reference baseline using
the frozen reviewed cases, original model/settings and shared ledger. Review every
safety/semantic flag and 50 seeded conversations, and record incomplete coverage
if the ceiling is reached. Resolve independent label agreement before treating
measurements as conclusive. Architecture changes remain a later explicit stage.

## Failures retained and practical limits

Initial logout failure, intermediate test/type/lint/format failures, browser fixture
selection error and a port-in-use server start are preserved alongside successful
corrections. A development-label export succeeded but its wrapper then failed on
a metadata filename collision; its report/log remain intact. Metadata now uses
`.command.json`. The no-key entrypoint intentionally exited 1 with an incomplete
manifest and zero new calls. Its double-load warning was corrected with importlib
dispatch and a subsequent successful free run. Browser servers were intentionally
terminated after verification. These are distinct from unresolved paid failures.

Expanded result privacy scanning remains heuristic; final integrity evidence records
candidates and their disposition. Exact configured credential scans cover saved
checkpoint/experiment artifacts without printing keys. Neither scan establishes
universal privacy safety. Event logs are saved after successful simulation play;
an interrupted run may have partial turn traces without a completed event log.

Temporary browser servers are stopped. Isolated PostgreSQL/Mailpit data are retained
for reproducibility; final stop status is in [CHECKS.md](CHECKS.md). No production
or original development database was used.
