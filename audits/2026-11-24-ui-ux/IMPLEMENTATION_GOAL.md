/goal Implement and verify the seven DawaLink UI/UX audit findings on the separate branch `fix/ui-ux-audit`. Leave the changes ready for review. Do not merge to main unless the user explicitly authorizes it in a later instruction. Do not deploy.

## Scope and starting point

Repository: `/Users/ajkanaan/Documents/AUB/EECE 503P - Agentic Systems/Project/dawalink-agentic-systems-project`.

Read repository instructions and these audit files before editing:
- `audits/2026-11-24-ui-ux/REPORT.md`: findings, reproduction steps and acceptance criteria.
- `audits/2026-11-24-ui-ux/BACKLOG.md`, `COVERAGE.md` and `PROGRESS.md`.
- Relevant screenshots/JSON through `EVIDENCE_INDEX.md`, especially settled error, breakpoint, watch-discovery and stable keyboard evidence.
- Relevant sections of `docs/11_ui_design.md`, `docs/06_api.md` and `docs/00_decision_log.md`.

The branch was created from `test/agent-evaluation` at `840a7394d9930cebfcc2e2fae8b0f87d9c0ef04d`. It has not been rebased onto main. Revalidate the actual branch, HEAD and working tree at execution time; the audit is historical evidence, not proof that code has remained unchanged. If already on this branch, continue there. If it is checked out in another workspace, use that workspace or a safely isolated checkout; never forcibly detach another session. Do not switch to or merge into main, merge other branches, rebase, reset or force-push.

There are pre-existing uncommitted changes in six `backend/src/dawalink/evals/` modules, untracked evaluation code/tests/data, the audit folder, and `DawaLink_Roadmap_and_Database_Handoff.md`. Preserve them. Record a fresh status, tracked diff and hashes of existing files before editing; do not stash, clean, delete, stage or commit unrelated work. The audit snapshot is in `evidence/git-status-before.txt` and `existing-source-changes.patch`. New UI work is authorized by executing this goal; earlier audit-only restrictions describe the completed audit, not this implementation task.

Work sequentially. Reuse existing React/Mantine components, API contracts, strings, Vitest/Testing Library and axe tooling. Do not add an audit framework, replace the design system or install unrelated dependencies. If present, inspect and apply `/Users/ajkanaan/.codex/skills/web-design-guidelines/SKILL.md` and its bundled guidance. Do not run unreviewed remote scripts.

## Safety and working environment

- No paid chat, evaluations or other model requests. Preserve all STOP markers and budget ledgers; do not resolve holds or change model/provider configuration in the existing stack.
- The original Docker stack on 5173/8000 had `LLM_PROVIDER=anthropic`. Do not assume those ports are safe test targets or change/stop that stack. The old isolated audit services/database were removed.
- For browser integration checks, create a separate current-source instance, disposable database and local captured-email service. Verify API and worker use `LLM_PROVIDER=none`, remove paid/telemetry/routing keys from their process environment, and target only their isolated ports. Use synthetic accounts/data and existing supported database/demo/admin setup. Keep secrets out of logs, reports, screenshots and Git.
- Use existing frontend fixtures for assistant and hard-to-reach UI states. Clearly label fixture results; never present them as live-model/integration verification. Use the supported demo clock only in the disposable database if request hours require it. Do not alter business rules or production data for testing.
- No agent architecture, schema migrations, request/sourcing policy, reservation/inventory accounting or authorization changes. The manual watch is distinct from an agent-created sourcing request; retain the rule that sourcing requests start in chat.
- Do not commit, push, open a PR or deploy as part of this goal. Leave a reviewed working-tree diff on the implementation branch. Never merge to main without a later explicit user instruction.

## Phase 1 — Baseline and release blockers

Record baseline checks and known failures before changing relevant code. Create a separate implementation evidence folder, e.g. `audits/2026-11-24-ui-ux/implementation-<execution-date>/`, without overwriting the original audit evidence. Maintain its short `PROGRESS.md` after each phase.

### F-01: Pharmacy-profile error recovery — high / P1

Inspect `frontend/src/features/pharmacy/PharmacyPortal.tsx`, `data.ts`, session handling and the admin's existing retry pattern.

Distinguish initial loading, exhausted initial query failure and available profile data. Give failed profile loading a heading, clear error message, keyboard-accessible retry and logout/exit. Preserve existing session-expiry handling and role restrictions; an authorization failure must not expose stale protected content. Consider background refresh failures when cached data exists rather than blindly hiding a usable portal. Reuse centralized error messages and existing loading/error primitives.

