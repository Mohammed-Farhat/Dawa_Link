# DawaLink pre-deployment UI/UX audit

**Date:** 24 November 2026 (Asia/Beirut). **Recommendation: hold deployment for F-01 and F-02.**

The main synthetic client and pharmacy workflows work, and the tested layouts generally reflow well. Two recovery/state defects need fixing before release: a pharmacy-profile failure strands the entire portal on “Loading…”, and crossing the 992 px breakpoint silently discards unsaved client form state. The manual watch flow works through a product deep link, but ordinary no-stock search does not expose that entry point. Pickup also finalizes immediately, without confirmation or undo.

**Seven confirmed findings:** three functional/navigation defects, one accessibility semantics defect, two interaction improvements and one optional visual/information-hierarchy improvement. Severity and priority are independent; P1 means recommended release gate, P2 means next fix batch, P3 means improvement. High means a role cannot complete its work under the reproduced condition; medium means lost work, inaccessible functionality or consequential error risk; low means friction or reduced clarity. Effort: small = one localized change; medium = several components or state handling; large = broader redesign. Estimates exclude product decisions and review time.

All 37 implemented page/route templates were rendered at **390 × 844** and **1440 × 900**, with live synthetic data or explicitly identified fixtures. This is **not** a full application, mobile-browser or WCAG conformance certification. See [coverage and workflow limits](COVERAGE.md), [prioritized backlog](BACKLOG.md), and the [screenshot/state index](EVIDENCE_INDEX.md).

## Top five priorities

1. **F-01 — High / P1:** give pharmacy-profile failures an error message, retry and a way out.
2. **F-02 — Medium / P1:** preserve client form/draft state across the 992 px layout transition.
3. **F-03 — Medium / P2:** make the manual “Notify me” flow reachable for an unstocked medicine through normal search.
4. **I-01 — Medium / P2:** protect final pickup from an accidental tap, with confirmation or an appropriate recovery mechanism.
5. **A-01 — Low / P2:** distinguish search regions by medicine strength/form/pack in their accessible names.

## Environment and method

Evaluated source: **`840a7394d9930cebfcc2e2fae8b0f87d9c0ef04d` plus existing working-tree changes**, recorded in [initial Git state](evidence/git-status-before.txt) and [existing tracked changes](evidence/existing-source-changes.patch). The tracked changes are six backend evaluation modules; existing untracked evaluation files/directories and `DawaLink_Roadmap_and_Database_Handoff.md` were preserved. There were no pre-existing frontend modifications. Current frontend source was served by Vite, and current backend source by Uvicorn, rather than assuming the existing container images matched HEAD.

The original stack on ports 5173/8000 had `LLM_PROVIDER=anthropic`; it was left untouched and was not the audit target. A separate local instance used ports 5174/8001, a new `dawalink_ui_audit_20261124` database, the supported database/demo setup, and isolated Mailpit on 8026/SMTP 1026. Its API and worker had **`LLM_PROVIDER=none`** and no paid-model, road-routing or Langfuse keys. No paid evaluation commands were run, no STOP markers or budget ledgers were changed, and no real email was sent. Demo accounts, newly registered audit accounts, and the supported admin-creation command supplied all live identities. The demo clock was advanced 12 hours through its existing UI to exercise watches during request hours; business rules were unchanged.

Testing used installed **Chrome 158.0.8127.37 on macOS**, bundled Playwright and the repository's existing axe-core. Browser traffic for the main sweep and fixture/workflow checks was restricted to localhost; external map tiles were intentionally blocked. A later read-only watch reconnaissance loaded only local pages. Nothing uploaded source, credentials or screenshots to an external audit service. The full sweep used desktop viewport emulation, not a mobile OS. An installed iOS runtime/device was tried, but Simulator.app was missing from the configured Xcode directory; Safari open timed out and the capture remained at the Apple boot screen. An Android AVD was listed but was not exercised. Native keyboard, safe-area/browser-chrome behavior and mobile Safari remain unverified. The audit-started simulator was returned to shutdown.

