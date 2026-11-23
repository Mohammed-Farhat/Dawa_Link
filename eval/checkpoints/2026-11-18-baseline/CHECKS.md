# Executed command inventory

All check.py commands use local.env, remove inherited paid/database keys, and run in the stated directory. Logs preserve stdout and stderr. Exit 0 on scorer-probes means probes executed; inspect their detected fields. Runtime exits reflect intentional shutdown.

| Evidence | Working directory | Exact command | Exit | Seconds |
|---|---|---|---:|---:|
| [api-runtime](evidence/api-runtime.txt) | backend | `uvicorn dawalink.api.main:create_app --factory --host 127.0.0.1 --port 58000 --no-access-log` | 0 | 169.494 |
| [backend-format](evidence/backend-format.txt) | backend | `ruff format --check .` | 0 | 0.755 |
| [backend-lint](evidence/backend-lint.txt) | backend | `ruff check .` | 0 | 0.754 |
| [backend-tests](evidence/backend-tests.txt) | backend | `pytest --junitxml=../eval/checkpoints/2026-11-18-baseline/evidence/backend-junit.xml` | 0 | 127.65 |
| [backend-types](evidence/backend-types.txt) | backend | `mypy` | 0 | 14.027 |
| [before-commit](evidence/before-commit.txt) | backend | `python -m dawalink.evals.before_commit` | 0 | 69.342 |
| [datasets](evidence/datasets.txt) | backend | `python -m dawalink.evals.validate` | 0 | 0.448 |
| [frontend-build-r2](evidence/frontend-build-r2.txt) | frontend | `npm run build` | 0 | 3.335 |
| [frontend-build](evidence/frontend-build.txt) | frontend | `npm run build` | 127 | 0.128 |
| [frontend-lint-r2](evidence/frontend-lint-r2.txt) | frontend | `npm run lint` | 0 | 0.653 |
| [frontend-lint](evidence/frontend-lint.txt) | frontend | `npm run lint` | 127 | 0.149 |
| [frontend-tests-r2](evidence/frontend-tests-r2.txt) | frontend | `npm test` | 0 | 8.2 |
| [frontend-tests](evidence/frontend-tests.txt) | frontend | `npm test` | 127 | 0.569 |
| [paired-free-smoke](evidence/paired-free-smoke.txt) | backend | `python ../eval/checkpoints/2026-11-18-baseline/free_sims.py` | 0 | 48.206 |
| [planner](evidence/planner.txt) | backend | `python -m dawalink.evals.plan_set` | 0 | 0.695 |
| [prepare](evidence/prepare.txt) | backend | `python ../eval/checkpoints/2026-11-18-baseline/prepare.py` | 0 | 10.048 |
| [privacy-scan](evidence/privacy-scan.txt) | backend | `python -m dawalink.evals.scan_results` | 0 | 12.471 |
| [runtime-probe](evidence/runtime-probe.txt) | backend | `python ../eval/checkpoints/2026-11-18-baseline/runtime_probe.py` | 0 | 0.483 |
| [scorer-probes-r2](evidence/scorer-probes-r2.txt) | backend | `python ../eval/checkpoints/2026-11-18-baseline/audit_probes.py` | 0 | 0.617 |
| [scorer-probes](evidence/scorer-probes.txt) | backend | `python ../eval/checkpoints/2026-11-18-baseline/audit_probes.py` | 1 | 0.087 |
| [web-runtime](evidence/web-runtime.txt) | frontend | `npm run dev -- --host 127.0.0.1 --port 55173 --strictPort` | -2 | 165.666 |

Setup commands (all output retained separately):

- `git status --short`; `git log -5 --oneline`; `git rev-parse HEAD`; `git switch -c test/agent-evaluation 1e17db0ea522622caaf8da41d60df4ef152ccec3`. Branch creation initially denied by filesystem sandbox, then succeeded with escalation.
- Backend `UV_CACHE_DIR=/tmp/dawalink-eval-uv uv sync --frozen`: first attempt exit 1 (DNS); retry exit 0.
- Frontend `PATH=/Users/ajkanaan/.nvm/versions/node/v24.21.0/bin:$PATH npm ci --cache /tmp/dawalink-eval-npm`: first attempt exit 1 (DNS); network retry exit 0; final clean install exit 0 after both earlier installers ended.
- `docker compose -f eval/checkpoints/2026-11-18-baseline/compose.yaml up -d --wait`: exit 0.
- Frontend `PATH=/Users/ajkanaan/.nvm/versions/node/v24.21.0/bin:$PATH npm audit --json --cache /tmp/dawalink-eval-npm`: exit 1, eight high-severity findings.
- `kill -INT 36302 36396`: stopped only this session's API and frontend.
- `docker compose -f eval/checkpoints/2026-11-18-baseline/compose.yaml stop`: exit 0; volume retained.
- `shasum -a 256 -c eval/checkpoints/2026-11-18-baseline/evidence/handoff.sha256`: OK.
- `git diff --exit-code`: exit 0 before report finalization; tracked implementation unchanged.
