# UI/UX fixes integrated with main — 25 November 2026

The seven audit fixes are verified against main at **`7da2b0a`** on **`fix/ui-ux-main-integration`**, in a separate worktree at `/private/tmp/dawalink-ui-ux-main-integration`. They are ready for PR review. **Nothing was merged or deployed.**

Only source commit `b836ac66a46542570faecb879f7708dc631f68d3` was cherry-picked, producing `8bcb2ac`. No other commits from `test/agent-evaluation` were imported. Backend application code, schema, agent behavior and evaluation artifacts are identical to this main base. The original `fix/ui-ux-audit` branch remains at `b836ac6`, with its pre-existing uncommitted work preserved.

See the [original findings](../REPORT.md), [historical implementation report](../implementation-2026-11-24/IMPLEMENTATION_REPORT.md), [current coverage](COVERAGE.md) and [current evidence index](EVIDENCE_INDEX.md). Historical test counts and environment details are retained as historical evidence, not substituted for this integration run.

## Integration decisions

The only cherry-pick conflict was in `docs/11_ui_design.md`. Resolution retains main’s account-deletion guidance and the pharmacy’s newer **Asks from DawaLink** placement, while replacing the prospective pickup Undo wording with the implemented confirmation. Main’s newer assistant offer-state tracking, generated API types, session implementation and tests were retained. No additional frontend implementation change was needed after applying the UI commit.

