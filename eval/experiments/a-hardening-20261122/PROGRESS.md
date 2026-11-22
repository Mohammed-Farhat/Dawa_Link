# A hardening checkpoint — 22 November 2026

Goal active. Work sequentially on test/agent-evaluation; preserve checkout. No push,
deployment or main merge. Unrelated handoff remains untracked and unchanged.

## Candidate6 free repairs in progress

Language repair implemented: expanded high-confidence English cues; opaque Q request
references excluded from Arabizi inference; current client language hint overrides stale
notes in loaded context while short corrections inherit. Unit grounding/language and
DB context suites passed, Ruff/format and mypy2files passed. Exact evidence and hashes:
evidence/candidate6-language-checks.json. No live-model validation, no final pin yet.
Remaining consolidated runtime/scorer repairs and integrated tests still required.

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

## Candidate5 evaluation stopped — paid work prohibited

validate_candidate5.py session54115 is terminal exit1. Do not restart it. STOP_PAID
is armed after new provider uncertainty; do not remove it or grandfather the new hold
into an allowed pin. No paid work until attributable billing evidence or an explicit
revised authorization resolves this stop. Free repairs/tests/reports can continue.

Primary source a6c231c, claude-haiku-5-5 medium, prompt1.15. Pin SHA256:
fb8da0d66a6147e393f6b1e2608d3c9d91f792e8866196107757b7dd384a86c1.
Accepted freeze SHA256:
9e8f67f313643d6721d8667ce7ea57f8dbea61c438702c0479cd19e5886d32f6.
Labels unchanged; source/harness stayed pinned during all calls.

Completed planned batches (original attempts, never replay):
- understanding200 run20261122T192948_5707ce159e65:199 execution-ok, U0008 blocked;
  full200 raw coverage but execution status incomplete, known$0.518497.
- understanding30 run20261122T201634_194d38a24db9:30 execution-ok, known$0.110528.
- safety100contexts/89cases run20261122T202552_ed1956da4231:99 execution-ok,
  R1036 request fallback after generation31.061s/LLMRejected, known$0.126866 plus
  one uncertain$0.645 hold (call21cc867d64e947db9e32ffcfd2920f55).
Total319/352 distinct cases,330/369 planned rows. Unexecuted18 safety cases/24contexts
and all15 fixed conversations. Queue stops before these batches; they are not failures
or completed coverage. Raw failed outcomes stay in denominators.

All230 understanding flags/original regressions and all100 safety contexts have explicit
implementation-assistant records (human_reviewed=false, independent=false), with raw
row hashes. evidence/candidate5-stopped-primary-summary.json reports0missing required
reviews. This does not establish semantic/independent acceptance. Earlier partial
snapshots remain historical, including one then-pendingU1054 review.

Confirmed next repairs: comparison subject/peer context and universal scope; missed
English cues; explicit relative pickup dates; hard-budget cards; complete baskets;
unsupported payment/foreign-cancellation promises, missing FIFO/pharmacist referrals,
wrong route-leg wording and unconfigured emergency contacts. Details and counterexamples:
evidence/candidate5-remediation-findings.json and primary-assistant-review.jsonl.
R1036 initial FIFO reply is explicit and changedfalse; raw false priority predicates
are execution-failure scores, not proof that priority changed. Scorer false positives
and false negatives remain distinct from real agent defects. Garbled Arabizi and catalog
limits remain visible. No tuning on held-out content.

Next source may now change only as a distinct candidate. Keep runtime and scorer commits
separate. Central fallback-card suppression is now repaired for preference/budget/pickup
constraints, including refusal before the first candidate reply; see candidate6 checks. Candidate5 affected tests517 passed previously;
new integrated changes justify one full backend run after targeted checks.

Offline helpers: summarize_validation.py checks coverage/accounting/review gaps;
export_review.py retains all safety/fixed/flags/original regressions and seeded played
sample. compare_simulations.py/SIMULATION_METHODS.md prospectively separate strict
complete pairs from full-world outcomes retaining turn failures. Six initial/six secondary
comparison checks and five raw-artifact fixture checks passed; no actual paired run yet.
Browser fixture isolated origin/DB config verified only. Live journeys remain unverified.

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
Latest evidence/candidate5-paid-stop-audit.json passes1131 historical evidence hashes
and historical ledger-row preservation. Known$3.957847;18 uncertain holds$11.610000;
committed$15.567847;0active reservations. Expandedknown$1.857798,
committed$2.502798, remaining$3.497202. Paid stop still applies despite available room.
Old17 holds$10.965 stay unchanged; new$0.645 uncertainty is separately identified above.
Unrelated handoff remains untracked SHA256:
0a3e0a09e2e04c1307aa3645d78e044b2ec3954bddb8f5cadc2dc3483b7aff13.
Postgres55433/Mailpit58025 isolated. Ignored local.env/root.env credentials excluded.
No evaluation process remains live; DB tests may now run sequentially.

## Next actions

1 Continue distinct A repairs (language partial done) plus positive/incorrect regressions; separate
  scorer repairs without label changes. Targeted checks, then one integrated fullbackend.
2 Run free search/rules/rules_asking seed1 n100 after final source, same initial worlds/
  events and source. Record paid A/played/browser as pending while STOP_PAID remains.
3 Prepare independent-review pack from all existing raw outcomes, clearly partial.
  Owner/teammate acceptance is pending; assistant review cannot replace it.
4 Heldout directory absent in metadata-only check; no contents opened. Final freeze/run
  needs suitable provenance, resolved development regressions and independent review.
5 Update report/reproduction/hashes/costs/demo/handoff with all limitations. No push,
  deployment or main merge. Do not mark goal complete while feasible free work remains.

## Candidate6 partial card/date/budget repair

167 targeted tests passed: tests/agent/test_cards.py tests/agent/test_context.py
and tests/unit/agent/{test_pickup,test_budget,test_grounding}.py (from backend after
sourcing isolated local.env). Ruff check/format12 files and mypy7 source files passed.
Commands/results/source hashes: evidence/candidate6-card-constraints-checks.json,
with raw test/lint/type logs alongside it. No paid calls; STOP_PAID remains armed.

Central fallback checks now prevent rejected cards reappearing after model refusal,
including refusal before a first candidate reply. Valid fallback cards remain usable.
Per-pack budget cards use explicit client cap/revision before model notes and the
configured USD rate; missing rate cannot establish affordability. Relative pickup days
are anchored to current Beirut date in code-owned state, survive clarification/model
note conflicts and expire after their date. Ambiguous dates/budget totals remain review
work. Clear French switches use the existing French detector before inheriting Arabizi.
No live-model or independent acceptance claimed. Next: comparison association/scope,
basket/prompt repairs, then separate scorer work and integrated checks.