Manual work covered screenshots, source tracing, rendered text/layout metrics, keyboard focus, menu arrows/Escape, stable dialog Tab cycling/Escape, form validation and focus, typed Arabic/mixed text, real synthetic mutations and failure injection. Narrow-phone checks used 320 px; search was checked around 480, 600, 992 and 1280 px. A 390 × 450 viewport was a short-height stress test, not an actual on-screen keyboard test.

Accessibility reference: [WCAG 2.2 AA](https://www.w3.org/TR/WCAG22/). Axe used WCAG A/AA tags through 2.2 plus best-practice rules in a painting browser, including contrast. Across **223 axe scans and 235 rendered capture records**, no automated WCAG-tagged A/AA violation was reported. Best-practice warnings occurred in repeated states: `landmark-unique` (9 scans), duplicate banner (7) and missing level-one heading (4). Contrast checks were incomplete in 47 scans and label/name checks in 22; see [aggregate results](evidence/automation-summary.json). Best-practice warnings and incomplete rules still require judgment; the automated results do not establish AA compliance. Contrast and label/name checks returned incomplete results in some states, and no screen-reader session was completed. Keyboard checks confirmed a visible skip link, focus transfer to `main`, account-menu navigation, settled reservation-modal focus containment and Escape, and keyboard horizontal scrolling of the inventory table. See [stable keyboard evidence](evidence/keyboard-stable.json).

The requested GPT-6.1 Sol Medium selection could not be verified or changed with the available session controls. Work was sequential and used no subagents.

## Selected audit skill

Installed and applied [Vercel web-design-guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines), version 1.1.0, at `/Users/ajkanaan/.codex/skills/web-design-guidelines`. Its [SKILL.md](/Users/ajkanaan/.codex/skills/web-design-guidelines/SKILL.md) and bundled `references/command.md` were inspected before use. The installed folder contains exactly these two Markdown files and no executable helper scripts. Its guideline snapshot pins upstream commit `434b7f91364665f2f733b310ec54809bf8f37937`. The supported skill installer succeeded with `--method git` after its download method hit a Python certificate-validation failure; certificate verification was not disabled. The skill is available automatically on the next turn. The user-requested detailed report format takes precedence over its terse default output format.

| Candidate | Scope and practical fit | Maintainer / maintenance evidence | Community evidence and decision |
|---|---|---|---|
| [Vercel web-design-guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines) | Direct review rules for accessibility, focus, forms, layout, content, touch and interaction. Framework-independent; fits React/Mantine source review and our existing browser/axe tools. Needs supplemental workflow testing and WCAG verification. | Official Vercel Labs repository. [Path history](https://github.com/vercel-labs/agent-skills/commits/main/skills/web-design-guidelines) metadata records 9 Nov 2026 maintenance. Local raw metadata is in `evidence/skill-maintenance-vercel.json`. | [Community description](https://www.reddit.com/r/BestGitHubRepos/comments/1wz8wai/agent_skills_a_collection_of_skills_for_ai_coding/) discusses UI review coverage. This is supporting discovery evidence, not a substantive independent quality evaluation. **Selected based on inspected scope, recent maintenance and lack of executable dependencies.** |
| [Anthropic webapp-testing](https://github.com/anthropics/skills/tree/main/skills/webapp-testing) | Clear local Playwright reconnaissance, screenshots and interaction testing. Less guidance on responsive/accessibility criteria; overlaps the browser tooling already available. Bundles a server helper and examples that were not installed or executed. | Official Anthropic repository. [Path history](https://github.com/anthropics/skills/commits/main/skills/webapp-testing) metadata returned 20 Apr 2026; see `evidence/skill-maintenance-anthropic.json`. | [QA-workflow discussion](https://www.reddit.com/r/codoid/comments/1vedops/the_16_claude_code_skills_that_stuck_in_qa/) recommends it as part of a QA stack, but does not establish comparative audit quality. Credible alternative for automation; weaker fit for the requested audit checklist. |

Two candidates were compared. No strong independent, substantive comparative community review was established; popularity and directory/security badges were not treated as proof of quality. Only the selected skill was installed, and no application dependency was added.

## Confirmed functional/navigation defects

### F-01 — Pharmacy-profile failures leave the whole portal on “Loading…”

**High · P1 · medium effort.** Role: pharmacy. Page: `/pharmacy/*`, reproduced on `/pharmacy`. Viewports: phone and desktop.

**Reproduce:** log in as a pharmacy; make `GET /api/v1/pharmacy/me` return 503; open the portal; wait 12 seconds so query retries finish. This was a browser response fixture, not a claim that the real API spontaneously failed. Four failed reads were recorded in the settled fixture's call log.

**Actual:** only “Loading…” remains. The portal navigation, retry, logout and error explanation are absent. **Expected:** distinguish pending from failed; explain the temporary failure, offer retry, and retain a safe way to leave/log out.

**Evidence:** [phone](screenshots/fixture-pharmacy-profile-error-settled-phone.png), [desktop](screenshots/fixture-pharmacy-profile-error-settled-desktop.png), [settled state/calls](evidence/settled-errors-states.json). Source: `frontend/src/features/pharmacy/PharmacyPortal.tsx:54` branches solely on missing data and ignores the failed query. The admin list provides an existing retry pattern to reuse.

**Impact:** an intermittent profile failure prevents every pharmacy task and gives no in-product recovery path. The missing heading reported by axe is a symptom of this same root cause, not a second finding.

**Fix / acceptance:** render explicit loading/error states around `usePharmacy`; after exhausted 503/network retries, show a named error screen and retry. Test 503 and rejected network requests; retry after recovery must load the portal without reauthentication; pending must still show a loading state. Verify both target sizes and keyboard access to retry/logout.

### F-02 — Crossing 992 px silently discards unsaved client state

**Medium · P1 · medium effort.** Role: client. Pages: confirmed on `/me` and the manual watch form; nested request-confirmation state also closed during the sweep. Viewports: transition **991 → 992 px** and phone ↔ desktop.

**Reproduce:** open `/me`; change First name to “Unsaved Synthetic Name” without saving; resize to 991 px, then 992 px. **Actual:** it remains typed at 991, then resets to the persisted “Rami” at 992, with no warning. The account-deletion form and manual watch form also closed when the layout boundary was crossed. **Expected:** responsive presentation changes preserve in-progress work and open-state where appropriate.

**Evidence:** [before](screenshots/breakpoint-profile-before.png), [after](screenshots/breakpoint-profile-after.png), [measured field values](evidence/manual-verification.json). Source: `frontend/src/components/layout.tsx:184` switches the `Screen` child tree between a fragment and `Shell`; `frontend/src/components/wide.ts` sets the 992 px boundary. Nested state is remounted. Other nested drafts should be checked rather than assumed affected.

**Impact:** resizing a window, using split-screen, or another width change across the boundary loses edits; users may submit stale values or repeat work.

**Fix / acceptance:** keep a stable component tree for responsive layout, or lift relevant draft state above the remounted boundary. At 991→992→991 and 390→1440→390, unsaved profile values must remain intact without saving to the server. Repeat for watch price input, deletion-form open state and request-cancellation confirmation. Inspect assistant drafts for the same cause. Do not silently persist unsaved changes as a workaround.

### F-03 — Normal no-stock search does not expose the working manual watch flow

**Medium · P2 · medium effort.** Role: client. Page: `/search`, with an existing but unstocked catalog medicine. Viewports: phone and desktop.

**Reproduce:** type “APO-AZITHROMYCIN Z” in normal search using the synthetic seed. **Actual:** no-stock results offer only “Ask DawaLink to find it”; there is no “Notify me” control or catalog/product selection. Open `/search?product=<that catalog product id>` directly and “Notify me if it appears” becomes available. Creating and cancelling the watch works. **Expected:** a client can identify an unstocked catalog medicine and reach its manual notification flow through the interface, including when the assistant is unavailable.

**Evidence:** [normal search, phone](screenshots/watch-discovery-phone.png), [desktop](screenshots/watch-discovery-desktop.png), [control counts](evidence/watch-discovery.json), [working deep-link form](screenshots/watch-final-form-phone.png), [live created/listed/cancelled record](evidence/watch-completed.json). Source: `frontend/src/features/client/search/SearchPage.tsx:309` renders only the assistant action for no groups; `:579` renders `NotifyMe` only on the product-specific route. Agent `create_watch` is an alternative, not a manual navigation path; live agent behavior was not tested.

**Impact:** the built manual watch feature is hard to discover for its primary use case, and no-stock users depend on the assistant even though the backend watch workflow works without it.

**Fix / acceptance:** offer catalog matching/selection for no-stock results and a clear manual watch action. From normal search, a client must select the exact medicine/strength/pack, start a 6-hour watch, find it in My medicines and stop it, without crafting a URL or using a model. Preserve existing request-hour, quantity and watch limits.

## Accessibility defect

### A-01 — Different search medicine groups have identical accessible region names

**Low · P2 · small effort.** Role: client. Page: populated `/search`. Viewports: phone and desktop.

**Reproduce:** search “a” in the seeded catalog; inspect named regions. **Actual:** separate strengths/packs share names such as “APO-ALLOPURINOL” and “APO-ATORVASTATIN”. Axe reports four duplicate-name nodes per viewport. Visible strength/form/pack text is not included in the region name. **Expected:** region navigation distinguishes the exact medicine variant.

**Evidence:** [phone](screenshots/search-results-phone.png), [axe nodes](evidence/search-results-phone-axe.json), [desktop axe nodes](evidence/search-results-desktop-axe.json). Source: `frontend/src/features/client/search/SearchPage.tsx:326` uses only `group.product.name` as `aria-label`, while variant details are separate text at `:331`.

**Impact:** assistive-technology region navigation cannot distinguish variants by name alone. WCAG reference: descriptive headings/labels, **2.4.6**; axe's `landmark-unique` is a best-practice rule and is not by itself proof of an AA failure.

**Fix / acceptance:** use an `aria-labelledby` combination or a concise accessible name containing the variant details needed to distinguish groups. No duplicated named medicine region should remain in this reproduced result set; verify names and navigation with a screen reader, not only axe. Keep visible variant details.

## Interaction improvements

### I-01 — Pickup finalizes with one tap and offers no undo

**Medium · P2 · medium effort.** Role: pharmacy. Pages: counter and reservation cards. Viewports: phone and desktop.

**Reproduce:** reserve a synthetic box; find its order number in the pharmacy counter; tap “Picked up”. **Actual:** one POST immediately changes the reservation to PICKED_UP, shows “is handed over”, and removes the finalization control. No confirmation or undo is offered. **Expected:** an explicit confirmation of the order/medicine/quantity, or a domain-appropriate correction path, guards an accidental final tap.

**Evidence:** [ready](screenshots/pickup-ready-phone.png), [finalized](screenshots/pickup-done-phone.png), [request count and final state](evidence/role-journeys.json). Source: `frontend/src/features/pharmacy/ReservationCard.tsx:116` calls `act('picked-up')` directly. Admin approval also acts immediately, but pickup is the confirmed primary case and is grouped here as an error-prevention concern rather than a second bug.

**Impact:** an accidental tap records a handover that did not happen. This is an interaction recommendation; the app currently implements its intentional one-tap behavior. No backend correctness or WCAG 3.3.4 violation is asserted.

**Fix / acceptance:** review the intended counter interaction; add a concise order-specific confirmation or a supported correction flow. If confirmation is selected, opening it sends no mutation, cancelling sends none, and confirming sends exactly one idempotent finalization request. Keep keyboard focus and target size usable at both viewports; leave inventory rules unchanged.

### I-02 — Location mode uses radio semantics without radio keyboard behavior

**Low · P3 · small effort.** Roles: public/client. Pages: signup and profile. Viewports: both; keyboard reproduction on desktop.

**Reproduce:** focus “On the map” in the Where you live radio group; press ArrowRight. **Actual:** focus and checked state do not move. Both controls remain ordinary tab stops; Tab/Space can still operate them. **Expected:** controls announced as radios follow the [WAI-ARIA radio-group keyboard pattern](https://www.w3.org/WAI/ARIA/apg/patterns/radio/), or use ordinary button semantics consistently.

**Evidence:** [keyboard measurement](evidence/manual-verification.json), [signup controls](screenshots/public-signup-phone.png). Source: `frontend/src/features/client/WhereYouLive.tsx:83–95` supplies roles and `aria-checked` but no arrow-key or roving-focus handling.

**Impact:** the announced widget behaves differently from keyboard users' expectations. This is a pattern inconsistency; a total keyboard-operability failure is not claimed.

**Fix / acceptance:** use native radios styled as pills, or implement Left/Right/Up/Down, checked-state updates and one tab stop for the group. Verify Tab, Shift+Tab, Space and arrow keys at both sizes without changing the selected location unexpectedly.

## Optional visual/information-hierarchy improvement

### V-01 — Phone inventory puts recurring stock work below lengthy setup content

**Low · P3 · small effort.** Role: pharmacy. Page: `/pharmacy/inventory`. Viewports: 390 px and 320 px; desktop is less affected.

**Reproduce:** open inventory on a phone. **Actual:** full CSV instructions and the Add one box form precede stock search and the table; repeat stock checks require scrolling through several screens of setup content. **Expected:** frequent tasks are easy to reach while import/replacement warnings remain visible at the point they matter.

**Evidence:** [390 px full page](screenshots/pharmacy-pharmacy-inventory-phone.png), [320 px](screenshots/narrow-pharmacy-320.png). Source: `frontend/src/features/pharmacy/InventoryPage.tsx:54–56` always renders `StockFile`, `AddBox`, then `StockTable`.

**Impact:** avoidable navigation effort for repeat mobile stock checks. This is not an overflow or WCAG failure: the table deliberately scrolls horizontally and was keyboard-scrollable.

**Fix / acceptance:** provide “Find stock / Add a box / Import CSV” task links or collapsible setup panels. At 390 and 320 px, stock search should be reachable by one explicit action without traversing the instructions. Expanded import must still explain that omitted rows are zeroed and reserved packs are retained. Preserve the existing direct access to Add a box for keyboard users.

## Observations requiring verification

- **NV-01 — Modal landmark warnings:** axe reports duplicate banner/landmark warnings when a Mantine modal is open (reservation and unavailable-stock dialogs). The DOM contains the page header and Modal header; no ancestor `inert`/`aria-hidden` was observed, while the dialog has `aria-modal=true`. Stable Tab cycling stayed in the dialog and Escape closed it. Verify VoiceOver/NVDA landmark and virtual-cursor behavior before deciding whether background hiding or header semantics need a fix. Evidence: [modal scan](evidence/keyboard-reserve-dialog-stable-axe.json), [stable DOM/keyboard record](evidence/keyboard-stable.json). Do not count this as a confirmed AA failure from axe alone.
- **NV-02 — Native mobile input:** native Safari, viewport changes from real keyboards, notches, browser toolbars and Android behavior remain unverified. The attempted iOS run stayed at boot, [captured here](screenshots/simulator-boot-failure.png). The short desktop viewport test cannot resolve these questions.
- **NV-03 — Incomplete automated checks:** review contrast and label/name items in per-state axe JSON. No failed color contrast was confirmed, but incomplete results are not passes. A full screen-reader and assistive-technology audit remains open.

## Release recommendation and remaining limits

**Block deployment on F-01 and F-02 until their acceptance criteria pass.** Resolve F-03 and review I-01 before calling the manual fallback and pharmacy counter ready for general users. A-01 is a small accessibility improvement to include in that batch. I-02 and V-01 can follow according to priority.

Live assistant quality, real-model clarification/decisions, external map tiles/geolocation permission behavior, real SMTP delivery, valid whole-stock CSV apply/discard, all admin rejection/suspension/contest/report mutations, all session-expiry/rate-limit variants, and watch-to-stock-arrival notification generation were not fully exercised. No business rules were modified to reach them. Assistant cards, request/offer states and escalation replies were tested with existing synthetic API fixtures; that verifies rendered interactions, not an integrated model/worker journey. A live unavailable-stock action did produce visible client notifications. The full coverage table identifies these distinctions and transient audit-probe failures that were later resolved.

No application fixes, architecture changes, commits, pushes, merges or deployments were performed. The intended persistent deliverables are this audit folder and the selected skill installation. Cleanup and preservation evidence is recorded separately in `evidence/preservation.json` and `evidence/cleanup.json`.
