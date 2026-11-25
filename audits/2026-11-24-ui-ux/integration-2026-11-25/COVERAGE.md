# Main integration coverage

Chrome production build, 390×844 and 1440×900; synthetic live data unless marked fixture. This is route smoke plus the recorded workflows, not complete workflow coverage.

| Route | Phone | Desktop |
|---|---|---|
| /welcome | [Rendered](evidence/public-welcome-phone.json) | [Rendered](evidence/public-welcome-desktop.json) |
| /signup | [Rendered](evidence/public-signup-phone.json) | [Rendered](evidence/public-signup-desktop.json) |
| /login | [Rendered](evidence/public-login-phone.json) | [Rendered](evidence/public-login-desktop.json) |
| /forgot-password | [Rendered](evidence/public-forgot-password-phone.json) | [Rendered](evidence/public-forgot-password-desktop.json) |
| /reset-password | [Rendered](evidence/public-reset-password-phone.json) | [Rendered](evidence/public-reset-password-desktop.json) |
| /check-email | [Rendered](evidence/public-check-email-phone.json) | [Rendered](evidence/public-check-email-desktop.json) |
| /verify-email | [Rendered](evidence/public-verify-email-phone.json) | [Rendered](evidence/public-verify-email-desktop.json) |
| /pharmacy/signup | [Rendered](evidence/public-pharmacy-signup-phone.json) | [Rendered](evidence/public-pharmacy-signup-desktop.json) |
| /admin/login | [Rendered](evidence/public-admin-login-phone.json) | [Rendered](evidence/public-admin-login-desktop.json) |
| /status | [Rendered](evidence/public-status-phone.json) | [Rendered](evidence/public-status-desktop.json) |
| /unknown-page | [Rendered](evidence/public-unknown-page-phone.json) | [Rendered](evidence/public-unknown-page-desktop.json) |
| / | [Rendered](evidence/client-home-phone.json) | [Rendered](evidence/client-home-desktop.json) |
| /search | [Rendered](evidence/client-search-phone.json) | [Rendered](evidence/client-search-desktop.json) |
| /assistant | [Rendered](evidence/client-assistant-phone.json) | [Rendered](evidence/client-assistant-desktop.json) |
| /medicines | [Rendered](evidence/client-medicines-phone.json) | [Rendered](evidence/client-medicines-desktop.json) |
| /me | [Rendered](evidence/client-me-phone.json) | [Rendered](evidence/client-me-desktop.json) |
| /notifications | [Rendered](evidence/client-notifications-phone.json) | [Rendered](evidence/client-notifications-desktop.json) |
| /pharmacy | [Rendered](evidence/pharmacy-pharmacy-phone.json) | [Rendered](evidence/pharmacy-pharmacy-desktop.json) |
| /pharmacy/reservations | [Rendered](evidence/pharmacy-pharmacy-reservations-phone.json) | [Rendered](evidence/pharmacy-pharmacy-reservations-desktop.json) |
| /pharmacy/inventory | [Rendered](evidence/pharmacy-pharmacy-inventory-phone.json) | [Rendered](evidence/pharmacy-pharmacy-inventory-desktop.json) |
| /pharmacy/listings | [Rendered](evidence/pharmacy-pharmacy-listings-phone.json) | [Rendered](evidence/pharmacy-pharmacy-listings-desktop.json) |
| /pharmacy/settings | [Rendered](evidence/pharmacy-pharmacy-settings-phone.json) | [Rendered](evidence/pharmacy-pharmacy-settings-desktop.json) |
| /pharmacy/notifications | [Rendered](evidence/pharmacy-pharmacy-notifications-phone.json) | [Rendered](evidence/pharmacy-pharmacy-notifications-desktop.json) |
| /admin | [Rendered](evidence/admin-admin-phone.json) | [Rendered](evidence/admin-admin-desktop.json) |
| /admin/escalations | [Rendered](evidence/admin-admin-escalations-phone.json) | [Rendered](evidence/admin-admin-escalations-desktop.json) |
| /admin/reports | [Rendered](evidence/admin-admin-reports-phone.json) | [Rendered](evidence/admin-admin-reports-desktop.json) |
| /admin/clients | [Rendered](evidence/admin-admin-clients-phone.json) | [Rendered](evidence/admin-admin-clients-desktop.json) |
| /admin/health | [Rendered](evidence/admin-admin-health-phone.json) | [Rendered](evidence/admin-admin-health-desktop.json) |
| /admin/catalog | [Rendered](evidence/admin-admin-catalog-phone.json) | [Rendered](evidence/admin-admin-catalog-desktop.json) |
| /admin/audit | [Rendered](evidence/admin-admin-audit-phone.json) | [Rendered](evidence/admin-admin-audit-desktop.json) |
| /admin/clock | [Rendered](evidence/admin-admin-clock-phone.json) | [Rendered](evidence/admin-admin-clock-desktop.json) |

| Additional detail template | Data | Evidence at both sizes |
|---|---|---|
| Listing | Live | [Phone](evidence/listing-detail-phone.json), [desktop](evidence/listing-detail-desktop.json) |
| Reservation ticket | Live | [Phone](evidence/ticket-reserved-phone.json), [desktop](evidence/ticket-reserved-desktop.json) |
| Request thread | Fixture | [Phone](evidence/fixture-request-detail-phone.json), [desktop](evidence/fixture-request-detail-desktop.json) |
| Escalation detail | Fixture | [Phone](evidence/fixture-escalation-detail-phone.json), [desktop](evidence/fixture-escalation-detail-desktop.json) |
| Pharmacy administration | Live | [Phone](evidence/admin-pharmacy-pending-live-phone.json), [desktop](evidence/admin-pharmacy-pending-live-desktop.json) |
| Client administration | Live | [Phone](evidence/admin-client-live-phone.json), [desktop](evidence/admin-client-live-desktop.json) |

Total: 31 top-level routes + 6 detail templates = 37 templates rendered at both sizes.

Changed criteria: [acceptance](evidence/acceptance.json), [pickup/focus/inventory/breakpoints](evidence/interactions.json), [inventory draft](evidence/inventory-draft.json). Live end-to-end observations: [client](evidence/journeys.json), [pharmacy/admin](evidence/role-journeys.json). Assistant/team/request states remain fixtures; no live model was used.

Narrow/breakpoint checks: profile/search/inventory at 320 px; search at 479/480/481, 599/600/601, 991/992/993 and 1279/1280. Actual draft-preserving resize sequences include 991→992→991 and 390→1440→390.

Native Safari/Android, on-screen keyboard/safe-area behavior and screen-reader virtual cursor remain unverified. Axe incomplete contrast/name checks remain manual follow-ups; modal landmark best-practice warnings remain. External maps/geolocation and real email delivery were not tested. Synthetic mail was captured locally; no deployment or live-model integration coverage is claimed.
