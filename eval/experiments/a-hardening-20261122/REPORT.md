# DawaLink A hardening and evaluation handoff

**Candidate6 is implemented and passes offline verification. Final model evaluation
is incomplete.** Paid work stopped after a new uncertain provider charge. There is no
independent acceptance, held-out evaluation or live-model browser verification.

## Decision and preservation

Retain A/current: neither B nor C met the original advancement rule. Original
assistant-reviewed quality was A111/120, B91/120, C106/120; successful execution was
120/118/111. C-minus-A's paired interval spans zero (-10.83 to +2.50 percentage points),
with provider incidents confounding reliability attribution. Original A met saved-span
latency targets (cards p95 14.08s; answers7.06s). This supports retaining the default,
not general superiority or readiness of the repaired candidate.

The original architecture source/evidence is separately preserved at bdc5c16 and in
its sealed report: ../architecture-20261119/revised-20261120/REPORT.md. All1481 original
sealed hashes were checked before repairs; the latest audit checks1131 historical
non-runtime evidence files and unchanged historical ledger rows. B/C remain available
for reproduction. No reset, clean, push, deployment or main merge was performed.
The unrelated untracked handoff document remains untouched.

## Candidate6 changes and verification

Runtime source snapshot:468971f5df8dc113089ffad22376b0420df0e2cb; promptv1.16.
candidate6-source-pin.json records244 source/configuration hashes, the accepted-case
freeze and claude-haiku-5-5/medium settings. It is not a held-out freeze or paid
execution authorization. Runtime and scorer repairs are separately committed.

Repairs cover false card/action claims; price/travel/expiry comparison association and
scope; explicit nearest/cheapest recommendations; language continuity; per-pack budget
and pickup-date constraints; and safe fallback cards, including refusal before the
first candidate reply. Code-owned relative pickup dates survive clarification without
being reinterpreted against a newer clock. Plan provenance detects omitted displayed
pharmacy-group cards; clearly labeled partial plans remain allowed.

Prompt corrections address complete basket workflows, whole-basket and entire-route
totals, dose sufficiency versus expiry eligibility, counter payment, ownership during
cancellation/escalation, fixed FIFO, pharmacist consultation and unconfigured emergency
contacts. These prompt changes have not been validated with the live model.

Separate scorer repairs include contextual clarification variants, search-intent
prefaces, genuine professional consultation, conditional pharmacy stock, FIFO tense,
currency-preserving client budgets, split-basket totals, exact same-product differences,
and demonstrable walking-nearest choices. A verified correct empty budget search makes
the card check inapplicable (null), not successful. Wrong constraints, malformed results
and provider failures cannot receive that exception. No accepted labels were changed.
Ambiguous implicit comparison peers and price association still require semantic review.

Integrated checks: **2320 tests passed**, Ruff check/format passed (356 files), mypy
passed (352 files). There were2297 test warnings; no test failure. Detailed immutable
logs/hashes: evidence/candidate6-integrated-checks.json. Targeted counts overlap and
must not be summed. Offline replay rejected U0037's false cheapest and U1019's global
scope claims while accepting U0008's corrected nearest comparison; original outcomes
remain unchanged. Passing scripted tests is not live-model or independent acceptance. The accepted-data
free gates also passed:200 exact planner rankings, valid dataset/catalog references,
no privacy flags across289 saved results and unchanged133/241 rules-day baseline.

## Development coverage and review

Accepted freeze:352 distinct cases (230 understanding,107 safety,15 fixed
conversations), representing369 configured contexts/conversations. Latest paid primary
attempts describe candidate5/prompt1.15, not candidate6:

| Suite | Recorded | Execution | Missing |
|---|---:|---|---:|
| Understanding |230 cases|229 OK; U0008 blocked|0|
| Safety |89 cases /100 contexts|99 OK; R1036 request provider fallback|18 cases /24 contexts|
| Fixed conversations |0|Not executed|15|

Total319/352 cases and330/369 planned rows. Known primary usage$0.755891 plus one
uncertain$0.645 hold. Both incomplete manifests and failures remain visible. Candidate4
runs are historical diagnostics: its last30 understanding cases reused chats, and its
fixed run completed12 of15. They are not pooled into candidate5 primary results.
Candidate6 has no new paid development attempts and no measured live performance rate.

All100 recorded candidate5 safety contexts and all required understanding flags/original
regressions have177 implementation-assistant review records. Every record explicitly
sets human_reviewed=false and independent=false. The owner/teammate pack is
review-pack-20261123/ with177 selected records, exact raw pointers/hashes and blank
independent verdicts. Privacy scans found0 flags across the pack and three primary runs.
No candidate5 model-played conversations completed: the seeded sample is0, not50.
Fresh candidate6 development/model-played evaluation and independent review remain due.

