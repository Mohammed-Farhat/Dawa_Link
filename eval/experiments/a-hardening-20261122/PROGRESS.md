# A hardening checkpoint — 2026-11-23

All currently feasible independent work is finished. **Final validation is incomplete.**
No process is running. STOP_PAID remains armed; do not restart candidate5 or make paid
calls until the new uncertain charge is explicitly resolved. Preserve the checkout;
never reset/clean, push, deploy or merge main. Unrelated handoff document untouched.

## Six-stage status

1. **Preservation complete.** Original architecture source/evidence separately committed
   at bdc5c16; A retained, B/C reproducible. Final audit verifies1131 historical evidence
   files and unchanged historical ledger rows. Original full1481-hash check preceded
   repairs. Historical source remains in commit/run archives.
2. **Offline hardening complete; live behavior pending.** Candidate6 source468971f5df8dc113089ffad22376b0420df0e2cb,
   prompt1.16, Haiku5.5/medium. Runtime and scorer changes separately committed;
   accepted labels unchanged. Source/config hashes244 in candidate6-source-pin.json,
   SHA167eff82698b99a9bf46f1743ccf7905137e02ff998e35291048e3942fa90200.
   This is reproduction-only, not final held-out freeze or paid authorization.
3. **Development partial.** Candidate5/prompt1.15 recorded319/352 cases,330/369 contexts:
   understanding230 (229OK/U0008 blocked), safety89/107 cases and100/124 contexts
   (99OK/R1036 provider fallback), fixed0/15. No candidate6 paid results. All100
   recorded safety contexts plus flags/regressions have177 assistant reviews; none
   independently accepted. review-pack-20261123 has177 raw-linked blank verdicts.
   Played sample0 because no candidate5 model-played run completed. Fresh repaired-A
   coverage and independent review remain due; do not pool diagnostic attempts.
4. **Free baselines complete; A comparison pending.** Same seed1/100-request world:
   search177/241 units,62 fully served,338 interactions,0 failed turns;
   rules133/241,43 served,318 interactions,66 failures;
   rules_asking124/241,39 served,358 interactions,100 failures. Both rules variants
   have full-world coverage but incomplete guarded execution. Shared inputs/source,
   arrivals and common keyed draws match. No A effect or across-seed interval exists.
   Simulated fulfillment median/p95 minutes:0/53,25/49,27/65 respectively; free turn
   latency unavailable. All API costs0. No optional seeds/stress loops.
5. **Held-out prerequisite missing.** Metadata-only check:eval/heldout absent; no semantic
   content opened. Resolve development/independent findings and suitable provenance,
   then freeze source/prompt/model/scorer/protocol/targets before opening content.
6. **Report/reproduction/demo preparation complete; live journeys pending.** REPORT.md,
   REPRODUCE.md, DEMO.md and SIMULATION_METHODS.md contain exact outcomes/limits.
   Browser factory updated to candidate6 pin; verified STOP rejects before settings,
   credentials/model creation. All8 live journeys remain unverified; same ledger required.

## Verification (no repeated full suites)

2320 backend tests passed in159.36s (2297 warnings); Ruff356 files, mypy352 passed.
Integrated evidence: evidence/candidate6-integrated-checks.json. Stale pre-correction
lint log retained separately; current corrected log passes. Targeted tests overlap.
Accepted-data free gates passed:200 exact planner rankings; valid datasets/catalog;
289 saved results without privacy flags; rules-day133/241 matches recorded baseline.
Final source/budget/held-out audit: evidence/candidate6-final-free-audit.json.
Archive audit covers21 terminal runs; two scanner flags adjudicated by the assistant
as ISO timestamp fractions, originals unchanged; no unadjudicated flags or unexpected
source archive members. Review pack + primary-run scan:0 flags/24 text files.

## Exact saved primary baseline attempts

- Failed search setup (root cwd, no world):20261123T103601_db0bd2765cea.
- Search:20261123T103631_2ac7e04cd1aa.
- Rules:20261123T103757_1b18dc237c7c.
- Rules asking:20261123T103927_d6e420d1b625.

Recompute archived comparability from root (choose a nonexistent output path):
`python3 eval/experiments/a-hardening-20261122/free_baseline_audit.py /tmp/dawalink-free-baselines.json 20261123T103631_2ac7e04cd1aa 20261123T103757_1b18dc237c7c 20261123T103927_d6e420d1b625`
Exact offline/full-suite and fresh free-run commands are in REPRODUCE.md; don't rerun
unchanged suites or existing attempts. Backend cwd is required for relative catalog paths.

## Accounting and next external decisions

Known$3.957847;18 unresolved holds$11.61; committed$15.567847; active reservations0.
Original17 holds$10.965 retained. New expanded hold$0.645:
21cc867d64e947db9e32ffcfd2920f55, run20261122T202552_ed1956da4231 (R1036 request).
It is not silently added to the old17 allowlist. Canonical budget.sqlite unchanged in
meaning; no hold released, stage reallocated or new paid call during this resume.
Caps remain baseline4/screening10/expanded6/heldout3/retries2, aggregate25 USD.
Expanded room$3.497202; reduced matrix estimate$3.70–5.20 before reservation headroom.

Next: owner supplies attributable billing evidence or explicitly authorizes future
paid work retaining the new hold; choose expanded6 with partial coverage or revised
stage ceilings within an agreed aggregate. Concrete matrix in REPORT.md prioritizes
fresh352-case development and first100-request A seed, then affordable played/live
journeys; optional seeds2–5/stresses deferred. Obtain owner/teammate review using the
pack and suitable held-out provenance. These are external prerequisites, not completed
validation. No paid runner may bypass STOP/new-uncertain guards.
