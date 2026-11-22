# Architecture comparison progress — 2026-11-19

Branch: `test/agent-evaluation`. No push, deployment, held-out inspection or main merge authorized.
Existing handoff and historical evidence preserved. Current owner-approved reference:
`8e689a583b69a399598f557ac8a2310571c1dbb1`; remote main `28cf4f1`, already integrated.
Reference source hashes: `reference.json`. Historical paid results are not new-reference results.

Completed:
- Read the four requested starting reports and fetched origin (no upstream delta).
- Owner confirmed teammate implementation complete; use current main.
- Added explicit owner-approved AI-assisted acceptance; default human gate retained.
- Frozen 352 accepted cases: 230 understanding, 107 safety, 15 conversations; 22 exclusions
  remain in the draft with reasons. Nine actual user decisions and 135 AI decisions retain
  their attribution. Acceptance is not 144 human checks. See `../../development-v2/freeze.json`.
- Implemented separate staged/verified contenders; current remains default.
- Extended existing experiment runner: architecture, stage, fixed IDs, repetition, smoke kind.
- Revised ceilings $6/$6/$8/$3/$2; same canonical `../architecture-20261118/budget.sqlite`.
- Frozen balanced 60-case `screening.json` and `targets.json` before comparative scores.
  Initial proportional sample omitted mixed safety; retained as rejected draft before scoring.
- Focused free checks: 350 passed. Ruff and mypy (340 files) passed.
- Provider model availability checked without generation: configured model available.

Free gate passed (133/241, zero no-shows/expiry). Clean full backend: 2131 passed;
366 focused shared-harness checks passed. Three repaired five-case smokes completed:
A $0.017819, B $0.013621, C $0.035786. Earlier A smoke $0.015916 and interrupted B
trace/scorer call $0.000288 retained in their original stages.

C lacked authoritative application-policy context and incorrectly questioned mandatory
logistics. Added the reference rules as read-only context; 359 focused checks pass.
Corrected C smoke completed ($0.038621 ledger). Final common Arabic question-recognition repair
passed 563 scripted checks, lint and mypy. Final five-case smokes completed: A $0.013994, B $0.016317, C $0.037238.
No new uncertain provider charges. Final sequential screening running in session 45063.
Evidence: screening-final.jsonl and screening-final-step-NN.txt. The first pre-fix screening A suite may finish without
interrupting paid calls; STOP_SCREENING prevents the next suite before setup.
That earlier source version is excluded from final comparison, never overwritten.
screening-source-freeze.json now pins the final common source. Sample and targets are unchanged.
The old orchestration stopped after A's pre-fix understanding suite (no next paid suite).

Measured screening forecast $1.747876; 2x planning margin $3.495752 plus one $0.645
reservation and initial screening charges fit $6. All extra/failed calls stay in their
originating stages. No new uncertain provider charges so far.
Historical ledger: $0.045449 known, $3.87 uncertain, $3.915449 committed (81 calls).
Do not release old reservations without attributable billing evidence. Retries stay in stage.

Exact free commands (repository root):
`python3 eval/experiments/architecture-20261119/check.py NAME pytest`
`python3 eval/experiments/architecture-20261119/check.py NAME python -m dawalink.evals.before_commit`
Evidence is exclusive: choose a new NAME for every invocation. Local containers use existing
`eval/checkpoints/2026-11-18-baseline/compose.yaml`, port 55433, synthetic credentials.

Paid entry point from backend (after free checks pass):
`.venv/bin/python ../eval/experiments/architecture-20261119/paid.py understanding --architecture current --stage baseline --kind smoke --repetition smoke --cases IDS --model claude-haiku-5-5 --effort medium --max-usd 1`
Use five IDs from `screening.json` smoke_understanding. B/C smoke use screening stage.
Every call uses the canonical ledger. Each runner invocation saves a unique immutable run
under `../architecture-20261118/runs`; do not pool smoke into comparative estimates.
Do not proceed to larger runs until all smoke outcomes, status and costs are reviewed.

## Live final screening / exact resume

