# Architecture evaluation — stopped at external budget blocker

Implementation, feasible free verification/review and the development report are complete.
**Paired screening is incomplete. Retain A/current; no challenger advanced.**

Branch `test/agent-evaluation`, HEAD `8e689a583b69a399598f557ac8a2310571c1dbb1` contains
completed main `28cf4f1d3f8412eff3ee7a10ffb9eb40102f1313`, explicitly accepted by the owner.
No push, deployment, held-out inspection or main merge. Original handoff preserved.

## Completed

- Accepted/froze352 development cases (230U/107S/15M), retaining22 exclusions/reasons,
  nine user and135 AI adjudications with honest attribution; default human gate retained.
- Implemented independent staged/verified variants; current remains default. Public APIs,
  reference prompts/tools/guards and backend stock/approval/ownership authority unchanged.
- Extended existing runner and canonical ledger; ceilings6/6/8/3/2 aggregate25.
- Full backend2131 passed. After final common harness/verifier-context changes,563 focused
  tests, Ruff lint/format and mypy340 files passed. Free evaluation gate passed.
- Final5-case smokes completed A/B/C; earlier calibration/failed evidence retained separately.
- Primary130 case observations: A1 U30/S20, B1 U30/S20, C1 U30 attempts (26 executed).
  230/360 planned case observations missing; no repetition2. All normalized M cases unrun.
- Ancillary batched M: A10 complete; B8 complete+1 failed, M0015 skipped by fail-fast.
  Shared partition repair planned individual M runs for all contenders before C scores;
  no such invocation started. Prior batches/costs/failures retained in coverage-repair.json.
- Reviewed all saved safety/semantic flags,29 primary tool/card/check/outcome disagreements,
  and all19 saved fixed-conversation attempts (18 complete,55 exchanges). Assistant review,
  not human/independent/blind. Raw scores and separate adjudications retained.
- Integrity audit passed: frozen source/sample/targets/data intact, all81 original ledger
  entries unchanged, every new attempt accounted. Screening explicitly incomplete.
- Isolated PostgreSQL/Mailpit containers stopped (exit0); evaluation-data volume retained.

## Spending and blocker

Canonical: `../architecture-20261118/budget.sqlite`. Known$0.858027; unresolved holds$9.03;
committed$9.888027 of$25. Historical known$0.045449; new known$0.812578.
Baseline known$0.093178+old holds$3.87 = committed$3.963178 of$6.
Screening known$0.764849+new holds$5.16 = committed$5.924849 of$6.
Only$0.075151 screening headroom remains, below one$0.645 reservation.
Expanded/held-out/retry allocations untouched. No budget borrowed or ledger reset.

C1 understanding run `20261119T162646_21096b0ddb62` hit a provider timeout/connection
failures; reference retries/subsequent cases generated8 uncertain workflow calls, all held.
Four cases were unavailable. Later HTTP HEAD connectivity responded but does not establish
billing attribution. No further paid generation after the suite/orchestrator stopped.
`STOP_SCREENING` prevents accidental comparison restart. See evidence/provider-incident.json.

## Evidence

- Final recommendation/methodology/coverage/results/limitations: REPORT.md.
- Original reference: reference.json, reference-agent.tar.gz.
- Source pin: screening-source-freeze.json; sample: screening.json; targets: targets.json.
- Accepted data/attribution freeze: ../../development-v2/freeze.json.
- Final observations: evidence/final-analysis-v2.json, final-summary.json,
  understanding-comparison.json. Every run is immutable under ../architecture-20261118/runs.
- Manual decisions/coverage: evidence/manual-adjudications.jsonl,
  manual-review-coverage.jsonl, disagreement-review.json, REVIEW_METHOD.md.
- Preservation/accounting: evidence/final-integrity-audit.json, final-workspace.json,
  provider-incident.json, shutdown.json; final ledger backup and seal accompany this file.
- Original sequential execution: evidence/screening-final.jsonl (ended after step6).
  Continuation: evidence/screening-continuation.jsonl (ended after step1).
  Old sessions45063/37980 exited. Do not restart either or duplicate completed runs.

## Conditional exact resume

No more paid work is currently feasible under the authorized screening ceiling.
Require attributable provider billing evidence for specific uncertain calls, or explicit
owner revision of stage ceilings within$25. Verify attribution before Ledger.reconcile;
retain receipt hashes and originals. Do not infer zero cost from connection errors, move
calls, erase reservations, or borrow held-out/retry reserves. Recalculate remaining costs
and ensure the next reservation fits both ceilings before removing STOP_SCREENING.

If those conditions are met and source/labels remain unchanged, re-enable only isolated
containers with the existing compose file. The next queued suite is C1 safety. From repo root:

`backend/.venv/bin/python eval/experiments/architecture-20261119/execute_screening.py --execution-id resume-UNIQUE --plan screening-continuation-commands.json --start-step 2`

Use a new unused execution ID. This is67 remaining invocations (7U/S+60 independent M),
not permission to bypass the blocker. Assess recovery of C1 provider-failed understanding
separately before any final inference; retain the failed original and charge any retry to
screening. No silent pooling or deletion. If source changes, freeze a new version and do not
pool earlier-source results. Never rerun a blocked action repeatedly.

Offline reproduction, with a new output path each time:
`backend/.venv/bin/python eval/experiments/architecture-20261119/analyze.py OUTPUT.json`
`backend/.venv/bin/python eval/experiments/architecture-20261119/summarize.py OUTPUT.json`
`backend/.venv/bin/python eval/experiments/architecture-20261119/audit_evidence.py OUTPUT.json --allow-incomplete`

Only after complete paired screening/review may one challenger earn fresh full-development
runs and prioritized simulations/played clients/stress under expanded$8. Held-out remains
reserved for a later task. See REPORT.md for omissions and required checks.