Current frontend source changes cover the shared layout, assistant/request frames, search/catalog choice and region labels, location radio behavior, pharmacy recovery, pickup confirmation, inventory links, anchor spacing, centralized strings and focused regressions. Exact source paths are listed in the [historical implementation report](../implementation-2026-11-24/IMPLEMENTATION_REPORT.md#source-and-test-changes). This integration also adds fresh evidence, updates that report with a dated integration pointer, and records the review candidate in `docs/build_plan.md`.

## Acceptance

| Finding | Current-source result | Evidence |
|---|---|---|
| F-01 pharmacy error recovery | Settled failure displays retry/logout; keyboard retry recovers at both sizes. Network/cached authorization cases remain covered by tests. | [Acceptance](evidence/acceptance.json), [phone](screenshots/profile-error-phone.png) |
| F-02 responsive state | Profile/deletion inputs and focus, assistant draft, request confirmation and watch price survive actual breakpoint resizing without unintended mutations. | [Acceptance](evidence/acceptance.json), [watch draft](screenshots/watch-draft-preserved-desktop.png) |
| F-03 watch discovery | Ordinary no-stock name search → explicit catalog variant → existing Notify me form → create/list/stop succeeds against main’s backend, without a model. | [Acceptance](evidence/acceptance.json), [chooser](screenshots/catalog-discovery-phone.png) |
| A-01 medicine regions | Populated search regions have distinct accessible labels; reproduced duplicate-region warning is absent at both sizes. | [Acceptance](evidence/acceptance.json), [axe](evidence/distinct-search-regions-phone-axe.json) |
| I-01 pickup confirmation | Cancel/Escape cause zero mutations; dialog failure/retry and explicit success pass at both sizes. Tab containment and useful success focus pass. Live counter handover sends one mutation. | [Interactions](evidence/interactions.json), [live pharmacy](evidence/role-journeys.json), [dialog](screenshots/pickup-confirmation-390.png) |
| I-02 location radios | Arrows select/focus with wrapping and no save/location request; existing account tests pass. | [Acceptance](evidence/acceptance.json) |
| V-01 inventory tasks | Stock target focuses and clears navigation at 320/390/1440 px; table keyboard scrolling works. Add-box draft survives jumps; CSV heading receives focus. | [Interactions](evidence/interactions.json), [draft](evidence/inventory-draft.json) |

Live client observations cover synthetic registration/confirmation, local password reset, login/logout, search/reserve/cancel and deletion-confirmation wrong-password recovery. Live pharmacy/admin observations cover pickup/unavailable, listing pause/resume, inventory pagination/filtering, pharmacy registration/confirmation, approval, client/audit navigation and notifications. All 20 observation records completed; these observations supplement explicit acceptance assertions and do not claim exhaustive workflow testing.

Route smoke rendered **31 top-level routes plus six detail templates**, each at **390×844 and 1440×900**. All 62 top-level route records reached the expected URL; no page errors were recorded. Narrow and breakpoint checks are enumerated in [coverage](COVERAGE.md). Assistant/team/request hard-to-reach states used existing synthetic fixtures; they are not live-model integration tests.

## Checks

Executed from this worktree’s `frontend/`, using existing Node **24.22.3** and existing dependencies; no installation or dependency-manifest changes:

| Command | Result |
|---|---|
| `npm run test -- --reporter=json --outputFile=…` | **533 passed, 0 failed**, 40 test files; [JSON](evidence/full-tests.json), [log](evidence/full-tests.log) |
| `npm run lint` | Exit 0; [log](evidence/lint.log) |
| `npm run typecheck` | Exit 0; [log](evidence/typecheck.log) |
| `VITE_API_URL=http://localhost:8001 npm run build` | Exit 0; [log](evidence/build.log) |

The count is two lower than the old branch’s 535 because current main does not contain that branch’s two additional logout tests. Main’s test tree was preserved; the live logout observation confirms redirection to `/login` and removal of the token. The existing non-failing build chunk-size warning and jsdom canvas/navigation notices remain. No backend test run is claimed: the integrated backend is unchanged from main and was exercised through isolated live API workflows.

Browser evidence contains **190 captures and 180 axe scans**, with no document overflow or WCAG-tagged automated violation. Four representative states were visually inspected. Eight modal scans retain duplicate-banner/landmark best-practice findings; incomplete contrast checks occur in 35 scans and label/name checks in 16. These are manual follow-ups, not accessibility passes. [Aggregate](evidence/automation-summary.json).

The initial dev-server run passed acceptance assertions, but the shared dependency symlink prevented fonts from being served. Final browser scripts were rerun against the production build’s preview with bundled-font readiness checks. Final screenshots overwrite those early captures; `acceptance-initial-fonts.*` retains superseded diagnostic results. The production preview/API are local verification targets, not deployed services.

## Isolation, preservation and cleanup

A fresh disposable PostgreSQL container/database, separate Mailpit and current-source API/worker/frontend were used. The API/worker received **`LLM_PROVIDER=none`**, a minimal environment with no model/routing/telemetry keys, synthetic accounts and local captured mail. Browser contexts blocked non-local requests. Source-path/configuration verification and seeded counts are in [runtime provenance](evidence/runtime-provenance.json). No paid model or evaluation command ran.

All **52 pre-existing modified/untracked files** in the original worktree retained their hashes, original status is identical, and its branch HEAD is unchanged. [Preservation](evidence/preservation.json). Sensitive-pattern scanning of new text artifacts found no provider/private keys, credential URLs or unredacted token URLs. [Scan](evidence/artifact-scan.json).

Disposable processes were stopped after verifying their working directories. Both test containers and PostgreSQL’s anonymous data volume were removed, as were temporary credentials and dependency/catalog symlinks. The original stack was not started or modified; Docker initially had no running containers. Docker Desktop was started to provide the test runtime. [Cleanup](evidence/cleanup.json). There is no running test environment left behind.

## Review and remaining limits

Recommend reviewing and merging this focused PR after the owner’s approval. The separate integration branch contains the UI commit and its verification/documentation update; it does not import the evaluation branch’s other commits. Main compatibility is verified for the recorded base; new main changes require normal PR conflict/check review.

Native mobile Safari/Android, on-screen keyboard/safe areas and screen-reader virtual-cursor/modal behavior remain unverified. Incomplete axe contrast/name checks remain manual follow-ups. Real map/geolocation, external email delivery and live models were not exercised. These limits do not negate the demonstrated regressions, and this report makes no broader deployment or accessibility-conformance claim. **Do not merge or deploy without explicit user authorization.**
