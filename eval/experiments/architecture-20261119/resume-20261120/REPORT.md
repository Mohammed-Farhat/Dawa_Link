# Resumed architecture evaluation — 20 November 2026

This supplement updates the earlier REPORT.md without overwriting its frozen evidence.
**Retain A. Paired screening is still incomplete; no challenger advanced.**

The owner replied “Not a problem use 0.645”. A bounded additional $0.645 screening
allowance raised its ceiling from $6 to $6.645. Aggregate ceiling stays $25; other
stage ceilings and all existing uncertain reservations remain unchanged. The small
bootstrap uses the existing experiment runner, model, source, sample, targets and
ledger; it changes only the authorized screening ceiling. Every new run records
the permission, effective limits and bootstrap hash in owner-allowance.json.

Queued C1 safety run `20261120T094710_31138f2a43a0` transmitted 85 model calls,
all settled from provider-reported usage, costing **$0.075497**. No new uncertain
charge occurred. It saved 21 of 24 planned context observations across 18 of 20
cases; 17 context observations (15 whole cases) executed successfully and passed
the frozen automatic safety checks. Three fallbacks and one no-turn observation
remain execution failures; two cases have no saved observation. The run is
explicitly incomplete, not a completed safety-equivalence test.

The final trace shows a workflow draft for R-1030 but no verifier response, then
immediate LLMRejected fallbacks for R-1036. Every transmitted call is settled;
remaining screening headroom is $0.644654, below the $0.645 next reservation by
$0.000346. No further suite or paid retry was started. R-1046/R-1050 were not run.

Reviewed all 21 saved observations and all nine safety disagreements involving C,
using the same manual rubric. No confirmed safety violation was found in the 17
successfully executed context observations. Preserve clarity concerns for R-0036
and R-1029 and the corrected escalation summary for R-0060. All raw checks are
retained. Review is by the implementation assistant, not human, independent or
blind. This partial result does not replace the earlier comparison or justify C.

| Accounting | USD |
|---|---:|
| Total provider-reported usage | 0.933524 |
| Unresolved reservations | 9.030000 |
| Current active-call reservations | 0 |
| Aggregate committed | 9.963524 |
| Aggregate ceiling | 25.000000 |
| Screening committed | 6.000346 |
| Revised screening ceiling | 6.645000 |

Known usage is calculated from provider token reports and frozen rates; it is
not an independently reconciled provider invoice. Unknown holds are maximum
reservations, not proven charges. Source/data/sample/targets stayed unchanged;
all prior ledger calls and events were verified unchanged. The isolated containers
were stopped with exit code 0; their volume remains. No held-out evaluation,
push, deployment or main merge occurred.

Full paired screening, C's missing/provider-failed cases, second repetitions,
normalized fixed conversations and conditional expansion remain outstanding.
Further paid work requires attributable reconciliation or an explicit revision
of the screening limit. The original report describes all unchanged methods,
implementation details, test evidence and limitations. See PROGRESS.md here for
current resume requirements, integrity.json for accounting checks and
manual-review.jsonl for every new observation review.
