# Implementation regression coverage

Phone: 390×844. Desktop: 1440×900. Live means current-source API with provider none and synthetic data; fixture means existing test fixtures intercepted in the browser. Rendered pages are smoke checks, not a claim that every mutation was exercised.

| Role | Template | Data/state | Phone | Desktop |
|---|---|---|---|---|
| public | `/welcome` | Live default/synthetic seed | [image](screenshots/public-welcome-phone.png) | [image](screenshots/public-welcome-desktop.png) |
| public | `/signup` | Live default/synthetic seed | [image](screenshots/public-signup-phone.png) | [image](screenshots/public-signup-desktop.png) |
| public | `/login` | Live default/synthetic seed | [image](screenshots/public-login-phone.png) | [image](screenshots/public-login-desktop.png) |
| public | `/forgot-password` | Live default/synthetic seed | [image](screenshots/public-forgot-password-phone.png) | [image](screenshots/public-forgot-password-desktop.png) |
| public | `/reset-password` | Live default/synthetic seed | [image](screenshots/public-reset-password-phone.png) | [image](screenshots/public-reset-password-desktop.png) |
| public | `/check-email` | Live default/synthetic seed | [image](screenshots/public-check-email-phone.png) | [image](screenshots/public-check-email-desktop.png) |
| public | `/verify-email` | Live default/synthetic seed | [image](screenshots/public-verify-email-phone.png) | [image](screenshots/public-verify-email-desktop.png) |
| public | `/pharmacy/signup` | Live default/synthetic seed | [image](screenshots/public-pharmacy-signup-phone.png) | [image](screenshots/public-pharmacy-signup-desktop.png) |
| public | `/admin/login` | Live default/synthetic seed | [image](screenshots/public-admin-login-phone.png) | [image](screenshots/public-admin-login-desktop.png) |
| public | `/status` | Live default/synthetic seed | [image](screenshots/public-status-phone.png) | [image](screenshots/public-status-desktop.png) |
| public | `/unknown-page` | Live default/synthetic seed | [image](screenshots/public-unknown-page-phone.png) | [image](screenshots/public-unknown-page-desktop.png) |
| client | `/` | Live default/synthetic seed | [image](screenshots/client-home-phone.png) | [image](screenshots/client-home-desktop.png) |
| client | `/search` | Live default/synthetic seed | [image](screenshots/client-search-phone.png) | [image](screenshots/client-search-desktop.png) |
| client | `/assistant` | Live default/synthetic seed | [image](screenshots/client-assistant-phone.png) | [image](screenshots/client-assistant-desktop.png) |
| client | `/medicines` | Live default/synthetic seed | [image](screenshots/client-medicines-phone.png) | [image](screenshots/client-medicines-desktop.png) |
| client | `/me` | Live default/synthetic seed | [image](screenshots/client-me-phone.png) | [image](screenshots/client-me-desktop.png) |
| client | `/notifications` | Live default/synthetic seed | [image](screenshots/client-notifications-phone.png) | [image](screenshots/client-notifications-desktop.png) |
| pharmacy | `/pharmacy` | Live default/synthetic seed | [image](screenshots/pharmacy-pharmacy-phone.png) | [image](screenshots/pharmacy-pharmacy-desktop.png) |
| pharmacy | `/pharmacy/reservations` | Live default/synthetic seed | [image](screenshots/pharmacy-pharmacy-reservations-phone.png) | [image](screenshots/pharmacy-pharmacy-reservations-desktop.png) |
| pharmacy | `/pharmacy/inventory` | Live default/synthetic seed | [image](screenshots/pharmacy-pharmacy-inventory-phone.png) | [image](screenshots/pharmacy-pharmacy-inventory-desktop.png) |
| pharmacy | `/pharmacy/listings` | Live default/synthetic seed | [image](screenshots/pharmacy-pharmacy-listings-phone.png) | [image](screenshots/pharmacy-pharmacy-listings-desktop.png) |
| pharmacy | `/pharmacy/settings` | Live default/synthetic seed | [image](screenshots/pharmacy-pharmacy-settings-phone.png) | [image](screenshots/pharmacy-pharmacy-settings-desktop.png) |
| pharmacy | `/pharmacy/notifications` | Live default/synthetic seed | [image](screenshots/pharmacy-pharmacy-notifications-phone.png) | [image](screenshots/pharmacy-pharmacy-notifications-desktop.png) |
| admin | `/admin` | Live default/synthetic seed | [image](screenshots/admin-admin-phone.png) | [image](screenshots/admin-admin-desktop.png) |
| admin | `/admin/escalations` | Live default/synthetic seed | [image](screenshots/admin-admin-escalations-phone.png) | [image](screenshots/admin-admin-escalations-desktop.png) |
| admin | `/admin/reports` | Live default/synthetic seed | [image](screenshots/admin-admin-reports-phone.png) | [image](screenshots/admin-admin-reports-desktop.png) |
| admin | `/admin/clients` | Live default/synthetic seed | [image](screenshots/admin-admin-clients-phone.png) | [image](screenshots/admin-admin-clients-desktop.png) |
| admin | `/admin/health` | Live default/synthetic seed | [image](screenshots/admin-admin-health-phone.png) | [image](screenshots/admin-admin-health-desktop.png) |
| admin | `/admin/catalog` | Live default/synthetic seed | [image](screenshots/admin-admin-catalog-phone.png) | [image](screenshots/admin-admin-catalog-desktop.png) |
| admin | `/admin/audit` | Live default/synthetic seed | [image](screenshots/admin-admin-audit-phone.png) | [image](screenshots/admin-admin-audit-desktop.png) |
| admin | `/admin/clock` | Live default/synthetic seed | [image](screenshots/admin-admin-clock-phone.png) | [image](screenshots/admin-admin-clock-desktop.png) |
| client | `/listings/:id` | Live listing | [image](screenshots/listing-detail-phone.png) | [image](screenshots/listing-detail-desktop.png) |
| client | `/reservations/:id` | Live reserved ticket | [image](screenshots/ticket-reserved-phone.png) | [image](screenshots/ticket-reserved-desktop.png) |
| client | `/requests/:id` | Fixture request/offer/thread | [image](screenshots/fixture-request-detail-phone.png) | [image](screenshots/fixture-request-detail-desktop.png) |
| admin | `/admin/pharmacies/:id` | Live pending/approved detail | [image](screenshots/admin-pharmacy-pending-live-phone.png) | [image](screenshots/admin-pharmacy-pending-live-desktop.png) |
| admin | `/admin/clients/:id` | Live client detail | [image](screenshots/admin-client-live-phone.png) | [image](screenshots/admin-client-live-desktop.png) |
| admin | `/admin/escalations/:id` | Fixture escalation detail | [image](screenshots/fixture-escalation-detail-phone.png) | [image](screenshots/fixture-escalation-detail-desktop.png) |