Acceptance:
- Pending shows loading; exhausted 503 and rejected-network reads show a useful error rather than indefinite Loading.
- Retry after API recovery loads the authorized portal without unnecessary reauthentication. Logout works from the failed state.
- Approved, pending, rejected and suspended pharmacy behavior stays correct.
- Verify at 390×844 and 1440×900, including keyboard operation. Use deterministic query retry settings in unit tests and settled retries in browser evidence.

### F-02: Preserve responsive client state — medium / P1

Inspect `frontend/src/components/layout.tsx`, `wide.ts`, shared CSS and all `Screen`/`Shell` consumers. Keep the page subtree at a stable React position and use responsive presentation around it; prefer this over saving drafts to storage or the server. Do not mount duplicate page trees or duplicate navigational landmarks to achieve the layout. Retain phone bottom navigation, desktop header, `plain`/`narrow` semantics, one main landmark, skip-link target, page-arrival focus and assistant height/scroll behavior.

Acceptance:
- At 991→992→991 and 390→1440→390, unsaved profile values survive without a mutation request.
- Watch form/price draft, deletion form and request-cancellation confirmation preserve relevant input/open state.
- Inspect assistant draft preservation with existing fixtures and test it if affected. Do not infer behavior from the profile alone.
- Changing layout does not create duplicate API mutations, lose route context, unexpectedly move focus or reset intentional form state. Navigation/logout still resets state where intended.
- Add a meaningful regression that changes the media-query result without remounting the test root. Verify actual resizing in a browser too.

Complete and verify these two blockers before moving to Phase 2. If a finding no longer reproduces, document the current evidence and retain a regression check where valuable; do not manufacture a fix.

## Phase 2 — Manual watch discovery and clearer medicine labels

### F-03: Reach Notify me from ordinary no-stock search — medium / P2

Inspect `frontend/src/features/client/search/SearchPage.tsx`, `NotifyMe.tsx`, search choices and the existing `GET /api/v1/catalog/products` contract. The pharmacy AddBox UI already uses catalog lookup; reuse the contract without coupling client code to pharmacy internals.

When ordinary name search has genuinely no stock, provide catalog matches with explicit selection of the exact product ID. Show enough name/strength/form/pack information to distinguish variants; include maker/code where needed. Route selection through the existing product-specific search and NotifyMe workflow. Retain the assistant option and existing watch limits, request hours, saved search choices and server-clock expiry messages. Avoid showing a watch merely because filters hide stock. Handle catalog loading, no match, failure/retry and stale responses after the query changes; use bounded queries consistent with current search behavior. Do not automatically choose the first medicine or create a watch/request.

Acceptance:
- From ordinary search for an existing unstocked medicine, select its exact variant, open Notify me, create a watch, find it in My medicines and stop it, without crafting a URL or using a model.
- Duplicate names/variants cannot silently target a different product ID.
- Existing stocked search, suggestions, filter-empty behavior and reservations still work; errors remain recoverable.
- Retain current handling for WATCH_EXISTS, LIMIT_WATCHES, OUTSIDE_REQUEST_HOURS and paused clients; test important unchanged boundaries with existing fixtures.

### A-01: Unique, useful medicine-region names — low / P2

In the same search work, derive region names from visible distinguishing medicine details, preferably `aria-labelledby` with stable unique IDs. Include meaningful variant information, not just an opaque ID or numerical suffix. Preserve visible labels and reasonable announcement length. If two entries still share details, use available maker/code to distinguish them.

Acceptance: same-brand variants are distinguishable in accessible region names on both viewports; the reproduced duplicate-name axe warning is resolved. Inspect the accessibility tree and use a screen reader if available; axe alone does not establish WCAG conformance.

## Phase 3 — Safer counter actions and keyboard behavior

### I-01: Confirm pharmacy pickup — medium / P2

Choose a concise confirmation dialog as the implementation approach; do not invent an undo/accounting reversal API. Update `frontend/src/features/pharmacy/ReservationCard.tsx` so the first Picked up tap opens a confirmation naming order number, medicine and quantity. Cancel/Escape must leave the reservation untouched. Only explicit confirmation invokes the existing picked-up endpoint. Keep the existing unavailable-stock dialog and mutation/refetch/error behavior correct.

This intentionally revises the current one-tap interaction documented in comments/tests. Update affected tests and current design documentation; preserve historical decision records. No changes to unrelated admin approval behavior are included.

Acceptance:
- Opening, cancelling and dismissing the dialog send zero pickup mutations. Confirm sends one request; disable repeated submission while pending and retain server duplicate/stale-state handling.
- API failure is visible where the user is acting and can be recovered from. Successful handover retains the existing notice/state update.
- Focus enters the dialog and returns appropriately on cancellation; if success removes the trigger, focus lands somewhere useful. Both viewports and keyboard operation work.

### I-02: Native radio behavior for location mode — low / P3