## Product outcomes

All three free contenders finished the same seed1 world (100 requests,241 wanted
units). Pairwise audits confirm identical initial inputs/source/arrivals and matching
shared keyed draws; different action-dependent keys are permitted by the protocol.

| Contender | Secured units | Fully served | Interactions | Failed turns | API USD |
|---|---:|---:|---:|---:|---:|
| Search |177/241|62/100|338|0|0|
| Rules |133/241|43/100|318|66|0|
| Rules asking |124/241|39/100|358|100|0|

Search is strictly complete. Rules and rules_asking completed the world but their
language-guard failures leave execution incomplete; retain them only in the predefined
full-world analysis, separately from strict completed pairs. Simulated minutes to fully
secure a request (median/p95, among fulfilled requests) were search0/53, rules25/49,
and rules_asking27/65. Turn latency was not captured for these free contenders and is
unavailable; simulated fulfillment time is not measured response latency. API cost per
fulfilled request is0 for each free contender.

Run IDs and all comparability checks: evidence/candidate6-free-baselines.json. The first
search setup failed before creating a world (wrong working directory), is archived
separately, and contributes no product outcomes. The paid A100-request seed was not
executed; no A-minus-baseline effect or cross-world uncertainty interval is available.
No optional seed expansion or stress sweep was attempted. SIMULATION_METHODS.md
predefines the analyses. Six-hour secured units are locks, not proof of dispensing;
model assumptions are not real pharmacy behavior.

## Spending and concrete pending matrix

Canonical ledger:../architecture-20261118/budget.sqlite. Latest audited known usage
$3.957847;18 unresolved holds$11.610000; committed$15.567847; active reservations0.
Original17 holds$10.965 remain unchanged. New uncertain call:
21cc867d64e947db9e32ffcfd2920f55 (expanded,$0.645), run20261122T202552_ed1956da4231.
STOP_PAID remains armed. Remaining room does not authorize overriding the stop.

Approved ceilings remain baseline4, screening10, expanded6, heldout3, retries2 USD,
aggregate25. Expanded committed$2.502798; room$3.497202. No holds were released,
stages moved, ledger reset or ceilings reallocated. API totals come from the ledger,
not token estimates. New free attempts cost0; failed setup attempts stay archived.

After the stop is explicitly resolved, the reduced prospective matrix is:

| Work | Target | Condition |
|---|---|---|
| Repaired A development |352 cases /369 rows|Fresh bounded worlds, new candidate pin, all original outcomes retained|
| Primary paired A simulation |Seed1,100 requests|Priority over optional seeds; stop at the applicable cost ceiling|
| Model-played conversations |As many as affordable, up to50|Review all if fewer than50; report exact count|
| Live browser |8 synthetic journeys|Same ledger; no scripted replacement|
| Extra seeds2–5 / stress sweeps |Deferred|Only after measured primary costs leave room|
| Held-out |One final run, allocation3|Suitable provenance plus resolved development and independent review before freeze|

Previous cost estimates for development (~1.25), A seed (~1.5–3), browser (~0.20) and
played50 (~0.75) total$3.70–5.20, exceeding current expanded room by$0.202798–1.702798
before conservative reservation headroom. They are estimates, not guaranteed quotes.
The exact decisions are whether attributable billing evidence resolves the new hold,
or revised authorization permits future paid work while retaining it; and whether to
keep expanded6 with explicit partial coverage or approve revised stage ceilings within
an agreed aggregate ceiling. No such revision has been assumed. New uncertainty must
never be silently grandfathered into a candidate pin.

## Held-out, demo and restart

Configured eval/heldout is absent in the latest metadata-only check; no held-out
semantic contents were opened. Final freeze and held-out scoring were not performed.
Independent review, suitable held-out provenance and resolved development regressions
remain prerequisites, not assistant-completed tasks.

DEMO.md prepares clarification, proposal, approval, reservation, pickup, cancellation,
unavailable stock and sourcing timeout on isolated synthetic accounts/infrastructure.
All eight live-model journeys remain unverified under STOP_PAID. Older scripted UI
results are supporting evidence only. The browser factory now uses the candidate6
reproduction pin and rejects STOP_PAID before loading settings, credentials or a model;
a no-API check confirms this. Source-drift and per-call unknown-charge protections remain active.
This preparation is not permission to launch paid work.

REPRODUCE.md provides exact offline checks, free-baseline commands and restart limits.
Do not restart the terminal candidate5 queue or use its paid harness against candidate6.
Keep original raw attempts, unknown charges, source snapshots and synthetic clock facts.
No production deployment or merge is part of this handoff.
