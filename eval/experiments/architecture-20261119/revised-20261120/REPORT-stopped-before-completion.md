# DawaLink architecture evaluation — updated 20 November 2026

**Retain A/current. Paired screening is incomplete; no challenger earned expansion.**
Two independent provider timeouts interrupted the latest recovery attempts. The
approved total remains $25; the stop reflects provider reliability, not exhaustion
of that total. All successful/failed outcomes, costs and uncertain holds remain.

## Implemented and verified

A preserves the completed reference agent. B extracts cumulative structured facts,
handles corrections/removals and uses code to route missing information or the
existing catalog/tool workflow. C adds a read-only draft verifier and at most one
correction through the existing guarded workflow. They are independent variants;
current remains default, with unchanged public APIs and backend business authority.

The accepted development subset has 352 cases, nine direct user decisions and 135
AI adjudications with honest attribution. Full backend tests: 2,131 passed; final
focused checks: 563 passed, with Ruff/format/mypy and free gates passing. Backend
source/sample/targets/data remain unchanged since those checks. New budget wrappers
passed free checks for approved caps, settlement, unknown-charge stop and unchanged
aggregate; they use the existing runner, not a separate evaluation implementation.

## Coverage and evidence

Original primary A1 U30/S20 and B1 U30/S20 are retained. C1 U has all 30 original
observations, including four provider failures. The earlier C1 safety attempt saved
21/24 contexts across 18/20 cases; 17 contexts executed. It stopped at the prior
reservation limit. It is not a completed safety-equivalence comparison.

Under the new $4/$9/$7/$3/$2 allocation, two full-batch C1 recovery suites were
attempted in order. Understanding run `20261120T100220_fc0fd422269f` saved seven
observations (three executed), with 32 settled calls costing $0.032105 and one
unknown $0.645 hold. Safety run `20261120T100958_6995d4b9b0d9` saved seven contexts
(three executed), with 17 settled calls costing $0.015369 and another unknown
$0.645 hold. Both unknown calls raised APITimeoutError after about 30 seconds,
returning no request ID. No further paid work followed the second independent failure.

All 14 saved observations were reviewed by the implementation assistant, not a
human, independent or blind reviewer. The completed safety responses refused
clinical advice/role override and showed no unauthorized state mutation. Missing
responses and false automatic checks after the stop are execution failures, not
proof of completed unsafe actions. A valid Concor strength question in ancillary
U-0014 exposes the already-known regex limitation. Preserve every raw score.

The original C1 U observation set remains primary, including provider failures;
its failed recovery stays ancillary. Partial C1 safety and its failed full recovery
remain separately reported. No successful-only pooling. Full-batch recovery was
chosen because subset execution changes the safety world's attacker/victim
assignment. This is an explicit post-incident protocol amendment, not preregistered
blind evaluation. Neither recovery produced eligible complete replacement evidence.

No second repetition or normalized fixed-conversation invocation started. Earlier
A/B batched conversations remain ancillary with their original successes/failures.
The original report documents manual review of safety/semantic flags and paired
disagreements; this update adds the 14 new observations. Screening still cannot
support promotion. Original first-pass U raw/manual pass counts remain A27/27,
B19/20 and C21/24 (C executed26/30); unequal/partial coverage prevents ranking.

## Spending

| Item | USD |
|---|---:|
| Known provider-reported usage | 0.980998 |
| Unresolved reservations | 10.320000 |
| Active-call reservations | 0 |
| Aggregate committed | 11.300998 |
| Aggregate ceiling | 25.000000 |
| Screening committed / ceiling | 7.337820 / 9 |
| Baseline committed / ceiling | 3.963178 / 4 |

Expanded $7, held-out $3 and retry reserve $2 remain untouched. Known usage comes
from returned token usage and recorded rates; it is not an independently reconciled
invoice. Uncertain reservations are not proven charges. No old call/event was
altered; the two new unknown calls remain fully held. Repeated timeout inspection
and a free HTTP 405 reachability response do not establish attributable billing or
reliable generation. The next $0.645 reservation would leave $1.017180 of effective
screening spending capacity; forecasts must be revisited before any future resume.

## Recommendation and outstanding work

Keep A. Earlier observed clarification/language/completeness regressions and C's
higher cost/latency are documented in ../REPORT.md; the new partial evidence gives
no basis to replace it. Do not expand before complete paired screening and review.
Fresh full development comparison, seed-paired simulations, model-played dialogue,
stress scenarios and held-out evaluation remain unrun. Six-hour fulfillment,
fully served requests, real successful-request cost and seed-paired intervals are
therefore unmeasured. All provider failures remain part of execution reliability.

Both isolated containers stopped with exit code 0; data volume preserved. No
held-out inspection, push, deployment or main merge. PROGRESS.md here records the
current next steps. integrity.json, provider-incident.json, budget-final.sqlite and
manual review files preserve accounting and lineage; ../REPORT.md retains the
original detailed implementation, test, sample and comparative methodology.
