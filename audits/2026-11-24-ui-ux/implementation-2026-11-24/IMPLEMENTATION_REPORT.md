# DawaLink UI/UX implementation — 24 November 2026

All seven findings from the [original audit](../REPORT.md) are implemented on **`fix/ui-ux-audit`**. The two audited release blockers, F-01 and F-02, pass their regression checks. Changes are uncommitted and ready for review; nothing was pushed, merged or deployed.

**Validation:** 535 frontend tests passed; lint, type checking and the production build passed. All 37 page templates were rendered at 390×844 and 1440×900, with narrow/breakpoint checks. The evidence includes 192 captured states and 182 axe scans; repeated states are not separate workflow passes. There were no WCAG-tagged automated violations or captured document overflow. Manual screen-reader/native mobile limitations remain.

See [coverage and verification boundaries](COVERAGE.md), [evidence index](EVIDENCE_INDEX.md), [final acceptance results](evidence/acceptance.json), [interaction results](evidence/interactions.json), and [quality checks](evidence/quality-checks.json).

## Changes and acceptance results

| Finding | Implementation | Verification | Status |
|---|---|---|---|
| F-01 · pharmacy profile failure | Explicit initial error heading, retry and logout; pending remains loading. Transient cached refresh failure retains usable content with a warning; forbidden refresh hides protected portal content. Existing session-expiry handling remains. | Settled 503 after four reads → keyboard retry → portal recovery at both sizes. Tests cover network rejection, logout and cached transient/forbidden responses. | Implemented; regression passed |
| F-02 · responsive state loss | Stable ancestors around Screen/main, assistant conversation and request thread. Width changes update presentation rather than replacing the page subtree. No draft persistence or duplicate page trees added. | Actual 991↔992 and 390↔1440 resizing preserves profile values, deletion password/open state, watch price, assistant draft and request-cancellation dialog. Focus/one main/no unintended mutations checked. Unit media-query changes do not remount the test root. | Implemented; regression passed |
| F-03 · manual watch discovery | Bounded catalog lookup offers exact medicine/strength/form/pack/code selection from no-stock name search. Also available when only ingredient alternatives or close matches have stock. Selection uses the existing product search/Notify me flow; filters hiding stock do not expose a watch. | Live ordinary search → exact variant → create → My medicines → stop, without a crafted URL/model. Unit tests cover distinct product IDs, lookup error/retry/no match, ingredient alternatives and late responses for replaced queries; existing filter/limit tests pass. | Implemented; regression passed |
| A-01 · duplicate region names | Medicine regions include strength/form/pack, with catalog code distinguishing otherwise identical labels. Visible variant text remains. | Seeded populated search has distinct region names at both sizes; the reproduced duplicate-name warning is gone. Same-detail/code distinction covered by test. Accessibility-tree/DOM and axe checked; screen-reader session not completed. | Implemented; automated/DOM verification passed; AT follow-up remains |
| I-01 · accidental final pickup | Order-specific confirmation identifies reference, medicine and quantity. Cancel/Escape do not mutate; explicit confirm uses the existing endpoint. Submission and post-success guards prevent duplicate taps. Failure appears inside the dialog; focus has a useful destination when the card disappears. | Browser checks at both sizes: zero cancel requests, visible recoverable failure, one request on explicit success, Tab containment, Escape and focus to Reservations heading. Live counter pickup and existing unavailable-stock flow pass. Fast double-click guarded by unit test. | Implemented; regression passed |
| I-02 · radio keyboard mismatch | Existing radio buttons now have one tab stop and wrapping Left/Right/Up/Down selection/focus. Space retains native button activation. Location values/lazy map/explicit geolocation behavior remain. | Browser and test verify checked state/focus and no save mutation or unsolicited location request. Signup/profile and existing account tests pass. | Implemented; regression passed |
| V-01 · stock task hierarchy | Find stock / Add one box / Import CSV links at the top focus stable section headings. Scroll margins clear the sticky bar. Existing forms stay mounted and CSV replacement warnings remain beside upload. | 320/390/1440 stock target visible/focused without document overflow; keyboard table scrolling still works. Add-box draft survives navigation; CSV link focuses its heading. | Implemented; regression passed |

## Before and after evidence

| Finding | Original audit | Implementation |
|---|---|---|
| F-01 | [Indefinite loading](../screenshots/fixture-pharmacy-profile-error-settled-phone.png) | [Recoverable error](screenshots/profile-error-phone.png), [recovered portal](screenshots/fixture-profile-retry-phone.png) |
| F-02 | [Lost unsaved value](../evidence/manual-verification.json) | [Resize measurements](evidence/acceptance.json), [preserved profile/deletion](screenshots/fixture-responsive-profile-phone.png), [preserved request dialog](screenshots/fixture-responsive-request-confirmation-desktop.png) |
| F-03 | [No-stock discovery](../screenshots/watch-discovery-phone.png) | [Catalog chooser](screenshots/catalog-discovery-phone.png), [watch created](screenshots/watch-created-phone.png), [listed](screenshots/watch-listed-phone.png), [stopped](screenshots/watch-stopped-phone.png) |
| A-01 | [Duplicate named regions](../evidence/search-results-phone-axe.json) | [Distinct names](evidence/distinct-search-regions-phone.json), [axe](evidence/distinct-search-regions-phone-axe.json) |
| I-01 | [Immediate pickup record](../evidence/role-journeys.json) | [Confirmation](screenshots/pickup-confirmation-390.png), [inline failure](screenshots/pickup-error-390.png), [success/focus](evidence/interactions.json) |
| I-02 | [Arrow key had no effect](../evidence/manual-verification.json) | [Keyboard observation](evidence/acceptance.json), [radio state](screenshots/radio-keyboard-phone.png) |
| V-01 | [Original inventory](../screenshots/pharmacy-pharmacy-inventory-phone.png) | [Task links at top](screenshots/inventory-tasks-top-phone.png), [navigation measurements](evidence/interactions.json), [draft retained](evidence/inventory-draft.json) |

