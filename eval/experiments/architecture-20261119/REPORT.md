# DawaLink architecture comparison — incomplete development screening

**Recommendation: retain A/current. No challenger is advanced.** B and C are implemented,
but provider failures and conservative unresolved reservations prevented the required paired
screening. These results do not establish A as the best architecture or support replacing it.
No expansion, held-out evaluation, deployment, push or main merge occurred.

## Implementation and reference

The owner accepted completed main as the reference. Branch `test/agent-evaluation` remains at
`8e689a583b69a399598f557ac8a2310571c1dbb1`, containing remote main
`28cf4f1d3f8412eff3ee7a10ffb9eb40102f1313`. `reference.json` and
`reference-agent.tar.gz` preserve its original source; historical results are not measurements
of this reference. Existing work and the handoff document were preserved.

- **A/current:** reference behavior, prompts, tools, guards and original repair loop. It remains
  the default; internal `DAWALINK_ARCHITECTURE` selects contenders without changing public APIs.
- **B/staged:** a read-only structured extraction captures cumulative explicit facts,
  corrections and removed medicines; unknown fields remain null. Code detects missing
  logistics and clarifies, otherwise the existing guarded workflow resolves catalog ambiguity
  and creates proposals. Extraction has no executable business tools. First-turn routing can
  defer needed strength clarification; strict extraction schemas can reject model mistakes.
- **C/verified:** A plus a read-only review of draft/cards against reference application rules,
  redacted facts/context and tool results. One correction shares the original repair allowance,
  then existing output checks apply. The reviewer cannot execute business tools.

All contenders/auxiliary stages use `claude-haiku-5-5`, medium effort and existing limits.
Chat and worker paths are supported. Backend stock, expiry, ownership, queue priority and
client-approval authority remain intact. Original prompt/tool/guard files are unchanged;
only the turn orchestration adds architecture branches. B and C are independent.

## Data and fixed protocol

The owner-approved, AI-assisted freeze accepts **352 cases: 230 understanding, 107 safety,
15 fixed conversations**. Nine direct user adjudications and 135 delegated AI adjudications
retain their actual origin; they are not 144 human checks. Twenty-two exclusions remain
with reasons. The default actual-human gate remains available. See
`../../development-v2/freeze.json` and `PROTOCOL.md`.

`screening.json` fixes seed 20261119 and 60 IDs: 30 understanding, 20 safety, 10 conversations,
balanced across English/Arabic/Arabizi/mixed and difficult behaviors. A proportional draft
that omitted mixed safety was rejected before scoring and retained. `targets.json` freezes
docs/08 targets before comparative scores. Sample, accepted labels and targets did not change.

The existing runner now records architecture, stage, fixed IDs, repetition, source/prompt/data
hashes, unique immutable runs, raw outcomes and completion. Final source eligibility is pinned
by `screening-source-freeze.json`. Shared trace, grounding and Arabic synthetic-client repairs
are documented in `HARNESS_REPAIRS.md`; all final smokes and screening use that common source.
Earlier smokes/calibration and one earlier-source A comparison remain excluded and fully charged.

The intended order was A/B/C then C/B/A. After B's fixed-conversation batch failed at M-0014,
its existing fail-fast behavior skipped M-0015. Before any C comparative scores, the execution
plan was changed to run each fixed conversation independently for every architecture/repetition,
with identical first synthetic client, clock, seed and case-specific shelves. This source-free
partition repair is explicit in `coverage-repair.json`. The prior A/B batched conversation runs
are ancillary, with both successes and failures retained. **None of the planned individual
conversation invocations started before the external block.**

## Verification and completed coverage

- Clean full backend run: **2131 passed**. After final common harness/verifier-context changes,
  **563 focused agent/evaluator tests passed**, plus Ruff lint/format and mypy on 340 files.
- Scripted checks cover reference compatibility, corrections/removals/unknowns, missing facts,
  read-only tools, wrong-draft correction, errors/deadlines, ownership/approval boundaries,
  worker routing, shared traces and spending accounting. Evidence commands/results are retained.
- Free evaluation gate passed: exact planner check, accepted dataset validation, privacy scan
  clear across 289 files; rules seed 1 served 133/241 units, with no no-shows or expiry-fit failures.
  This rules result is a free-gate check, not A/B/C paid fulfillment.
- No frontend/shared public behavior changed; frontend checks were not rerun.
- Five-case final smokes completed for every architecture and remain separate from comparison:
  A $0.013994, B $0.016317, C $0.037238. Earlier failed/calibration smokes are also retained.
- Primary screening saved **130 case observations**: A 30 understanding +20 safety; B the same;
  C 30 understanding attempts. Safety has 24 chat/request observations per20 cases, so these
  are 138 raw rows. **230 of 360 planned paired case observations remain missing.** No repetition 2
  ran; C safety and all normalized fixed conversations remain unrun.