Final execution is **running**, unified-exec session **45063**. Do not start a duplicate.
First final run: `20261119T155557_e5728d4d1c99` (A, understanding, repetition 1).
`evidence/screening-final.jsonl` records completed suite steps only; individual live
`screening-final-step-NN.txt` logs are flushed and each suite's turns are already durable.
The 18 saved commands run A-understanding/safety/multiturn, B all three, C all three,
then C/B/A for repetition 2. Same fixed IDs throughout. Each call reserves atomically.

Final smokes:
- A `20261119T155213_9ba78d29369e`: five complete, $0.013994 canonical usage.
- B `20261119T155214_6c95f009cdad`: five complete, $0.016317.
- C `20261119T155213_841d75050a11`: five complete, $0.037238.
Every smoke is excluded from comparison. Manual smoke reviews are under evidence;
confirmed B missing-strength question and C English-for-Arabizi failure remain findings.
Automatic language and clarification regexes still have documented limitations.

Once this process ends, inspect its events and completion manifests. If provider holds,
budget refusal, missing coverage or an exception stopped it, investigate once; do not
repeatedly rerun. If safe and a remaining independent command is authorized, use a NEW
execution ID and `--start-step N` (never overwrite logs), through execute_screening.py.
All paid calls still enter the original experiment runner; no replacement model runner.

After final coverage: run `backend/.venv/bin/python eval/experiments/architecture-20261119/analyze.py NEW-OUTPUT.json`.
Only comparison-kind manifests whose hashes equal screening-source-freeze.json are eligible.
The earlier A run `20261119T154330_08f752c52d2a` is excluded for harness drift, although its
manifest's original kind remains comparison; its $0.081445 remains charged to screening.
Use review_export.py RUN --flags-only for compact raw inspection. Review every safety and
semantic flag and cross-architecture disagreement; record assistant attribution, not human
review. Rank only after both repetitions. Normalize safety's chat/request rows per case.
Advance one challenger only under the fixed promotion rule; otherwise retain A and stop.
Expansion, if earned, uses the original runner and $8 expanded ceiling. Held-out remains
unopened, $3 held-out and $2 retry reserve unborrowed. Finish REPORT.md and a sealed final
ledger snapshot; stop isolated containers without deleting data. No push/deployment/main merge.

A repetition1 is complete: understanding30 + safety20 (24 observations) + conversations10
(30 exchanges). Runs: 155557_e5728d4d1c99 / 160209_564cc4cef04f / 160514_fb0c053439a6.
B understanding repetition1 is running as final step4. Manual A review covers all60 cases;
raw scorer errors and confirmed semantic failures are separately preserved in
`evidence/manual-adjudications.jsonl`. Review interpretation and bias limits are explicit
in `evidence/REVIEW_METHOD.md`. `summarize.py` aggregates only complete final-source runs,
groups safety by case, applies separate adjudications and bootstraps paired case clusters
(carrying both repetitions together). It never calls a model. `REPORT.md` is a draft until
both screening repetitions, disagreement review and the conditional advancement decision.

## Shared execution partitioning repair — live continuation

Old session45063 ended normally after step6: B's batched conversation M0014 returned
an invalid auxiliary schema (settled usage), causing the existing fail-fast runner to
skip M0015. No provider uncertainty or budget refusal. Do not restart session45063.
`coverage-repair.json` records the repair before C comparative scores: execute every
fixed conversation separately through the SAME runner for every architecture/repetition.
All have the identical first synthetic client, case-specific shelves, world seed and clock.
A failed conversation is retained and cannot skip another case. Source/sample/targets
unchanged. Prior A/B batched conversation runs are ancillary, never erased: their positive
and negative findings and costs remain in the report, including B's execution failure.

**Live session37980** runs `execute_screening.py --execution-id continuation --plan
screening-continuation-commands.json`. There are68 commands: remaining8 U/S suites in
C1/C2/B2/A2 order, then60 individual fixed-conversation invocations in A/B/C then C/B/A.
Combined primary coverage:12 U/S +60 individual conversation runs =72 invocations,
360 case observations (384 raw rows because safety has24 observations per20 cases).
The four completed A1/B1 U/S runs remain primary; only the two batched multiturn runs
are explicitly excluded from primary aggregation. This partition change and its timing
must be disclosed; it is not a new source tuning or deletion of failed results.
`analyze.py`, `summarize.py` and `audit_evidence.py` honor explicit ancillary exclusions.
