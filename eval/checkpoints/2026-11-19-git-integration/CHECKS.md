# Integration check commands

From repository root, use `python3 eval/checkpoints/2026-11-19-git-integration/check.py NEW-NAME backend|frontend COMMAND...`. Only synthetic ignored local.env is loaded, provider keys stripped, output files exclusive. No paid evaluations.

| Evidence | Directory | Exact argument vector | Exit | Seconds |
|---|---|---|---:|---:|
| [backend-format](evidence/backend-format.txt) | backend | `["ruff", "format", "--check", "."]` | 0 | 0.018 |
| [backend-static](evidence/backend-static.txt) | backend | `["ruff", "check", "."]` | 0 | 0.108 |
| [backend-tests](evidence/backend-tests.txt) | backend | `["pytest", "--junitxml=../eval/checkpoints/2026-11-19-git-integration/evidence/backend.xml"]` | 0 | 145.264 |
| [backend-types](evidence/backend-types.txt) | backend | `["mypy"]` | 0 | 8.612 |
| [free-gate](evidence/free-gate.txt) | backend | `["python", "-m", "dawalink.evals.before_commit"]` | 0 | 75.856 |
| [frontend-build](evidence/frontend-build.txt) | frontend | `["npm", "run", "build"]` | 0 | 10.047 |
| [frontend-lint](evidence/frontend-lint.txt) | frontend | `["npm", "run", "lint"]` | 0 | 0.662 |
| [frontend-tests](evidence/frontend-tests.txt) | frontend | `["npm", "test"]` | 0 | 11.26 |
| [isolated-start](evidence/isolated-start.txt) | backend | `["docker", "compose", "-f", "../eval/checkpoints/2026-11-18-baseline/compose.yaml", "up", "-d", "--wait"]` | 0 | 16.033 |
| [isolated-stop](evidence/isolated-stop.txt) | backend | `["docker", "compose", "-f", "../eval/checkpoints/2026-11-18-baseline/compose.yaml", "stop"]` | 0 | 0.704 |
| [publication-audit](evidence/publication-audit.txt) | backend | `["python", "../eval/checkpoints/2026-11-19-git-integration/audit_publication.py"]` | 0 | 0.428 |
| [publication-final](evidence/publication-final.txt) | backend | `["python", "../eval/checkpoints/2026-11-19-git-integration/audit_publication.py", "--final"]` | 0 | 0.56 |

Git operations in order (repository root):

1. `git fetch origin --prune` (first approval timed out; one retry succeeded).
2. Separate `git add -- <explicit paths>` and commits: `Fix logout session state`; `Harden evaluation scoring and budget tracking`; `Save baseline evidence and readiness findings`.
3. `git merge --no-ff --no-commit origin/main` reported two conflicts (exit 1). Resolved SessionProvider and simulation/database.py; staged only the resolutions. Other upstream changes retained.
4. After tests, `git fetch origin --prune` confirmed `origin/main` still at `28cf4f1`. `git diff --check -- backend frontend docs .gitignore` and its cached form passed; `git diff --name-only --diff-filter=U` is empty. Raw terminal evidence retains its original whitespace.
5. `python3 eval/checkpoints/2026-11-19-git-integration/seal.py` indexes these results and verifies all 209 earlier checkpoint artifact hashes without rewriting them.
6. Final merge commit: `git commit -m 'Merge main into evaluation branch'`. Publication uses `git push --set-upstream origin test/agent-evaluation`; no force or main push. Confirm with `git ls-remote origin refs/heads/test/agent-evaluation refs/heads/main` and local status/log.

Initial staged whitespace scan flagged only unchanged captured terminal whitespace. Those outputs were preserved, and source checks were scoped explicitly. No failed tests or scoring controls were suppressed. Browser journeys were not repeated; prior browser findings are historical.
