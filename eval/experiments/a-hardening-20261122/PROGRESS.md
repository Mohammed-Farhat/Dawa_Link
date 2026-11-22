# A hardening checkpoint — 22 November 2026

Goal active. Work sequentially on test/agent-evaluation; preserve checkout. No push,
deployment or main merge. Unrelated handoff remains untracked and unchanged.

## Completed

- Historical architecture preserved separately in bdc5c16; A retained, no B/C tuning.
  Historical A/B/C outcomes describe their original source, not repaired A.
- Initial A grounding/language/preferences repairs and separate scorer repairs committed.
  Earlier free gates and broad tests passed; do not repeat unchanged checks.
- Candidate5 source a6c231c: English reference IDs cannot masquerade as Arabizi;
  universal equal-price claims need complete supporting scope; nearest/cheapest
  recommendations checked against feasible same-product options. Explicit instructions
  survive clarifications independently of model notes. A failed preference repair uses
  text-only fallback, excluding its rejected recommendation cards.
- Candidate5 affected tests: 517 passed; Ruff passed; mypy10 source files passed.
  evidence/candidate5-final-{tests,lint,types}.txt.
- Candidate5 pilots: understanding U0145/U0146/U1019 run
  20261122T192655_3c3efda9076a ($0.010916), safety R1022 run
  20261122T192807_71ceae8851d0 ($0.000420). All execution successful; recommendation
  and English refusal checks correct. Joined-turn grounding scorer false flags and
  ambiguous card-holds wording retained in assistant review. No independent acceptance.

## Active primary evaluation — do not duplicate

Candidate5 primary pin SHA256:
fb8da0d66a6147e393f6b1e2608d3c9d91f792e8866196107757b7dd384a86c1.
Candidate5 pilot pin preserved separately as candidate5-pilot-pin.json.
Accepted freeze SHA256:
9e8f67f313643d6721d8667ce7ea57f8dbea61c438702c0479cd19e5886d32f6.
Runtime claude-haiku-5-5, medium, prompt1.15; accepted labels unchanged.

One-shot validate_candidate5.py running, exec session54115. First batch200/200 recorded
(run20261122T192948_5707ce159e65); queue now understanding-2 (30 cases).
First batch known$0.518497, no unsettled run calls, one guardrail-blocked U0008.
Execution status remains incomplete despite full200 raw coverage. All60 flagged rows
and required original regressions have62 assistant records; summary reports0missing.
Snapshot: evidence/candidate5-first-batch-summary.json (not final matrix results). Read
 evidence/candidate5-primary-queue.json and *queue-log.txt before acting.
DO NOT rerun this queue or old finish_development.py. Every batch log is exclusive.
Pre-outcome matrix candidate5-batches.json: understanding200+30 fresh cases;
safety100+24 fresh contexts (89+18 cases); fifteen separate fixed-case invocations.
All352 cases exactly once, 369 total context/conversation rows. Fresh seeded worlds;
bootstrap rejects more than200 clients before transmission. Fixed cases dispatched
individually because their runner stops after its first incomplete conversation.
Failures stay in denominators. Raw coverage is not semantic acceptance.
No source or pinned harness edits while this queue runs.
Incremental primary assistant review is in evidence/candidate5-primary-assistant-review.jsonl
(raw-row hashes, human_reviewed=false, independent=false). All flags inspected through
all200 first-batch rows (through U1024), including original U0025/U0145/U0146/U0150/U1019 regressions.
Budget-normalization and empty-affordable-stock scorer applicability findings are retained;
U0137 over-budget recommendations remain a raw accepted-label failure despite soft wording. U0037 is a real false cheapest claim missed by
runtime pronoun association; U0008 initially false price claim and false-blocked repair;
Plavix catalog ambiguity prevents U0032 completion. These findings remain unresolved,
not acceptance. U0044/U0059 expose missed English lexical cues and actual first-reply
language failures; language-input diagnostic records35/72 English inputs without
confident inference (not35 observed response failures). Other reviewed flags include genuine scorer association/clarification
errors and language-quality concerns. Do not silently replace raw scores.
U0080 repeats the clear day-after-tomorrow→tomorrow error, including wrong-date cards
after the client repeats the intended day. evidence/candidate5-remediation-findings.json
records confirmed mechanisms for the next distinct candidate after this matrix
finishes, plus a fallback-path inspection risk that still needs scripted reproduction.
U0123 really creates only one group of a two-pharmacy basket while describing the full
plan. Repeated three-medicine both wording, ambiguous pack-duration claims and one
stray Devanagari glyph remain explicit quality findings. U1017 falsely implies app
reservation requires payment. U1019 honors cheapest preference but invents global
three-pharmacy/equal-price scope from five returned rows/28 total; keep this real failure. Prompt findings are recorded
separately; no runtime/prompt/source edits have been made during this matrix.
Free-only report helpers: summarize_validation.py verifies completed matrix/source,
coverage/costs and review gaps; exporter retains partial checkpoints and original
regressions even if unflagged. compare_simulations.py rejects duplicate seed/contender,
changed worlds/draws/source and excludes execution-incomplete pairs from seed estimates.
Six initial offline integrity scenarios passed. SIMULATION_METHODS.md prospectively adds
a separate full-world analysis retaining turn failures/caps, alongside strict completed
pairs; six secondary comparison and five raw-artifact fixture checks passed. These are
helper checks only; actual paired comparison remains unexecuted.
Browser fixture origin now explicitly matches localhost55173; configuration/isolated DB
target verified without connections or model calls. Two completed candidate5 pilot
archives passed privacy scan14files/0flags. Live journeys remain unverified.

