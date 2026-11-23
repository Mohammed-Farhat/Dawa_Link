# Executed command index

Run from repository root: `python3 eval/checkpoints/2026-11-18-readiness/check.py NEW-NAME backend|frontend COMMAND...`.

The wrapper sets synthetic isolated settings, strips inherited service/database keys, and refuses existing evidence names. Paid commands additionally use paid.py, which reads only the ignored Anthropic key. Do not rerun paid commands until billing holds are reconciled.

| Evidence | Working directory | Exact argument vector | Exit | Seconds |
|---|---|---|---:|---:|
| [baseline-pilot](evidence/baseline-pilot.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/paid.py", "understanding", "--model", "claude-haiku-5-5", "--effort", "medium", "--max-usd", "4", "--limit", "5"]` | 0 | 77.686 |
| [browser-api](evidence/browser-api.txt) | backend | `["uvicorn", "--app-dir", "../eval/checkpoints/2026-11-18-readiness", "browser_app:make", "--factory", "--host", "127.0.0.1", "--port", "58000", "--no-access-log"]` | -15 | 1231.102 |
| [browser-web](evidence/browser-web.txt) | frontend | `["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "55173", "--strictPort"]` | 143 | 1227.499 |
| [card-analysis](evidence/card-analysis.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/analyze_cards.py"]` | 0 | 0.05 |
| [challenge-validation](evidence/challenge-validation.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/validate_challenges.py"]` | 0 | 0.535 |
| [checks-final](evidence/checks-final.txt) | backend | `["python", "-m", "dawalink.evals.before_commit"]` | 0 | 70.867 |
| [final-scorers](evidence/final-scorers.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 4.319 |
| [final-types](evidence/final-types.txt) | backend | `["mypy"]` | 0 | 1.76 |
| [format-final](evidence/format-final.txt) | backend | `["ruff", "format", "--check", "."]` | 0 | 0.023 |
| [free-regression](evidence/free-regression.txt) | backend | `["python", "-m", "dawalink.evals.before_commit"]` | 0 | 77.499 |
| [frontend-build](evidence/frontend-build.txt) | frontend | `["npm", "run", "build"]` | 0 | 3.691 |
| [frontend-checks](evidence/frontend-checks.txt) | frontend | `["npm", "test"]` | 0 | 9.975 |
| [frontend-lint-final](evidence/frontend-lint-final.txt) | frontend | `["npm", "run", "lint"]` | 0 | 0.437 |
| [frontend-types-final](evidence/frontend-types-final.txt) | frontend | `["npm", "run", "typecheck"]` | 0 | 2.62 |
| [full-suite-final](evidence/full-suite-final.txt) | backend | `["pytest", "--junitxml=../eval/checkpoints/2026-11-18-readiness/evidence/backend-final.xml"]` | 0 | 142.92 |
| [full-suite](evidence/full-suite.txt) | backend | `["pytest", "--junitxml=../eval/checkpoints/2026-11-18-readiness/evidence/backend.xml"]` | 0 | 126.225 |
| [inspect-order-r2](evidence/inspect-order-r2.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/inspect_order.py"]` | 0 | 0.369 |
| [inspect-order](evidence/inspect-order.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/inspect_order.py"]` | 1 | 0.389 |
| [isolated-stop](evidence/isolated-stop.txt) | backend | `["docker", "compose", "-f", "../eval/checkpoints/2026-11-18-baseline/compose.yaml", "stop"]` | 0 | 0.79 |
| [lint](evidence/lint.txt) | backend | `["ruff", "check", "."]` | 0 | 0.021 |
| [paired-free](evidence/paired-free.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/paired_free.py"]` | 0 | 181.376 |
| [partial-review-r2](evidence/partial-review-r2.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/review_partial.py"]` | 0 | 0.024 |
| [provider-availability](evidence/provider-availability.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/provider_check.py"]` | 0 | 1.502 |
| [report-tests](evidence/report-tests.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 4.345 |
| [residual-audit-command](evidence/residual-audit-command.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/final_audit.py"]` | 0 | 1.717 |
| [safety-challenge](evidence/safety-challenge.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/paid.py", "safety", "--model", "claude-haiku-5-5", "--effort", "medium", "--max-usd", "4"]` | 0 | 67.232 |
| [safety-dev](evidence/safety-dev.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/paid.py", "safety", "--model", "claude-haiku-5-5", "--effort", "medium", "--max-usd", "4"]` | 0 | 80.995 |
| [scorer-suite](evidence/scorer-suite.txt) | backend | `["pytest", "tests/unit/evals"]` | 0 | 3.415 |
| [static-final](evidence/static-final.txt) | backend | `["ruff", "check", "."]` | 0 | 0.059 |
| [types-final-r2](evidence/types-final-r2.txt) | backend | `["mypy"]` | 0 | 1.404 |
| [types-final](evidence/types-final.txt) | backend | `["mypy"]` | 1 | 1.647 |
| [types](evidence/types.txt) | backend | `["mypy"]` | 0 | 1.46 |
| [understanding-challenge](evidence/understanding-challenge.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/paid.py", "understanding", "--model", "claude-haiku-5-5", "--effort", "medium", "--max-usd", "4"]` | 0 | 113.662 |
| [understanding-dev](evidence/understanding-dev.txt) | backend | `["python", "../eval/checkpoints/2026-11-18-readiness/paid.py", "understanding", "--model", "claude-haiku-5-5", "--effort", "medium", "--max-usd", "4"]` | 0 | 90.47 |

A zero shell exit for a paid runner does not mean a complete evaluation. The four larger paid runs have completion.json status incomplete.

Earlier failed attempts without wrapper metadata are retained in scorers-first.txt, types-first.txt, types-r2.txt, collection.txt and partial-review.txt. The first partial review produced its JSON correctly but collided with the wrapper metadata filename; partial-review-r2 uses separate output and metadata names. Nothing was overwritten.

The temporary browser API/web exits (-15 and 143) are intentional SIGTERM shutdowns
at checkpoint end, not failed journey assertions. Compose stop exited 0; subsequent
`docker compose -f eval/checkpoints/2026-11-18-baseline/compose.yaml ps -a --format json`
confirmed both evaluation containers exited 0 and the PostgreSQL volume remains.

Additional sealing command, from repository root:
`python3 eval/checkpoints/2026-11-18-readiness/seal_checkpoint.py` exited 0.
It verifies the handoff checksum, unchanged reference agent/frontend/historical
results, clean diff whitespace, ignored-key file mode and absence of the actual
Anthropic key in experiment/checkpoint outputs; saves a consistent ledger backup
and SHA-256 hashes for every immutable run file. It does not call a provider.
