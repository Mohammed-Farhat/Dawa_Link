# Shared harness repairs (all contenders)

- Fixed-case selection now applies before limits in understanding/safety/fixed conversations.
  The managed runner computes expected coverage using the same selection. Unknown/duplicate
  IDs fail before any model transmission. Imported-by-value dataset paths are refreshed for
  modules already loaded by dataset validation.
- Stage is explicit (baseline/screening/expanded), replacing the hard-coded baseline.
  Architecture/repetition/smoke metadata and source archives remain per unique run.
- Per-call accounting records purpose, architecture, effort and request hash, alongside the
  existing usage/failure metadata. Extraction/verifier/correction/client/retry calls use the
  same model wrapper and originating stage. Caps changed to owner-authorized $6/$6/$8/$3/$2.
- Full backend check initially: 2124 pass, one privacy-test failure. Exact text `1990` appeared
  only in a trace timer fraction (0.02894829199067317), not a prompt or tool payload. The test
  now excludes only the known trace/span timing fields from the birth-date string scan.
  All input/output/metadata payloads remain checked. Its script also supplies the existing
  guard's expected second reply and requires completion, instead of passing after a script
  exhaustion. Application guards and the reference behavior were not changed by this repair.

Original failed evidence is retained. A clean full rerun follows. These repairs apply to A,
B and C alike; no historical scores were overwritten or relabeled as fresh measurements.

Smoke-discovered repairs, before comparative screening:
- B's first extraction trace emitted bare argument objects instead of the shared
  `{name, arguments}` tool-call schema. The scorer raised KeyError after one paid call.
  The trace emitter now preserves that schema; a scripted end-to-end trace/scorer test
  covers it. Run `20261119T153712_8ad1f4d45e3f` remains incomplete ($0.000288, screening).
- `plan_basket` places its total on the parent plan and the pharmacy inside `groups`.
  Grounding now associates a single-group plan total with its pharmacy. Negative controls
  reject changed totals, wrong pharmacies, assigning basket totals to individual products,
  and assigning multi-pharmacy totals to one pharmacy. The earlier A smoke's U-0123 and
  U-1040 totals match actual tools; flags were scorer errors, not invented prices.
- U-0014's “Which one do you need?” followed by 5mg/10mg choices is a semantic clarification
  that the narrow question regex misses. This remains a manually reviewed scorer limitation;
  the regex was not loosened from a paid example.

Repaired-contract verification: 366 scripted/unit agent/evaluator checks pass (see command
log for exact count), plus Ruff/mypy. All three architectures receive fresh smoke runs on
this same repaired harness. Earlier smoke evidence is retained and excluded from screening.

Final synthetic-client correction:
- A clear Arabic request for missing duration without `?`/`؟` was not recognized as a
  question, so the scripted client stopped rather than supplying its remaining truth.
  Added explicit `بدي أعرف/اعرف` request wording and sentence-initial `خبرني/أخبرني`.
  Negative controls retain declarative “the pharmacist told me” as statements.
- Old C smoke's U-1040 is a harness-induced conversation truncation, not evidence that
  the agent would ignore a duration answer it never received. The strength question in
  U-0014 remains a manually reviewed regex limitation.
- Final screening uses the same fixed correction for every architecture. Sample/targets
  unchanged. Earlier A 30-case run is retained and excluded for source/harness drift.
