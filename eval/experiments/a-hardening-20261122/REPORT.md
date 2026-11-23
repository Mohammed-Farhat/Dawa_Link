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
remain unchanged. Passing scripted tests is not live-model or independent acceptance.

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

The free seed1 search/rules/rules_asking runs are being recorded separately. Their
final metrics and comparability audit will be added after terminal completion.
The paid A100-request seed was not executed; therefore no A-minus-baseline effect or
cross-world reliability estimate is available. No optional seed expansion or stress
sweep was attempted. SIMULATION_METHODS.md predefines strict complete pairs and a
separate full-world analysis retaining execution failures. Six-hour secured units are
locks, not proof of dispensing; model assumptions are not real pharmacy behavior.

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
results are supporting evidence only. The current browser factory still requires a
candidate-specific update after authorization; it rejects source drift and paid stop.

REPRODUCE.md provides exact offline checks, free-baseline commands and restart limits.
Do not restart the terminal candidate5 queue or use its paid harness against candidate6.
Keep original raw attempts, unknown charges, source snapshots and synthetic clock facts.
No production deployment or merge is part of this handoff.
