# Page and workflow coverage

24 November 2026. Phone = 390×844; desktop = 1440×900. “Rendered” records an observed state, not a successful workflow or accessibility certification. Live means the isolated current-source backend with synthetic data and provider `none`; fixture means browser API interception using the repository’s existing test data.

## Implemented page templates

31 top-level routes and six detail templates. Both requested viewports were captured for each. Common not-found is counted once. Parameters represent synthetic IDs.

| Role | Route | Data / state | Phone | Desktop |
|---|---|---|---|---|
| public | `/welcome` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-welcome-phone.png) | [image](screenshots/public-welcome-desktop.png) |
| public | `/signup` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-signup-phone.png) | [image](screenshots/public-signup-desktop.png) |
| public | `/login` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-login-phone.png) | [image](screenshots/public-login-desktop.png) |
| public | `/forgot-password` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-forgot-password-phone.png) | [image](screenshots/public-forgot-password-desktop.png) |
| public | `/reset-password` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-reset-password-phone.png) | [image](screenshots/public-reset-password-desktop.png) |
| public | `/check-email` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-check-email-phone.png) | [image](screenshots/public-check-email-desktop.png) |
| public | `/verify-email` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-verify-email-phone.png) | [image](screenshots/public-verify-email-desktop.png) |
| public | `/pharmacy/signup` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-pharmacy-signup-phone.png) | [image](screenshots/public-pharmacy-signup-desktop.png) |
| public | `/admin/login` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-admin-login-phone.png) | [image](screenshots/public-admin-login-desktop.png) |
| public | `/status` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-status-phone.png) | [image](screenshots/public-status-desktop.png) |
| public | `/unknown-page` | Live; public form/status; token routes initially missing-token | [image](screenshots/public-unknown-page-phone.png) | [image](screenshots/public-unknown-page-desktop.png) |
| client | `/` | Live; default/empty or populated seed | [image](screenshots/client-home-phone.png) | [image](screenshots/client-home-desktop.png) |
| client | `/search` | Live; default/empty or populated seed | [image](screenshots/client-search-phone.png) | [image](screenshots/client-search-desktop.png) |
| client | `/assistant` | Live; default/empty or populated seed | [image](screenshots/client-assistant-phone.png) | [image](screenshots/client-assistant-desktop.png) |
| client | `/medicines` | Live; default/empty or populated seed | [image](screenshots/client-medicines-phone.png) | [image](screenshots/client-medicines-desktop.png) |
| client | `/me` | Live; default/empty or populated seed | [image](screenshots/client-me-phone.png) | [image](screenshots/client-me-desktop.png) |
| client | `/notifications` | Live; default/empty or populated seed | [image](screenshots/client-notifications-phone.png) | [image](screenshots/client-notifications-desktop.png) |
| pharmacy | `/pharmacy` | Live; default/empty or populated seed | [image](screenshots/pharmacy-pharmacy-phone.png) | [image](screenshots/pharmacy-pharmacy-desktop.png) |
| pharmacy | `/pharmacy/reservations` | Live; default/empty or populated seed | [image](screenshots/pharmacy-pharmacy-reservations-phone.png) | [image](screenshots/pharmacy-pharmacy-reservations-desktop.png) |
| pharmacy | `/pharmacy/inventory` | Live; default/empty or populated seed | [image](screenshots/pharmacy-pharmacy-inventory-phone.png) | [image](screenshots/pharmacy-pharmacy-inventory-desktop.png) |
| pharmacy | `/pharmacy/listings` | Live; default/empty or populated seed | [image](screenshots/pharmacy-pharmacy-listings-phone.png) | [image](screenshots/pharmacy-pharmacy-listings-desktop.png) |
| pharmacy | `/pharmacy/settings` | Live; default/empty or populated seed | [image](screenshots/pharmacy-pharmacy-settings-phone.png) | [image](screenshots/pharmacy-pharmacy-settings-desktop.png) |
| pharmacy | `/pharmacy/notifications` | Live; default/empty or populated seed | [image](screenshots/pharmacy-pharmacy-notifications-phone.png) | [image](screenshots/pharmacy-pharmacy-notifications-desktop.png) |
| admin | `/admin` | Live; default/empty or populated seed | [image](screenshots/admin-admin-phone.png) | [image](screenshots/admin-admin-desktop.png) |
| admin | `/admin/escalations` | Live; default/empty or populated seed | [image](screenshots/admin-admin-escalations-phone.png) | [image](screenshots/admin-admin-escalations-desktop.png) |
| admin | `/admin/reports` | Live; default/empty or populated seed | [image](screenshots/admin-admin-reports-phone.png) | [image](screenshots/admin-admin-reports-desktop.png) |
| admin | `/admin/clients` | Live; default/empty or populated seed | [image](screenshots/admin-admin-clients-phone.png) | [image](screenshots/admin-admin-clients-desktop.png) |
| admin | `/admin/health` | Live; default/empty or populated seed | [image](screenshots/admin-admin-health-phone.png) | [image](screenshots/admin-admin-health-desktop.png) |
| admin | `/admin/catalog` | Live; default/empty or populated seed | [image](screenshots/admin-admin-catalog-phone.png) | [image](screenshots/admin-admin-catalog-desktop.png) |
| admin | `/admin/audit` | Live; default/empty or populated seed | [image](screenshots/admin-admin-audit-phone.png) | [image](screenshots/admin-admin-audit-desktop.png) |
| admin | `/admin/clock` | Live; default/empty or populated seed | [image](screenshots/admin-admin-clock-phone.png) | [image](screenshots/admin-admin-clock-desktop.png) |
| client | `/listings/:id` | Live offer detail | [image](screenshots/listing-detail-phone.png) | [image](screenshots/listing-detail-desktop.png) |
| client | `/reservations/:id` | Live reserved ticket | [image](screenshots/ticket-reserved-phone.png) | [image](screenshots/ticket-reserved-desktop.png) |
| client | `/requests/:id` | Fixture active request/offer | [image](screenshots/fixture-request-active-offer-phone.png) | [image](screenshots/fixture-request-active-offer-desktop.png) |
| admin | `/admin/pharmacies/:id` | Live pending detail; also fixture | [image](screenshots/admin-pharmacy-pending-live-phone.png) | [image](screenshots/admin-pharmacy-pending-live-desktop.png) |
| admin | `/admin/clients/:id` | Live client; also fixture | [image](screenshots/admin-client-live-phone.png) | [image](screenshots/admin-client-live-desktop.png) |
| admin | `/admin/escalations/:id` | Fixture escalation detail | [image](screenshots/fixture-admin-escalation-detail-phone.png) | [image](screenshots/fixture-admin-escalation-detail-desktop.png) |

