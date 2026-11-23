# Executed commands and failure inventory

Run from repository root: `python3 eval/checkpoints/2026-11-18-reconciliation/check.py NEW-NAME backend|frontend COMMAND...`.

The wrapper strips inherited provider/database settings, loads only synthetic local.env, and refuses existing evidence files. Arguments below run in the indicated repository subdirectory. No command in this checkpoint supplied a paid provider key. Database/container commands require local sandbox permission. Each output starts with the exact directory and argument vector.

| Evidence | Directory | Exact argument vector | Exit | Seconds |
|---|---|---|---:|---:|
| [accounting-lint-r2](evidence/accounting-lint-r2.txt) | backend | `["ruff", "check", "."]` | 0 | 0.023 |
| [accounting-lint](evidence/accounting-lint.txt) | backend | `["ruff", "check", "src/dawalink/evals/budget.py", "tests/unit/evals/test_readiness.py"]` | 1 | 0.092 |
| [accounting-tests-r2](evidence/accounting-tests-r2.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 3.731 |
| [accounting-tests](evidence/accounting-tests.txt) | backend | `["pytest", "tests/unit/evals/test_readiness.py"]` | 0 | 2.957 |
| [accounting-types-r2](evidence/accounting-types-r2.txt) | backend | `["mypy"]` | 0 | 1.267 |
| [accounting-types](evidence/accounting-types.txt) | backend | `["mypy"]` | 0 | 1.387 |
| [actual-event-audit](evidence/actual-event-audit.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/audit_events.py"]` | 0 | 0.07 |
| [billing-inventory-command](evidence/billing-inventory-command.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/billing_inventory.py"]` | 0 | 0.115 |
| [browser-api-r2](evidence/browser-api-r2.txt) | backend | `["uvicorn", "--app-dir", "../eval/checkpoints/2026-11-18-reconciliation", "browser_fixture:make", "--factory", "--host", "127.0.0.1", "--port", "58000", "--no-access-log"]` | 3 | 1.943 |
| [browser-api-r3](evidence/browser-api-r3.txt) | backend | `["uvicorn", "--app-dir", "../eval/checkpoints/2026-11-18-reconciliation", "browser_fixture:make", "--factory", "--host", "127.0.0.1", "--port", "58000", "--no-access-log"]` | -15 | 1415.732 |
| [browser-api](evidence/browser-api.txt) | backend | `["uvicorn", "--app-dir", "../eval/checkpoints/2026-11-18-reconciliation", "browser_fixture:make", "--factory", "--host", "127.0.0.1", "--port", "58000", "--no-access-log"]` | -15 | 181.381 |
| [browser-init](evidence/browser-init.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/browser_fixture.py", "init"]` | 0 | 2.305 |
| [browser-phase-clarify](evidence/browser-phase-clarify.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/browser_fixture.py", "clarify"]` | 0 | 2.365 |
| [browser-phase-request](evidence/browser-phase-request.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/browser_fixture.py", "request"]` | 0 | 2.304 |
| [browser-phase-reserve](evidence/browser-phase-reserve.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/browser_fixture.py", "reserve"]` | 0 | 2.006 |
| [browser-timeout](evidence/browser-timeout.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/browser_fixture.py", "timeout"]` | 0 | 4.461 |
| [browser-web](evidence/browser-web.txt) | frontend | `["env", "VITE_API_URL=http://localhost:58000", "npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "55173", "--strictPort"]` | 143 | 1703.685 |
| [checkpoint-audit](evidence/checkpoint-audit.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/audit_checkpoint.py"]` | 0 | 0.299 |
| [evaluator-static](evidence/evaluator-static.txt) | backend | `["ruff", "check", "."]` | 0 | 0.024 |
| [evaluator-tests](evidence/evaluator-tests.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 3.926 |
| [evaluator-types](evidence/evaluator-types.txt) | backend | `["mypy"]` | 0 | 1.798 |
| [events-format](evidence/events-format.txt) | backend | `["ruff", "format", "src/dawalink/sim/engine.py", "src/dawalink/sim/run.py"]` | 0 | 0.046 |
| [events-lint](evidence/events-lint.txt) | backend | `["ruff", "check", "."]` | 0 | 0.021 |
| [events-rules-asking](evidence/events-rules-asking.txt) | backend | `["env", "EVAL_DATASET=reviewed", "python", "-m", "dawalink.evals.experiment", "simulation", "--contender", "rules_asking", "--seeds", "1", "--requests", "100", "--save"]` | 0 | 73.338 |
| [events-rules](evidence/events-rules.txt) | backend | `["env", "EVAL_DATASET=reviewed", "python", "-m", "dawalink.evals.experiment", "simulation", "--contender", "rules", "--seeds", "1", "--requests", "100", "--save"]` | 0 | 71.667 |
| [events-search](evidence/events-search.txt) | backend | `["env", "EVAL_DATASET=reviewed", "python", "-m", "dawalink.evals.experiment", "simulation", "--contender", "search", "--seeds", "1", "--requests", "100", "--save"]` | 0 | 79.005 |
| [events-tests](evidence/events-tests.txt) | backend | `["pytest", "tests/services/test_sim_engine.py", "tests/unit/test_sim_scenario.py", "tests/db/test_sim_world.py", "tests/unit/test_sim_rules.py", "-q"]` | 0 | 21.764 |
| [events-types](evidence/events-types.txt) | backend | `["mypy"]` | 0 | 1.626 |
| [final-backend](evidence/final-backend.txt) | backend | `["pytest", "--junitxml=../eval/checkpoints/2026-11-18-reconciliation/evidence/backend-final.xml"]` | 0 | 182.133 |
| [final-dispatch-free](evidence/final-dispatch-free.txt) | backend | `["env", "EVAL_DATASET=reviewed", "python", "-m", "dawalink.evals.experiment", "simulation", "--contender", "search", "--seeds", "1", "--requests", "1", "--save"]` | 0 | 19.059 |
| [final-dispatch-tests](evidence/final-dispatch-tests.txt) | backend | `["pytest", "tests/unit/evals/test_readiness.py", "tests/unit/evals/test_multiturn.py", "tests/unit/evals/test_grounding.py", "-q"]` | 0 | 3.241 |
| [final-dispatch-types](evidence/final-dispatch-types.txt) | backend | `["mypy"]` | 0 | 1.595 |
| [final-eval-tests](evidence/final-eval-tests.txt) | backend | `["pytest", "tests/unit/evals", "tests/agent/test_eval_conversations.py", "tests/agent/test_eval_multiturn.py", "-q"]` | 0 | 5.212 |
| [final-format-check](evidence/final-format-check.txt) | backend | `["ruff", "format", "--check", "."]` | 0 | 0.076 |
| [final-format](evidence/final-format.txt) | backend | `["ruff", "format", "src/dawalink/evals/run_multiturn.py", "src/dawalink/evals/experiment.py", "src/dawalink/evals/before_commit.py", "tests/unit/evals/test_multiturn.py"]` | 0 | 0.052 |
| [final-free-quick](evidence/final-free-quick.txt) | backend | `["python", "-m", "dawalink.evals.before_commit", "--skip-day"]` | 0 | 13.95 |
| [final-grounding-format](evidence/final-grounding-format.txt) | backend | `["ruff", "format", "src/dawalink/evals/grounding.py", "tests/unit/evals/test_grounding.py"]` | 0 | 0.052 |
| [final-grounding-static](evidence/final-grounding-static.txt) | backend | `["ruff", "check", "."]` | 0 | 0.098 |
| [final-grounding-tests](evidence/final-grounding-tests.txt) | backend | `["pytest", "tests/unit/evals/test_grounding.py", "-q"]` | 0 | 3.645 |
| [final-grounding-types](evidence/final-grounding-types.txt) | backend | `["mypy"]` | 0 | 1.962 |
| [final-lint](evidence/final-lint.txt) | backend | `["ruff", "check", "."]` | 0 | 0.024 |
| [final-types](evidence/final-types.txt) | backend | `["mypy"]` | 0 | 1.74 |
| [format-clean](evidence/format-clean.txt) | backend | `["ruff", "format", "--check", "."]` | 0 | 0.057 |
| [free-gate](evidence/free-gate.txt) | backend | `["python", "-m", "dawalink.evals.before_commit"]` | 0 | 59.318 |
| [freeze-format-fix](evidence/freeze-format-fix.txt) | backend | `["ruff", "format", "src/dawalink/evals/experiment.py"]` | 0 | 0.048 |
| [freeze-format](evidence/freeze-format.txt) | backend | `["ruff", "format", "--check", "."]` | 1 | 0.061 |
| [freeze-static](evidence/freeze-static.txt) | backend | `["ruff", "check", "."]` | 0 | 0.063 |
| [frontend-build](evidence/frontend-build.txt) | frontend | `["npm", "run", "build"]` | 0 | 7.862 |
| [frontend-lint](evidence/frontend-lint.txt) | frontend | `["npm", "run", "lint"]` | 0 | 0.419 |
| [full-backend](evidence/full-backend.txt) | backend | `["pytest", "--junitxml=../eval/checkpoints/2026-11-18-reconciliation/evidence/backend.xml"]` | 0 | 116.838 |
| [full-frontend](evidence/full-frontend.txt) | frontend | `["npm", "test"]` | 0 | 8.787 |
| [grounding-static](evidence/grounding-static.txt) | backend | `["ruff", "check", "."]` | 0 | 0.034 |
| [grounding-tests-r2](evidence/grounding-tests-r2.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 4.296 |
| [grounding-tests](evidence/grounding-tests.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 4.783 |
| [grounding-types](evidence/grounding-types.txt) | backend | `["mypy"]` | 0 | 1.756 |
| [isolated-start](evidence/isolated-start.txt) | backend | `["docker", "compose", "-f", "../eval/checkpoints/2026-11-18-baseline/compose.yaml", "up", "-d", "--wait"]` | 0 | 16.048 |
| [isolated-status-final](evidence/isolated-status-final.txt) | backend | `["docker", "compose", "-f", "../eval/checkpoints/2026-11-18-baseline/compose.yaml", "ps", "-a", "--format", "json"]` | 0 | 0.138 |
| [isolated-stop-final](evidence/isolated-stop-final.txt) | backend | `["docker", "compose", "-f", "../eval/checkpoints/2026-11-18-baseline/compose.yaml", "stop"]` | 0 | 0.851 |
| [logout-fixed](evidence/logout-fixed.txt) | frontend | `["npm", "test", "--", "--run", "src/features/client/ClientExtras.test.tsx", "-t", "Logging"]` | 0 | 1.783 |
| [logout-reproduction](evidence/logout-reproduction.txt) | frontend | `["npm", "test", "--", "--run", "src/features/client/ClientExtras.test.tsx", "-t", "Logging"]` | 1 | 4.773 |
| [multiturn-format-r2](evidence/multiturn-format-r2.txt) | backend | `["ruff", "format", "src/dawalink/evals/run_multiturn.py", "src/dawalink/evals/experiment.py"]` | 0 | 0.016 |
| [multiturn-format-r3](evidence/multiturn-format-r3.txt) | backend | `["ruff", "format", "src/dawalink/evals/run_understanding.py", "tests/unit/evals/test_multiturn.py"]` | 0 | 0.016 |
| [multiturn-format-r4](evidence/multiturn-format-r4.txt) | backend | `["ruff", "format", "tests/agent/test_eval_multiturn.py"]` | 0 | 0.014 |
| [multiturn-format](evidence/multiturn-format.txt) | backend | `["ruff", "check", "--select", "I", "--fix", "src/dawalink/evals/run_multiturn.py"]` | 0 | 0.075 |
| [multiturn-integration](evidence/multiturn-integration.txt) | backend | `["pytest", "tests/agent/test_eval_multiturn.py", "tests/unit/evals/test_multiturn.py", "-q"]` | 0 | 3.603 |
| [multiturn-static-r2](evidence/multiturn-static-r2.txt) | backend | `["ruff", "check", "--fix", "src/dawalink/evals/run_multiturn.py", "tests/unit/evals/test_multiturn.py", "tests/agent/test_eval_multiturn.py"]` | 1 | 0.072 |
| [multiturn-static](evidence/multiturn-static.txt) | backend | `["ruff", "check", "--fix", "src/dawalink/evals/run_multiturn.py", "tests/unit/evals/test_multiturn.py"]` | 0 | 0.057 |
| [multiturn-tests](evidence/multiturn-tests.txt) | backend | `["pytest", "tests/unit/evals", "-q"]` | 0 | 6.784 |
| [multiturn-types-r2](evidence/multiturn-types-r2.txt) | backend | `["mypy"]` | 1 | 2.489 |
| [multiturn-types-r3](evidence/multiturn-types-r3.txt) | backend | `["mypy"]` | 1 | 1.962 |
| [multiturn-types](evidence/multiturn-types.txt) | backend | `["mypy"]` | 1 | 3.5 |
| [p95-static](evidence/p95-static.txt) | backend | `["ruff", "check", "."]` | 0 | 0.063 |
| [p95-tests](evidence/p95-tests.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 3.677 |
| [paired-rules-asking](evidence/paired-rules-asking.txt) | backend | `["python", "-m", "dawalink.evals.experiment", "simulation", "--contender", "rules_asking", "--seeds", "1", "--requests", "100", "--save"]` | 0 | 60.042 |
| [paired-rules](evidence/paired-rules.txt) | backend | `["python", "-m", "dawalink.evals.experiment", "simulation", "--contender", "rules", "--seeds", "1", "--requests", "100", "--save"]` | 0 | 58.02 |
| [paired-search](evidence/paired-search.txt) | backend | `["python", "-m", "dawalink.evals.experiment", "simulation", "--contender", "search", "--seeds", "1", "--requests", "100", "--save"]` | 0 | 76.157 |
| [preservation](evidence/preservation.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/verify_preservation.py"]` | 0 | 0.136 |
| [provenance-format-r2](evidence/provenance-format-r2.txt) | backend | `["ruff", "format", "src/dawalink/sim/save.py", "src/dawalink/sim/run.py", "src/dawalink/evals/experiment.py", "tests/unit/evals/test_readiness.py"]` | 0 | 0.014 |
| [provenance-format](evidence/provenance-format.txt) | backend | `["ruff", "check", "--select", "I", "--fix", "src/dawalink/sim/save.py", "tests/unit/evals/test_readiness.py"]` | 0 | 0.058 |
| [provenance-lint](evidence/provenance-lint.txt) | backend | `["ruff", "check", "."]` | 0 | 0.022 |
| [provenance-tests](evidence/provenance-tests.txt) | backend | `["pytest", "tests/unit/evals", "-q"]` | 0 | 3.884 |
| [provenance-types](evidence/provenance-types.txt) | backend | `["mypy"]` | 0 | 1.792 |
| [review-static](evidence/review-static.txt) | backend | `["ruff", "check", "."]` | 1 | 0.022 |
| [review-tests](evidence/review-tests.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 4.352 |
| [review-types](evidence/review-types.txt) | backend | `["mypy"]` | 0 | 1.71 |
| [reviewed-case-freeze](evidence/reviewed-case-freeze.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/freeze_cases.py"]` | 0 | 2.657 |
| [reviewed-entrypoint-no-key](evidence/reviewed-entrypoint-no-key.txt) | backend | `["env", "EVAL_DATASET=reviewed", "python", "-m", "dawalink.evals.experiment", "multiturn", "--model", "claude-haiku-5-5", "--effort", "medium", "--max-usd", "0.01", "--limit", "1"]` | 1 | 2.851 |
| [safety-separation](evidence/safety-separation.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 3.913 |
| [seal-final](evidence/seal-final.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-reconciliation/seal_final.py"]` | 0 | 0.606 |
| [static-clean](evidence/static-clean.txt) | backend | `["ruff", "check", "."]` | 0 | 0.072 |

## Nonzero outcomes

Nonzero commands are retained below, including expected negative controls and intentional server shutdowns. Intermediate failures were fixed and later successful checks are also indexed. See REPORT.md for unresolved gaps.

- [accounting-lint](evidence/accounting-lint.txt): exit 1.
- [browser-api-r2](evidence/browser-api-r2.txt): exit 3.
- [browser-api-r3](evidence/browser-api-r3.txt): exit -15.
- [browser-api](evidence/browser-api.txt): exit -15.
- [browser-web](evidence/browser-web.txt): exit 143.
- [freeze-format](evidence/freeze-format.txt): exit 1.
- [logout-reproduction](evidence/logout-reproduction.txt): exit 1.
- [multiturn-static-r2](evidence/multiturn-static-r2.txt): exit 1.
- [multiturn-types-r2](evidence/multiturn-types-r2.txt): exit 1.
- [multiturn-types-r3](evidence/multiturn-types-r3.txt): exit 1.
- [multiturn-types](evidence/multiturn-types.txt): exit 1.
- [review-static](evidence/review-static.txt): exit 1.
- [reviewed-entrypoint-no-key](evidence/reviewed-entrypoint-no-key.txt): exit 1.

The logout reproduction intentionally failed before the fix; 204/503 regressions then passed. Browser API/frontend SIGTERM exits -15/143 are intentional cleanup. browser-api-r2 exited 3 because the prior server still held the port; the subsequent restart succeeded. reviewed-entrypoint-no-key deliberately refused missing credentials and saved an incomplete run with no new calls. Its import double-load warning was subsequently fixed and the free dispatch run passed.

## Outputs without completed wrapper metadata

- [development-label-audit](evidence/development-label-audit.txt): `cwd: backend` / `command: ["python", "../eval/checkpoints/2026-11-18-reconciliation/review_development.py"]`.

Missing metadata is not silently treated as an executed pass. The development-label-audit report was written successfully but the original wrapper then collided with that report filename, leaving no completed wrapper metadata. The report and command output are preserved. Metadata now uses .command.json. Initial account/lint/type/format failures and every retry remain saved.

Native Safari operations are recorded in [browser-journeys.md](evidence/browser-journeys.md); they were UI actions rather than shell commands. The fixture/clock commands appear in the table. No provider billing reconciliation or paid rerun was executed.

Sealing commands, from repository root: `python3 eval/checkpoints/2026-11-18-reconciliation/index_checks.py` writes this new index and evidence-hashes.json exclusively. The source script is preserved. Existing checkpoint files and result folders are not rewritten.
