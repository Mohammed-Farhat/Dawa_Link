# Development-v2 implementation and handoff

Status: **draft; human acceptance pending**. Development material only. No agent outputs,
performance scores, API evaluations, commits, pushes or held-out cases were used.

The version contains 234 understanding, 124 safety and 16 fixed conversations (374 total).
All 318 original cases remain byte-identical prefixes of their new files. Historical
freezes/results/hashes are unchanged. The 56 additions meet the requested language,
category, family and conversation-length distribution. See COVERAGE.md and coverage.json.

The fixed evaluation clock remains Monday 2026-11-16, 10:00 Beirut; authoring occurred
2026-11-19. provenance.json pins the local catalog snapshot, reference date, rule commit,
source hashes and relevant prompt/guard/state files. Catalog checks use the local CSV
snapshot, not live database contents or available stock. Understanding labels describe
facts; the runner's logistics clarification policy remains separate from `gold.expected`.
No stock-failure scenarios or new runner capabilities were added.

## Review completed

A separate Codex session labeled the seed-20261119 stratified blind sample: 47
understanding, 25 safety and four conversations. It saved all 76 decisions before seeing
proposed labels, then reviewed the remaining 298 cases. Outputs and hashes are saved.
This is **separate-session AI review with human checking pending**.

Exact normalized comparison found 62 field differences across 60 blind cases.
`review/agreement.json` records agreement by field and suite before adjudication. Some
field differences reflect implicit versus omitted medicine forms, so these numbers are
not semantic error rates. Additional findings include ambiguous times, medicine forms,
budget scope and safety checks with insufficient fixtures or incompatible clarification
behavior. Human review must resolve these; the author has not accepted AI findings as truth.

There are **106 flagged cases plus 38 reproducibly sampled otherwise agreed cases**:
144 human checks required, zero completed. Each case's original label, reviewer decision,
and field differences are in review/human-review-pack.jsonl. Pending final decisions,
reasons and human identities remain null in review/adjudication.jsonl. All draft cases are
excluded from scored use; exclusions.json records the unresolved queue.

## Human handoff and freeze

1. Review all 144 entries in review/human-review-pack.jsonl. Copy
   review/human-checks.template.jsonl to review/human-checks.jsonl and complete every row:
   `human_reviewed: true`, reviewer identity, `decision: "include"` or `"exclude"`, and reason.
2. For corrected expectations, populate `final_label` with `{"gold": ...}` for understanding,
   `{"checks": [...]}` for safety, or `{"turns": [{"gold": ..., "behavior": ...}, ...]}` for
   conversations. Turn texts are preserved. Null final_label explicitly retains the original
   label when the human selects include. Exclude cases whose ambiguity cannot be resolved
   within the existing schema/runner. Do not rewrite blind decisions.
3. Recheck any drift in the pinned product rules or prompt/guard/state files after the
   teammate's agent commit is frozen. Re-review affected cases in a new version if sources
   changed. Particular dependencies: clarification before search; corrections/removal in
   search versus active-request changes requiring taps; budget per-pack semantics; proposal
   cards versus actual reservation; clinical referral plus logistics; privacy/priority setups.
4. Run validation, then `python -m dawalink.evals.development_review freeze` from backend.
   The gate requires complete saved AI review and actual human decisions. It emits a
   separate scored subset, final adjudication, exclusions, and a hash freeze without
   modifying this draft or historical freezes. It refuses a second freeze.

Internal `EVAL_DATASET=expanded` selects all three adjudicated suites, including the fixed
multi-turn file. Before freeze it raises an error before run-directory, ledger, model or
database setup. `select_dataset("expanded", allow_draft=True)` is for offline inspection.
Existing development/challenge/reviewed selections retain their paths and behavior.
Public application APIs are unchanged. Paid evaluations remain unauthorized.

## Validation

Run from backend using the existing virtual environment (no network/package setup):

```bash
.venv/bin/python -m dawalink.evals.development_review validate
.venv/bin/python -m pytest tests/unit/evals/test_development_review.py tests/unit/evals/test_datasets.py tests/unit/evals/test_score_understanding.py tests/unit/evals/test_score_safety.py tests/unit/evals/test_multiturn.py
.venv/bin/ruff check src/dawalink/evals/development_review.py src/dawalink/evals/dataset_selection.py src/dawalink/evals/experiment.py tests/unit/evals/test_development_review.py
.venv/bin/mypy src/dawalink/evals/development_review.py src/dawalink/evals/dataset_selection.py src/dawalink/evals/experiment.py tests/unit/evals/test_development_review.py
```

Focused tests: 74 passed. Catalog/schema/count validation: zero errors. Ruff and mypy pass on all changed Python files. Tests exercise deliberately stale
quantities, budgets, dates and preferences; removed-item proposals; missing clarification;
forbidden state changes; legacy selector paths; draft and changed-freeze rejection.

Known scorer limits remain explicit: situation notes match topic words rather than full
transport semantics; safety still_helps counts lookups/cards rather than clarification
alone; budget labels do not represent total-versus-per-pack scope. Human review must
exclude or resolve affected cases. No accuracy or agent-success claim follows from this work.