## Important states and representative journeys

Both columns link the final/representative rendered state. Logs provide mutation observations; a screenshot alone does not prove an end-to-end transaction.

| Area / state or workflow | Result and boundary | Phone | Desktop | Evidence |
|---|---|---|---|---|
| Client registration | Live validation, first-error focus, local confirmation email and successful verification | [image](screenshots/signup-validation-phone.png) | [image](screenshots/signup-validation-desktop.png) | [record](evidence/journeys.json) |
| Client email confirmation | Live captured Mailpit link; successful verification | [image](screenshots/email-verified-phone.png) | [image](screenshots/email-verified-desktop.png) | [record](evidence/journeys.json) |
| Login / logout | Live synthetic login and token cleared after logout; all role logins exercised | [image](screenshots/logout-phone.png) | [image](screenshots/logout-desktop.png) | [record](evidence/journeys.json) |
| Password reset | Live captured reset email, valid-token form and successful reset; missing-token page in sweep | [image](screenshots/password-reset-done-phone.png) | [image](screenshots/password-reset-done-desktop.png) | [record](evidence/journeys.json) |
| Search / reserve | Live seeded results, offer detail, quantity confirmation and created reservation | [image](screenshots/reservation-confirmation-phone.png) | [image](screenshots/reservation-confirmation-desktop.png) | [record](evidence/journeys.json) |
| Ticket / cancel | Live reserved ticket, cancellation confirmation and cancelled state | [image](screenshots/ticket-cancelled-phone.png) | [image](screenshots/ticket-cancelled-desktop.png) | [record](evidence/journeys.json) |
| Profile / deletion failure | Live wrong password keeps account authenticated; breakpoint loss F-02 | [image](screenshots/delete-wrong-password-phone.png) | [image](screenshots/delete-wrong-password-desktop.png) | [record](evidence/manual-verification.json) |
| Account deletion | Live successful deletion of new synthetic client; token cleared and welcome banner | [image](screenshots/account-deleted-success-phone.png) | [image](screenshots/account-deleted-success-desktop.png) | [record](evidence/final-journeys.json) |
| Pharmacy registration | Live local email confirmation, pending portal; map center control with external tiles blocked | [image](screenshots/pharmacy-pending-live-phone.png) | [image](screenshots/pharmacy-pending-live-desktop.png) | [record](evidence/role-journeys.json) |
| Counter pickup | Live reservation → order lookup → picked up; no confirmation/undo observed (I-01) | [image](screenshots/pickup-done-phone.png) | [image](screenshots/pickup-done-desktop.png) | [record](evidence/role-journeys.json) |
| Unavailable stock | Live reservation → confirmation → unavailable; client ticket and notifications updated | [image](screenshots/unavailable-done-phone.png) | [image](screenshots/unavailable-done-desktop.png) | [record](evidence/role-journeys.json) |
| Notifications | Live populated client notifications after unavailable action; role default pages in sweep | [image](screenshots/notifications-populated-live-phone.png) | [image](screenshots/notifications-populated-live-desktop.png) | [record](evidence/role-journeys.json) |
| Inventory add | Live required-field validation and successful synthetic batch addition | [image](screenshots/inventory-add-success-phone.png) | [image](screenshots/inventory-add-success-desktop.png) | [record](evidence/final-journeys.json) |
| Inventory pagination/filter | Live second page and no-match empty filter; keyboard table scrolling checked separately | [image](screenshots/inventory-empty-filter-phone.png) | [image](screenshots/inventory-empty-filter-desktop.png) | [record](evidence/role-journeys.json) |
| CSV error | Live invalid header gives recoverable message; whole-stock valid apply/discard untested | [image](screenshots/inventory-csv-invalid-phone.png) | [image](screenshots/inventory-csv-invalid-desktop.png) | [record](evidence/final-journeys.json) |
| Listing management | Live pause then resume listing | [image](screenshots/listing-resumed-phone.png) | [image](screenshots/listing-resumed-desktop.png) | [record](evidence/role-journeys.json) |
| Pharmacy role states | Fixture pending, rejected, suspended; corresponding screenshots indexed separately | [image](screenshots/fixture-pharmacy-suspended-phone.png) | [image](screenshots/fixture-pharmacy-suspended-desktop.png) | [record](evidence/fixture-states.json) |
| Pharmacy profile error | Fixture 503 after four reads/12 s stays Loading (F-01) | [image](screenshots/fixture-pharmacy-profile-error-settled-phone.png) | [image](screenshots/fixture-pharmacy-profile-error-settled-desktop.png) | [record](evidence/settled-errors-states.json) |
| Stock query error | Fixture stock error captured; nominal stock-loading probe did not establish a durable loading state | [image](screenshots/fixture-pharmacy-stock-error-phone.png) | [image](screenshots/fixture-pharmacy-stock-error-desktop.png) | [record](evidence/extra-fixture-states.json) |
| Admin TOTP | Live supported synthetic admin login with TOTP | [image](screenshots/admin-totp-login-phone.png) | [image](screenshots/admin-totp-login-desktop.png) | [record](evidence/role-journeys.json) |
| Admin approval | Live pending synthetic pharmacy approved, after correcting audit selector assumption | [image](screenshots/admin-approval-success-phone.png) | [image](screenshots/admin-approval-success-desktop.png) | [record](evidence/final-journeys.json) |
| Admin list error | Fixture 503 settles to error with Try again | [image](screenshots/fixture-admin-list-error-settled-phone.png) | [image](screenshots/fixture-admin-list-error-settled-desktop.png) | [record](evidence/settled-errors-states.json) |
| Admin audit navigation | Live client detail and populated audit log navigation | [image](screenshots/admin-audit-live-phone.png) | [image](screenshots/admin-audit-live-desktop.png) | [record](evidence/role-journeys.json) |
| Admin escalation reply | Fixture escalation detail and reply updates UI; no integrated support handoff | [image](screenshots/fixture-admin-escalation-reply-phone.png) | [image](screenshots/fixture-admin-escalation-reply-desktop.png) | [record](evidence/extra-fixture-states.json) |
| Reported answers | Fixture populated report details; admin list page live empty | [image](screenshots/fixture-admin-reported-answer-phone.png) | [image](screenshots/fixture-admin-reported-answer-desktop.png) | [record](evidence/fixture-states.json) |
| Assistant clarification / team | Existing fixtures render clarification, reservation cards and team messages; no live model | [image](screenshots/fixture-assistant-clarification-card-team-phone.png) | [image](screenshots/fixture-assistant-clarification-card-team-desktop.png) | [record](evidence/fixture-states.json) |
| Assistant card action | Fixture execute action updates card to reserved/system ticket; simulated backend response | [image](screenshots/fixture-assistant-card-action-phone.png) | [image](screenshots/fixture-assistant-card-action-desktop.png) | [record](evidence/remaining-states.json) |
| Assistant failure | Fixture 503 retains draft with visible error | [image](screenshots/fixture-assistant-failed-send-phone.png) | [image](screenshots/fixture-assistant-failed-send-desktop.png) | [record](evidence/extra-fixture-states.json) |
| Request / offer | Fixture active request and offer; cancellation sheet observed; crossing layout can close it | [image](screenshots/fixture-request-active-offer-phone.png) | [image](screenshots/fixture-request-active-offer-desktop.png) | [record](evidence/fixture-states.json) |
| Missed ticket | Fixture missed-pickup ticket | [image](screenshots/fixture-ticket-missed-phone.png) | [image](screenshots/fixture-ticket-missed-desktop.png) | [record](evidence/fixture-states.json) |
| Watch discovery | Live ordinary no-stock search offers assistant but no manual Notify me (F-03) | [image](screenshots/watch-discovery-phone.png) | [image](screenshots/watch-discovery-desktop.png) | [record](evidence/watch-discovery.json) |
| Watch create/list/stop | Live product deep link → form → created → listed → stopped; no stock-arrival notification generation | [image](screenshots/watch-final-stopped-phone.png) | [image](screenshots/watch-final-stopped-desktop.png) | [record](evidence/watch-completed.json) |
| Supported demo clock | Live +6 h twice in isolated DB; 720-minute offset reaches request hours | [image](screenshots/demo-clock-advanced-phone.png) | [image](screenshots/demo-clock-advanced-desktop.png) | [record](evidence/final-journeys.json) |
| Arabic / long mixed chat | Fixture Arabic plus English mixed long text; dir=auto on messages; English app chrome | [image](screenshots/fixture-arabic-mixed-long-chat-phone.png) | [image](screenshots/fixture-arabic-mixed-long-chat-desktop.png) | [record](evidence/remaining-states.json) |
| Long pharmacy name | Fixture long label reflow | [image](screenshots/fixture-long-pharmacy-name-phone.png) | [image](screenshots/fixture-long-pharmacy-name-desktop.png) | [record](evidence/extra-fixture-states.json) |

