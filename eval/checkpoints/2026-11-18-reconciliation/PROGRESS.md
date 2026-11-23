# Resume checkpoint — pre-architecture reconciliation

Status: feasible independent free work complete; architecture gate remains closed.
Paused at user request and explicitly resumed on 2026-11-18. No active test jobs.
Read REPORT.md, CHECKS.md and PROTOCOL.md before further work.

Branch: test/agent-evaluation. Reference HEAD/agent/prompts:
1e17db0ea522622caaf8da41d60df4ef152ccec3. No architecture changes, held-out reads,
commits, staging, push, merge or deployment. Original handoff/datasets, historical
results, earlier checkpoints and partial runs preserved. Repairs are uncommitted.

Completed: provider-boundary usage/failure accounting; audited billing adjustments;
shared retries/client ledger; final-card quantities and choice grouping; product/
pharmacy/currency price grounding; semantic review candidates; execution/safety
separation; nearest-rank p95; exclusive writers; template provenance and raw
completion checks; actual world/event/draw audit. Original agent unchanged.
Logout fixed separately with failed reproduction and passing 204/503 regressions.
Native Safari pickup, cancellation, unavailable-stock and sourcing-timeout journeys
verified using synthetic accounts and ScriptedModel.

Checks: full backend 1,986 passed; frontend 153 passed; frontend lint/build/types
passed. Latest event addition: 92 simulation tests passed; mypy 325 files, lint and
format passed. Free gate: exact planner, valid datasets, 289 historical files clean,
rules 133/241, zero no-shows/expiry violations.

Final free seed-1 / 100-request runs, all complete, 241 units wanted:
- search 20261118T173120_8802618a6095: 177 secured, 62 fully served.
- rules 20261118T173119_c88ce825ede3: 133 secured, 43 fully served.
- rules_asking 20261118T173119_bde18996e9e1: 133 secured, 43 fully served.
Code/world/stock/schedules/timing identical; 180 actual arrivals match, all applied.
Shared draws match (105/105/547 across pairs). Conditional event sets differ with
actions. One seed, no paid current-agent simulation; no quality victory.
See evidence/event-audit-findings.json. Earlier runs preserved.

Reviewed development copies frozen: 210 understanding + 100 safety cases; corrected
U-1012 language and 12 safety no-state-change checks. Added 8 fixed conversations /
24 turns. Use EVAL_DATASET=reviewed and reconciliation-freeze.json. Same-session
review only; independent label agreement outstanding. New cases are Concor-heavy,
adversarial coverage English-heavy. No held-out cases opened.

Canonical ledger: eval/experiments/architecture-20261118/budget.sqlite.
81 call rows unchanged: 75 settled, usage-derived $0.045449; six uncertain calls
retain $3.87; committed $3.915449 of $4 baseline. $3.87 is a reservation, not a
confirmed charge. Next $0.645 reservation cannot fit. No additional paid calls,
unsupported release, reset or allocation borrowing. Additive call_events intended.

External blocker: attributable billing/usage evidence for six uncertain calls
(IDs/times in evidence/billing-inventory.json). Do not repeatedly request it.
Verify attribution before audited reconciliation. Only if spending permits: fresh
original-agent baseline on frozen reviewed cases/settings/worlds; review all safety/
semantic flags and 50 reproducibly sampled conversations. Earlier 35 rows/all
8 flags reviewed: flags were failed/blank executions, not safety passes or proven
violations. Language switching and blanket prescription claim remain real findings.

Cleanup: browser API/frontend stopped; isolated PostgreSQL/Mailpit stopped, exit 0.
Volumes and browser DB dawalink_sim_browser_reconciliation_1811 retained.
Restart only isolated compose.yaml if needed; never source root .env for free
checks. check.py loads synthetic local.env and refuses used evidence names.

Final evidence: final-integrity-v2.json verifies 35 old run files, original agent/
prompts/handoff, ledger calls, source/input/all-run hashes, exact configured-key scan.
Two privacy candidates are timestamp false positives. CHECKS.md records commands/
nonzero outcomes; evidence-hashes.json seals this checkpoint. Do not rerun exporters
against existing outputs. See REPORT.md/PROTOCOL.md for limits and acceptance gates.