## Source and test changes

Shared frame: `frontend/src/components/layout.tsx`, `features/client/assistant/AssistantPage.tsx`, `features/client/requests/RequestPage.tsx`. Pharmacy recovery: `features/pharmacy/PharmacyPortal.tsx`. Search/catalog/accessible names: `features/client/search/SearchPage.tsx`. Pickup: `features/pharmacy/ReservationCard.tsx`. Radio behavior: `features/client/WhereYouLive.tsx`. Inventory links: `features/pharmacy/InventoryPage.tsx` and the anchor rule in `app/global.css`. UI wording remains centralized in `frontend/src/strings/en.ts`.

Tests were extended in AccountPages, SearchPage, RequestPage and PharmacyPortal; `app/ResponsiveState.test.tsx` exercises actual media-query subscriptions and retained form DOM/focus. Existing tests were updated for intentional variant labels and pickup confirmation, retaining transaction/error assertions. `docs/11_ui_design.md` records the current interaction changes; historical decision-log entries were preserved. The exact 16 source/document/test paths are recorded in [preservation evidence](evidence/preservation.json).

No backend application code, API contract, database schema, agent architecture, inventory accounting, sourcing-request policy or dependency manifests changed. Manual watches still use the existing endpoint and rules; sourcing requests still start in chat.

## Checks

Executed in `frontend/` with the already installed Node **24.22.3**, without adding dependencies:

| Check | Result | Evidence |
|---|---|---|
| `npm run test -- --reporter=json …` | 535 passed, 0 failed across 40 test files | [Full results](evidence/full-tests.json) |
| `npm run lint` | Exit 0 | [Log](evidence/final-lint.log) |
| `npm run typecheck` | Exit 0 | [Log](evidence/final-typecheck.log) |
| `VITE_API_URL=http://localhost:8001 npm run build` | Exit 0; local verification build only | [Log](evidence/final-build.log) |
| Focused final search/request suite | Passed after final shared-frame/search refactor | [Results](evidence/final-search-request-tests.json) |
| `git diff --check` | Passed | Final review |
| Route smoke / workflows | 37 templates × 2 viewports; live and fixture distinctions recorded | [Coverage](COVERAGE.md) |

The build retains its non-failing >500 kB chunk warning; bundle restructuring was outside this work. Existing jsdom canvas/navigation warnings do not establish browser layout or contrast behavior. Browser checks supplement those tests. The shell's default Node 20 could not format failed Vitest output because `Map.groupBy` was unavailable; final checks used the existing bundled Node 24 rather than installing anything.

Axe found no WCAG-tagged failures in these captures. It retained best-practice duplicate-banner/landmark warnings in eight modal scans, plus incomplete color-contrast checks in 37 scans and label/name checks in 16. These are not conformance passes. [Raw aggregate](evidence/automation-summary.json).

## Remaining limits and release recommendation

The two audited release blockers are resolved in the tested source. All seven planned changes are ready for code review. This is not deployment authorization or a complete accessibility/security certification.

- NV-01: modal background/virtual-cursor behavior still needs a real VoiceOver/NVDA session. Keyboard containment/Escape passed; no speculative background-hiding change was applied solely to quiet axe.
- NV-02: actual mobile Safari/Android, on-screen keyboard, browser chrome/safe areas remain unverified. Chrome phone viewport emulation was used. The prior native iOS launch failed; installing a replacement toolchain was not part of this implementation.
- NV-03: incomplete contrast/name items and screen-reader navigation remain manual follow-ups. No confirmed contrast failure was observed in inspected states.
- Live models and integrated model-to-team handoff were intentionally not exercised. Assistant/support/request rendering used the existing synthetic fixtures. External map tiles/geolocation and real mail delivery were not tested; mail stayed in isolated Mailpit. Other original coverage limits are retained in [the matrix](COVERAGE.md).

No further functional blocker was found within these acceptance checks. Review the changes and complete the remaining device/assistive-technology verification before making a broader release claim.

## Preservation and cleanup

Branch remains `fix/ui-ux-audit`, HEAD `840a7394d9930cebfcc2e2fae8b0f87d9c0ef04d`; all implementation changes remain in the working tree. Hashes of **2,588 existing evaluation/backend-test/handoff files** were unchanged. This includes the pre-existing modified evaluation modules and unrelated handoff. No commits, pushes, merges or deployment occurred.

Verification used a separate current-source API/worker with `LLM_PROVIDER=none`, removed external API keys, synthetic accounts, captured local email and a disposable database. Existing paid-model STOP/budget artifacts were preserved, and no paid model/evaluation command was run. The original stack was never the test target.

The temporary frontend/API/worker are stopped, isolated Mailpit removed, and `dawalink_ui_implementation_20261124` dropped with absence verified. Temporary environment/admin credential/launch files were removed, the artifact scan found no known environment-secret values, and all five original Compose services remain running. See [preservation](evidence/preservation.json) and [cleanup](evidence/cleanup.json). Retesting requires deliberately recreating isolation; there is no hidden test environment left running.