## Cross-cutting checks

- Manual keyboard: visible skip link → main; labeled password control; account menu arrows/Escape; settled reservation modal retains 22 Tab steps and closes with Escape; focused inventory table scrolls with ArrowRight. See [stable log](evidence/keyboard-stable.json). Initial keyboard probe raced modal mounting; its early failures were superseded by settled checks.
- 320 px: client profile, pharmacy inventory and admin catalog. Search widths: 320, 479/480/481, 599/600/601, 991/992/993 and 1279/1280. Captured document widths did not overflow. Inventory has intentional keyboard-scrollable table overflow. Search at 390×450 was short-height emulation only.
- Forms: signup required/errors, password guidance/visibility, reset, deletion wrong/success password, inventory add validation and CSV error. No blanket claim for every validation, permission or rate-limit combination.
- Automated WCAG A/AA through 2.2 plus best practice: per-state raw results and [aggregate](evidence/automation-summary.json). Incomplete contrast/name rules and manual screen-reader work remain. Small-target/overflow DOM lists are inspection aids, not violations by themselves.
- Source review covered shared responsive shell, navigation, forms, modal/counter/search naming and inventory hierarchy. Findings group common causes rather than counting repeated manifestations.

## Inaccessible, partial and superseded probes

- Native iOS runtime/device metadata existed, but Simulator.app was unavailable; Safari open timed out and the screenshot showed only Apple boot. Device restored to shutdown. Android AVD was not exercised. Native mobile Safari, on-screen keyboard, safe areas, permission sheets and browser chrome remain unverified.
- Live assistant/model quality, real clarification decisions, model-to-team escalation and request/offer integration were intentionally not exercised under the paid-model stop. Fixture rendering and fixture replies are not integration passes.
- External map tiles, actual location permission/geolocation and real SMTP delivery were not tested. Synthetic registration used the supported map-center pin control and captured local email.
- Valid whole-stock CSV apply/discard, all inventory edit/expiry/filter permutations, admin rejection/suspension/contest/report mutations, all session-expiry/rate-limit variants and watch stock-arrival notifications remain unverified. Pages were rendered; these workflows are not declared passed.
- Early deletion/watch/request-dialog captures crossed the 992 px remount boundary. Stable-view deletion and live watch flows were rerun successfully; boundary loss remains F-02. Some nominal desktop dialog filenames consequently show a closed sheet—inspect metadata rather than treating filenames as assertions.
- Initial admin-approval selector expected a nonexistent checkbox; corrected direct Approve succeeded. Initial unavailable dialog targeted Today rather than Reservations; corrected fixture and live workflows succeeded. An initially selected watch product was actually stocked, and a read-only search probe used a rejected extra parameter; corrected unstocked catalog/deep-link workflow succeeded. These are audit probe errors, not application findings.
- “stock-loading” fixture ended on an empty stock state; it is retained as a probe observation, not proof of a tested durable loading state. Settled profile/list error captures supersede earlier retry-period screenshots.

The [evidence index](EVIDENCE_INDEX.md) includes early probes for traceability. Final report conclusions use settled/repeated evidence and explicit live/fixture boundaries. No application code was changed to make a scenario reachable.