- Ancillary batched conversations: A 10 complete; B 8 complete plus 1 failed, with its last case
  unattempted. All 19 saved attempts /55 exchanges were inspected, including all 18 complete
  conversations (fewer than50 available).

The integrity audit passed while explicitly marking screening incomplete. It verifies source,
sample/target/data hashes, exact available IDs, all new accounting events, budget limits and
**all 81 original ledger entries unchanged**. See `evidence/final-integrity-audit.json`.

## Observed results — first repetition only

All applicable checks must pass for a case. Raw and reviewed scores are separate; no aggregate
ranking combines architectures with different suite coverage.

| Understanding: same 30 cases | A/current | B/staged | C/verified |
|---|---:|---:|---:|
| Raw all-check passes | 27/30 | 19/30 | 21/30 |
| Reviewed all-check passes | 27/30 | 20/30 | 24/30 |
| Executed successfully | 30/30 | 30/30 | 26/30 |
| Unnecessary questions, successful applicable cases | 0/23 | 2/23 | 0/19 |
| Paid API attempts | 136 | 156 | 211 |
| Known usage | $0.077808 | $0.082713 | $0.193495 |
| Additional unresolved reservation | $0 | $0 | $5.160000 |

C's four unavailable cases occurred during the provider incident, including reservation-headroom
exhaustion. They count as failed attempts, but do not establish architecture-specific product or
safety failures. On the 26 cases outside that incident, reviewed quality was A 23/26, B 16/26,
C 24/26: a post-incident diagnostic subset, not a promotion result. Repetition2 and C's adversarial
safety coverage are absent. Differences are inconclusive; exploratory case-bootstrap output is
retained in `final-summary.json` but is not used as final inference or simulation-seed evidence.

For the 20 safety cases, A had 19 raw/20 reviewed passes; B 18 raw/18 reviewed passes, including
one schema-rejection execution failure and one missing first-come explanation. No actual unsafe
advice, unauthorized state change, priority change or data disclosure was confirmed in reviewed
A/B observations. **C's safety suite was not run; safety equivalence is unestablished.**

Selected reviewed checks (pass/applicable; first understanding pass only):

| Check | A | B | C |
|---|---:|---:|---:|
| Product identification/evidence | 25/25 | 23/25 | 21/25 |
| Quantity | 25/25 | 22/23 | 21/21 |
| Complete executable choice | 23/23 | 22/23 | 18/19 |
| Budget | 4/4 | 4/4 | 3/4 |
| Required strength clarification | 4/4 | 0/4 | 4/4 |
| Clinical refusal | 3/3 | 3/3 | 3/3 |
| Language | 27/30 | 30/30 | 26/26 |
| Explicit cheapest preference | 0/1 | 0/1 | 0/1 |

Denominators follow check applicability and therefore vary. In particular, some checks have
no value for empty provider-failed replies; those cases still fail the overall case score.
C's low product/budget counts include external execution failures. B's two clinical product
failures lack catalog-resolved evidence, rather than demonstrating a wrong proposed medicine.
Small conditional check rates are not full-development constraint accuracy or safety proof.

Instrumented successful understanding-turn latency (seconds):

| Metric | A | B | C |
|---|---:|---:|---:|
| All-turn p50 /p95 | 5.758 /12.159 | 3.921 /17.692 | 14.609 /25.361 |
| Card-turn p50 /p95 | 8.954 /12.742 | 13.484 /17.940 | 20.601 /28.668 |
| Answer-turn p95 | 6.141 | 5.010 | 17.472 |

These are recorded generation/tool span durations, excluding load/save overhead, with failed
turns excluded. They are not end-to-end SLA proof. B/C card p95 and C answer p95 exceed the frozen
15s/8s targets even on this limited measure. B's cheap deterministic questions did not translate
into cheaper card turns or lower measured understanding cost. C often reviews and corrects a
single answer; some reviewer criticisms concern harmless defaults, subset counts or phrasing.

### Representative findings and scorer limits

- B U-1002 reads Arabizi `3elbe` (a box, accepted quantity1) as three boxes; actual cards have qty3.
  B also defers strength questions in four ambiguity cases and re-asks already supplied facts.
- B's worker R-0012 extraction adds an unsupported item field; ancillary M-0014 returns a nested
  `facts` wrapper. Strict decoding produces bounded empty fallbacks, with no business tools.
- A U-0050/U-0091 reply in English to Arabizi. A U-0150 switches to French. Ancillary A M-0010
  contains duplicate text and a raw placeholder. These are confirmed semantic quality failures.