## Diagnostic attempts retained, not pooled into primary results

Candidate1/2/3 pilots and all candidate4 raw runs remain append-only.
Candidate4 understanding 20261122T142220_8b5e802698ef:230 raw rows, but final30
U1025–U1054 reused earlier clients/chats and are contaminated. Valid first200 flags
have56 assistant-review records. Isolation plan retains evidence; obsolete candidate4
isolated-tail rerun was NOT executed. Candidate5 uses fresh bounded batches instead.
Candidate4 safety original20261122T151920_7e30b3b85ee2 exhausted200clients at100contexts;
continuation20261122T185706_649d44cb0ddf completed remaining24; explicit union107cases,
124contexts, no duplicates, one execution failureR1022. See coverage/plans.
Candidate4 fixed20261122T190243_4a27a43a3f69 attempted13/15:12completed, M0013 first
turn blocked, M0014–15 unexecuted. See candidate4-fixed-coverage.json. Do not call
this full coverage. These are superseded development diagnostics, never final acceptance.

## Budget and preservation

Canonical ledger ../architecture-20261118/budget.sqlite; caps baseline4/screening10/
expanded6/heldout3/retries2,total25. Never move calls, release unknown holds or reallocate.
Pre-primary audit passed:1131 historical evidence hashes and historical ledger rows
unchanged; unrelated handoff SHA256
0a3e0a09e2e04c1307aa3645d78e044b2ec3954bddb8f5cadc2dc3483b7aff13.
Known$3.201945;17 historical unknown holds$10.965; committed$14.166945;0active at
snapshot. Expandedused$1.101896, remaining$4.898104. Primary calls now change totals.
Audit: backend/.venv/bin/python eval/experiments/a-hardening-20261122/audit.py.
paid_v5 enforces source/harness pin, stage caps, STOP_PAID and stops new uncertainty.
Postgres55433/Mailpit58025 isolated. Ignored local.env/root.env credentials excluded.

## Next actions

1 Monitor queue; inspect every semantic/execution flag and all124 safety contexts.
  No overlapping DB tests/evaluators. Any partial raw coverage: preserve attempts,
  document only unexecuted continuation IDs before spending; never rerun failures.
2 Played up to50 as affordable. Review all flags and reproducible seed20261122 sample50
  or all completed fewer. Prepare export_review.py pack; label assistant review honestly.
3 Paired seed1/n100 agent/search/rules/rules_asking, same starting world/events. Free
  baselines via free_sim.py and paid A via paid_v5.py simulation. Verify comparability
  and cost, then expand2–5 only affordable. Report all requested metrics/uncertainty.
4 Eight live-model browser journeys remain unverified. live_browser.py and DEMO.md
  prepared only; update browser fixture to final source pin before starting. Sameledger,
  synthetic isolated infrastructure. No API/frontend running.
5 Heldout directory absent in prior metadata-only check; no semantic content opened.
  Independent owner/teammate review pending. No final heldout freeze/run until required
  review/development prerequisites resolve. Continue feasible independent work.
6 Finish REPORT.md, reproducible commands/hashes/costs/limitations/review pack/demo/seal.
  Report is currently a working draft, not final evidence or completed goal.