37 templates rendered at both target sizes. Public token pages initially show their missing/invalid-token state; valid confirmation/reset and local email flows were separately exercised. Assistant page loading with provider none is not model testing.

| Acceptance / workflow | Evidence and status |
|---|---|
| F-01 settled 503 → keyboard retry/recovery | `evidence/acceptance.json`; four failed reads before retry. Network rejection/logout and cached transient/forbidden branches covered by unit tests. |
| F-02 actual resize without reload | `evidence/acceptance.json`; profile values, deletion password/open state, assistant draft, request-cancellation dialog and watch price survive 991↔992 and 390↔1440. One main; no unintended mutations. |
| F-03 ordinary search → exact catalog variant → watch → My medicines → stop | Live `evidence/acceptance.json`. Catalog failure/no-match, variants, late response and existing filter/limits behavior covered in SearchPage tests. |
| A-01 populated region names | Live `distinct-search-regions-*` and acceptance record; named regions distinct; duplicate-code fallback covered by unit test. |
| I-01 pickup confirmation | Fixture `evidence/interactions.json`, phone/desktop: opening/cancelling/Escape zero requests; error visible in dialog; explicit retry succeeds; focus restored to Reservations heading if card disappears. Live counter journey also succeeds. Fast double-click guard covered by unit test. |
| I-02 radio keyboard | Live acceptance and unit tests: arrows wrap with checked state/focus, zero save mutations or unsolicited geolocation. |
| V-01 task links | Live interactions at 320/390/1440; stock heading focused, clears sticky bar, table scrolls by keyboard. `inventory-draft.json` verifies add-box draft retained and CSV link focused. |
| Client registration/confirmation/reset/login/logout | Live `evidence/journeys.json`, captured local email only. |
| Search/reserve/ticket/cancel/deletion confirmation | Live journeys; wrong-password deletion preserves account. Successful destructive deletion was not repeated in this implementation; its existing tests pass. |
| Pharmacy pickup/unavailable/listings/inventory | Live `evidence/role-journeys.json`: confirmed pickup, unavailable ticket/notifications, pause/resume, pagination and empty filter. Existing stock/add/CSV regression tests pass; no claim of exhaustive CSV replacement testing. |
| Admin TOTP/approval/detail/audit | Live role journeys; remaining admin page templates smoke-tested. |
| Assistant/support/request states | Existing fixtures only. Support message/card/thread rendering captured; no integrated model-to-team handoff or live model evaluation. |
| Responsive widths | `interactions.json`: search 320, 479/480/481, 599/600/601, 991/992/993, 1279/1280; profile 320; inventory 320/390/1440. No captured document overflow. |

## Verification boundaries

Desktop Chrome viewport emulation only. Native mobile Safari/Android, on-screen keyboard, browser chrome/safe areas and screen-reader sessions remain unverified. The original audit's installed iOS runtime could not launch a functioning Simulator/Safari; no new emulator/toolchain installation was attempted. Modal headers retain best-practice duplicate-banner warnings; settled Tab cycling/Escape work, but this is not proof of virtual-cursor isolation. Incomplete axe contrast/name checks are not passes. No speculative modal-background change was made.

External map tiles and real geolocation/delivery were blocked/not exercised. Model quality, all admin mutations, all session/rate-limit combinations, valid whole-stock replacement and watch-to-stock-arrival generation remain outside verified coverage. New screenshots include full-page captures with sticky headers at the current scroll position; this can place the header midway through the stitched image.

Initial acceptance logs are retained with `-initial`, `-second`, `-third` suffixes. They include incorrect audit selectors (delete button ellipsis, product-specific Stop watching label), a shared-context admin login mistake, the real request-frame remount subsequently fixed, and the ingredient-alternative catalog case subsequently fixed. Canonical `acceptance.json` and `interactions.json` are the final results. Earlier `changed-tests.json` failures are superseded by `full-tests.json` and final focused results. These probe mistakes are not remaining application findings.
