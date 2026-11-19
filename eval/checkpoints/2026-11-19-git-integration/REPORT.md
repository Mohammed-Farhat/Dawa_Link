# Evaluation branch integration — 19 November 2026

Publication follow-up: collaborator access was granted (push=true), and the normal
push of test/agent-evaluation succeeded. Remote verification returned
25be69889a7cb55dbd6ea36e2a3d035b3d3cdc48 for the test branch and unchanged
28cf4f1d3f8412eff3ee7a10ffb9eb40102f1313 for main. The 403 recorded below is
historical and resolved. This documentation follow-up adds no source changes.

User authorized committing the completed work, merging current main into
`test/agent-evaluation`, and pushing only that branch. Main itself stays unchanged.
No paid evaluation, architecture experiment or deployment is part of this task.

Local changes were committed before integration:

- `2f85474` — Fix logout session state
- `9c52a8d` — Harden evaluation scoring and budget tracking
- `8db6a10` — Save baseline evidence and readiness findings

Fetched main: `28cf4f1`, six commits after the original `1e17db0` reference. Incoming
work includes client/admin changes, three migrations, inventory listing/pricing
rules and agent context/privacy updates. These upstream changes are retained.
The original evaluated agent remains in commit history and immutable source archives;
the historical baseline must not be presented as evidence for the merged code.

Two conflicts were resolved:

- SessionProvider: retain main's shared transition helper for login/logout/session
  expiry; retain query cancellation before logout clears the observed user.
- Simulation database: retain fingerprinted templates and readiness markers. New
  migrations create a new matching template, addressing main's stale-schema concern
  without altering historical templates.

The client regression tests and build log merged with both sides' additions.
No unrelated changes were dropped. Real provider keys and local.env are excluded;
synthetic local.env.example files and setup instructions are tracked. The original
untracked handoff remains excluded and unchanged. Exact-key/token-pattern scans
included all 13 source archives. Captured terminal whitespace is intentionally
preserved; source whitespace checks are scoped separately.

## Combined validation

| Check | Result |
|---|---|
| Full backend suite | 2,103 passed; 2,300 dependency deprecation warnings; evidence/backend.xml |
| Full frontend suite | 190 passed, 13 files |
| Backend static checks | Ruff lint/format passed; strict mypy passed, 335 files |
| Frontend static/build | Lint, TypeScript and production build passed; large-chunk/jsdom warnings remain |
| Free evaluation gate | Planner exact; datasets valid; 289 historical result files clean; policy 133/241, zero no-shows/expiry violations |
| Conflicts/source whitespace | No unresolved conflicts; scoped source whitespace checks passed |
| Isolation | Only dedicated evaluation PostgreSQL/Mailpit used; both stopped after checks, data retained |

Exact commands, directories, exits and outputs are saved under evidence/ by check.py
and indexed in CHECKS.md. Fetch was repeated after tests; origin/main remains
28cf4f1. The canonical ledger retains all 81 original calls and six uncertain holds;
no paid calls were made. Previous readiness gaps remain documented in the
18 November reconciliation report. Browser journeys were not repeated for main's
new UI; their earlier evidence remains explicitly historical.

Publication target is only refs/heads/test/agent-evaluation, using a normal push
with no force. Main's remote ref must remain 28cf4f1 at verification. The merge
commit contains these checks and the unchanged upstream changes; its ID and remote
verification are reported to the user after pushing. The original handoff stays
untracked. No billing hold is released by committing the ledger.

## Publication result

Merge commit: `a83f039`. `git push --set-upstream origin test/agent-evaluation`
exited 128 with GitHub HTTP 403, permission denied to `ajkanaan`. The authenticated
account's API permission flags confirm `pull: true`, `push: false`; this is repository
access, not a merge conflict or main-branch protection rejection. No retry was made
after that permission check. No credential or account configuration was changed.

`git ls-remote origin refs/heads/test/agent-evaluation refs/heads/main` returned only
main at `28cf4f1d3f8412eff3ee7a10ffb9eb40102f1313`. Nothing was pushed; main is
unchanged and the remote test branch does not exist. All requested code/evidence
is committed locally, ready to publish once Mohammed grants `ajkanaan` Write access.
The already-authorized push can resume after checking for any newer main commits.

The pre-push evidence seal is preserved. Only this report and PROGRESS.md changed
after sealing, to record the real publication outcome; executed results remain
unchanged. A separate publication-status.json records the permission check and
updated documentation hashes.