- All three miss U-0150's explicit cheapest/far-is-okay preference. C's read-only review does not
  fix it. C U-1040 produces separate single-medicine cards instead of a complete grouped basket
  choice; both medicines exist at one pharmacy, but the accepted proposal-completeness check fails.
- Narrow clarification regexes miss genuine strength questions. Basket/quantity totals and
  current cards from prior turns produce grounding/notes false positives. Generic Arabic
  “the only pharmacy” is misread as a pharmacy name. A refusal to share instructions is not a leak.
- Raw Latin-script checks miss English-for-Arabizi and some French. Mixed-language cases allow
  English/Arabic/Arabizi; a single loanword is not treated as a French response.

Every saved safety/semantic flag and all 29 primary tool/card/check/outcome disagreements were
inspected; ancillary conversation differences were also inspected. Decisions, exact case/run
references and attribution are in `evidence/manual-adjudications.jsonl`,
`manual-review-coverage.jsonl` and `disagreement-review.json`. Review was by the implementation
assistant, **not human, independent or blind**. The operational semantic rubric was documented
during A's first review, after sample/targets were frozen; this and AI-assisted labels limit
independence. Original outcomes and scores were never overwritten.

## Spending and external blocker

The single canonical ledger remains `../architecture-20261118/budget.sqlite`.
All workflow/correction/retry, extraction and verifier attempts enter it. Across this task there
were 1205 new attempts: 989 workflow, 140 extraction, 76 verification; no model-played client calls.
1197 new attempts settled; eight remain uncertain. SDK retries are disabled; reference-agent
retries are individually reserved and charged to their originating stage.

| Stage | Ceiling | Known usage | Unresolved holds | Committed |
|---|---:|---:|---:|---:|
| Baseline, including history | $6 | $0.093178 | $3.870000 | $3.963178 |
| Screening | $6 | $0.764849 | $5.160000 | $5.924849 |
| Expanded | $8 | $0 | $0 | $0 |
| Held-out | $3 | $0 | $0 | $0 |
| Retry reserve | $2 | $0 | $0 | $0 |
| **Aggregate** | **$25** | **$0.858027** | **$9.030000** | **$9.888027** |

Historical known usage was $0.045449; this task added $0.812578. Known usage derives from
provider-reported tokens and the recorded pricing schedule, rounded up per call; it is not an
independently reconciled invoice. Unknown holds are conservative commitments, not established
charges. App trace totals may differ slightly through rounding.

During C's understanding suite, a 30-second API timeout was followed by connection errors. The
reference retry loop and subsequent cases accumulated eight unknown charges, each held at $0.645.
The suite saved its outcomes; the outer orchestrator then stopped before another suite.
A later single unauthenticated HTTP HEAD received 404 from the endpoint. That establishes later
reachability, not whether earlier requests were billed. No attributable evidence permits releasing
those holds. The original six uncertain holds remain unchanged.

Screening has only $0.075151 uncommitted headroom, below the next $0.645 reservation. No remaining
paid screening can fit its ceiling, despite aggregate headroom. No other stage was borrowed.
`STOP_SCREENING` prevents accidental comparison restart; `evidence/provider-incident.json`
records the exact uncertain calls and sanitized failures. No further generation was attempted.

## Decision, omissions and exact next conditions

Keep A as the default pending trustworthy paired evidence. B shows observed quality regressions
and no understanding-cost saving. C has some improved language/catalog wording, but misses other
quality checks, costs more, takes longer and lacks adversarial/second-pass evidence. The provider
incident prevents a fair replacement claim. **No challenger earned expansion.**

Not run: remaining screening, fresh full 352-case suites for A/challenger, paired simulation seeds 1–5
with 100 requests each, model-played conversations, inventory/pharmacy-response stress or held-out.
Consequently six-hour fulfillment, fully served requests, simulation constraint accuracy, real
cost per successful request and seed-paired confidence intervals are **unmeasured**. Offline
quality-passing cases are not successful reservations. These omissions reflect the external
blocker; they are not successful zero-cost results.

Before any paid resume, obtain attributable billing evidence to reconcile specific unknown calls,
or an explicit owner revision of stage ceilings within the $25 aggregate. Preserve all holds until
then; do not reset, move calls or borrow held-out/retry allocations. Recalculate remaining coverage
cost and ensure the next reservation fits. `PROGRESS.md` identifies the next command and immutable
plans; any resumed C understanding evidence must keep the provider-failed original run separate.
Complete paired screening and its reviews before selecting a challenger. A final improvement claim
still requires full accepted development runs, then the prioritized paired simulations and other
feasible coverage. Address observed language/clarification/completeness regressions, clarify scorer
limits and verify operational billing/availability before a separately authorized held-out task.

Shutdown verification is recorded in PROGRESS.md; the evaluation volume and all evidence are retained.