In `frontend/src/features/client/WhereYouLive.tsx`, prefer native radios styled with existing pills for map/area selection, or implement the full radio keyboard pattern if native controls are unsuitable. Keep one tab entry, arrow-key selection and visible focus. Preserve stored map/area values, lazy map loading and privacy behavior: changing mode alone must not request geolocation, submit profile data or write a location into a URL/storage. Existing explicit Use my location behavior remains intact.

Acceptance: Tab/Shift+Tab enter/leave the group sensibly, arrows move/select with wrapping, Space selects, and signup/profile bindings remain correct at both sizes. Verify mode changes do not accidentally request location or save data.

## Phase 4 — Small inventory hierarchy improvement

### V-01: Direct access to recurring stock work — low / P3

Make a small change in `frontend/src/features/pharmacy/InventoryPage.tsx`: add clearly labeled task links near the top for Find stock, Add a box and Import CSV, targeting stable sections. Prefer in-page links with correct scroll/focus behavior over conditional unmounting or a broader inventory redesign. Keep all forms and their drafts mounted. Preserve whole-stock replacement warnings at the upload action, reserved-pack explanations, table semantics and keyboard horizontal scrolling.

Acceptance: at 390 px and 320 px, stock search is reachable with one explicit action without traversing long instructions; Add a box and CSV remain directly accessible by keyboard. Headings are not obscured by sticky navigation, and no document overflow is introduced.

## Phase 5 — Regression, accessibility and delivery

Use existing tests under `frontend/src/test/`, `frontend/src/features/client/search/SearchPage.test.tsx`, `frontend/src/features/pharmacy/PharmacyPortal.test.tsx`, `PharmacyStock.test.tsx`, `PharmacyBounds.test.tsx`, `AccountPages.test.tsx`, `DeleteAccount.test.tsx`, `requests/RequestPage.test.tsx`, `assistant/AssistantPage.test.tsx` and `app/Frame.test.tsx`. Add focused tests only where they protect real new behavior, especially the two blockers, watch product selection and zero/one pickup mutations. Do not delete useful assertions simply to make changed behavior pass. Layout/contrast must be checked in a painting browser; jsdom cannot establish those results.

From `frontend/`, run focused tests during implementation, then the complete existing checks:

```sh
npm run test
npm run lint
npm run typecheck
VITE_API_URL=http://localhost:8001 npm run build
```

The build URL is an isolated local placeholder, not a deployment target; choose the actual isolated API port if different. Run each command separately and record actual results. Do not install dependencies merely to avoid diagnosing an existing setup issue. Backend tests are needed only if an unavoidable backend change is separately justified; the intended solution is frontend-only. Do not expand scope to fix unrelated baseline failures.

Browser verification:
- Exercise every changed acceptance criterion at 390×844 and 1440×900; capture before/after evidence in the new implementation folder.
- Because F-02 changes the shared client frame, repeat the existing 37-template route smoke matrix with synthetic live data or clearly labeled fixtures; check navigation, main/heading, viewport overflow and obvious layout regressions. This is a smoke check, not a claim of complete workflow coverage.
- Check 320 px on profile, search and pharmacy inventory; 479/480/481, 599/600/601, 991/992/993 and 1279/1280 where the changed layouts apply. Test actual resizing without reloading.
- Repeat client search/reserve/cancel, manual watch create/list/stop, deletion confirmation, pharmacy pickup/unavailable, inventory and admin navigation smoke checks. Assistant drafts/cards/support remain fixture-only.
- Run axe plus manual keyboard/focus inspection on changed states. Revisit NV-01 modal semantics, NV-02 native mobile input and NV-03 incomplete contrast/name results if the required tools are available. Do not apply speculative modal fixes based only on best-practice warnings. If screen readers/native browsers remain unavailable, record the precise limitation and recommended follow-up rather than claiming a pass or silently expanding infrastructure work.

Deliver `IMPLEMENTATION_REPORT.md` in the new evidence folder with each finding's status, changed files, acceptance evidence, test commands/results, before/after screenshots, regression matrix, unresolved limitations and remaining release recommendation. Link original audit findings; do not rewrite the original report as if fixes existed during the audit. Update only current design guidance that changed intentionally, not historical decisions.

Finally inspect the complete diff, check for unintended generated files/secrets, verify unrelated baseline changes and the handoff remain unchanged, and clean up only services/database/accounts created for this implementation. Keep implementation evidence; leave the original stack running. Report the branch and files changed, blockers resolved/unresolved and any failed checks.

Stop with all seven findings addressed and validated, or with a precise, evidenced explanation of any genuinely blocked item. Do not claim deployment readiness beyond the verified coverage. Leave everything on `fix/ui-ux-audit`; no commit, push, merge or deployment. Merging to main requires a later explicit instruction from the user.
