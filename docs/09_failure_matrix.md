# DawaLink: Failure Matrix (living)

**Version:** v1.1 (validated; v1.1 adds location, routing and expiry-fit failures) · **Date:** 2026-10-20
**Builds on:** `04` v3.0 (rules, invariants) · `05` v2.0 (locks, clock check) · `06` v1.0 (error codes) · `07` v1.0 (agent limits, guards) · `08` v1.0 (evaluation)
**Status:** ✅ validated 2026-10-20 (decision log §R). It's a **living document**: every PR updates it (Definition of Done #6).

The course requires that *"application teams must maintain a Failure Matrix"* and that systems *"handle incomplete, invalid, unexpected, or malicious inputs and external component failures safely and predictably."* This document lists **every way we know DawaLink can fail**, and for each one:
- how we notice it;
- what the system does;
- what the user sees;
- which test proves it.

The attacker's point of view (assets, threats, mitigations) is in `10` (threat model). This matrix covers **behavior under failure**, including security failures.

---

## In short

- **118 failure modes in 6 groups:**
  - FX: external components (the LLM, email, database, workers…);
  - FA: the agent;
  - FR: races and timing;
  - FI: invalid or ambiguous input;
  - FS: security;
  - FO: operations.
- **Two rules decide every behavior:**
  1. **Fail closed** where people or stock could be hurt (stock, money, safety, privacy): when unsure, don't act.
  2. **Degrade gracefully** where only convenience is lost (the AI, email, tracing): keep everything else working and say so plainly.
- **Every row has a test** in a named folder. Failures are **injected on purpose** in tests (§8): AI down, email down, database cut, worker killed, clock moved.
- **Status per row:** ⏳ designed · 🔨 implemented · ✅ tested. Today every row is ⏳; the build moves them.

---

## 1. Principles

| # | Principle | In practice |
|---|---|---|
| P1 | **Fail closed for stock, money, safety and privacy** | A reservation either fully happens or doesn't (one transaction). A failed check never reserves. A doubtful reply is replaced by a safe template. Unknown access → `404`. |
| P2 | **Degrade gracefully for convenience** | AI down → search, reservations, requests and timers keep working. Email down → in-app notifications still appear. Tracing down → turns still run. |
| P3 | **Everything that waits has a deadline on its row** | The clock check finds anything overdue, even after a crash or restart (`04` R-T10). |
| P4 | **Re-check state before acting** | Every timed action, tap and pharmacy button re-reads the row under a lock. A stale action does nothing. |
| P5 | **Repeating is safe** | Idempotency keys on every creation; one-use proposals; one transaction per change. |
| P6 | **Timeouts everywhere** | LLM 30 s, turn 60/90 s, tools 5 s, database statements 5 s, outbound HTTP 10 s. |
| P7 | **The user always gets a plain message and a next step** | Never a stack trace or a raw code: "Someone reserved this a moment ago." + other options. |
| P8 | **Every failure leaves a trail** | A structured log with `request_id` and `trace_id`; counted in metrics; alerts for the serious ones (`04` R-AL). |

**Severity:**
- **H** (high): wrong stock or money, a safety or privacy breach, or lost data.
- **M** (medium): a feature unavailable, or a user stuck without a clear next step.
- **L** (low): a cosmetic problem or a short delay.

**Test folders** (checklist §6):
- `unit`, `integration`, `api`, `agent`, `failure`, `security`, `regression`;
- `eval` = suite E4 or E6 in `08`;
- `manual` = a demo-day checklist.

---

## 2. FX: external components

| ID | Failure | Detected by | What the system does | User sees | Test | Sev |
|---|---|---|---|---|---|---|
| FX-1 | **LLM provider down** (connection error, 5xx) | Exception after 2 retries (N-36) | Chat: SSE `error`, turn outcome `fallback`. Worker turn: retried at 1/5/15 min (SM-12). Circuit breaker after 3 failures in 5 min (N-38). | "Assistant unavailable. [Use Search]". Requests keep working. | `failure` (fake LLM "down" mode) | M |
| FX-2 | **LLM slow** (no answer in 30 s) | Call timeout (N-35) | Retry once within the turn's 60/90 s budget (N-37); otherwise as FX-1 | "Taking longer than usual…" then as FX-1 | `failure` (fake "slow") | M |
| FX-3 | **LLM rate-limited (429)** | Provider status | Back-off retries (1 s, 3 s); then as FX-1. Counted in `agent_runs.retries`. | Usually nothing; otherwise as FX-1 | `failure` (fake "429") | L |
| FX-4 | **LLM spend reaches the monthly budget** | Sum of `agent_runs.cost_usd` | 80% → alert (R-AL); 100% → **degraded mode for everyone** until raised | "Assistant unavailable" banner; search works | `failure` | M |
| FX-5 | **Local model (Ollama) not running** (development) | Connection refused | Same as FX-1; the startup check logs a clear hint | Developer sees "Start Ollama" in the logs | `failure` | L |
| FX-6 | **Langfuse unreachable** | Send error or timeout | **Tracing is best-effort (FM-D3):** sent in the background; if it fails, it's dropped with a counter. **The turn never fails because of tracing.** `agent_runs` still records everything. | Nothing | `failure` (fake tracer raising) | L |
| FX-7 | **Email (SES) down or throttled** | SES error | Outbox: FAILED → retry 1 m, 5 m, 30 m → DEAD + alert (SM-12). In-app notifications are unaffected. | The in-app notification still appears; the email arrives late or never | `failure` (fake mailer) | M |
| FX-8 | **Email bounces / invalid address** | SES bounce | Marked DEAD; the client sees in-app notifications only | Nothing (in-app works) | `failure` | L |
| FX-9 | **SES sandbox** blocks unverified addresses (demo) | SES error | As FX-7. **Demo accounts prepared**, or production access requested (`02` §7). | Verification email missing in a live demo | `manual` (demo checklist) | M |
| FX-10 | **Database down** | Connection error | API returns `503 SERVICE_UNAVAILABLE`; the worker pauses and retries every 10 s; nothing half-written (transactions) | "DawaLink is temporarily unavailable" | `failure` (stop the database container) | H |
| FX-11 | **Database slow / statement timeout** (5 s) | Statement timeout | Transaction rolled back; API `503` (safe to retry: idempotency); the clock check retries on the next pass | "Please try again" | `failure` | M |
| FX-12 | **Connection pool exhausted** | Pool timeout | Request fails fast with `503`; logged; an alert if repeated. No connection is held during LLM calls (turn lease), so this is unlikely. | "Please try again" | `failure` (tiny pool) | M |
| FX-13 | **Worker process crashes or restarts** | ECS restarts it; clock-check delay metric | Nothing is lost: deadlines live on the rows (P3). The next pass handles everything overdue; each row is handled once (`SKIP LOCKED` + re-check). | At most a short delay | `failure` (kill the worker mid-pass) | M |
| FX-14 | **Clock check falls behind** (> 2 min) | Lag metric | Alert (R-AL); it catches up in deadline order | Offers or expiries a little late (never early) | `failure` | L |
| FX-15 | **API task restarts during a chat stream** | Stream closed | The client's message is already saved; the turn either saved its reply or will be retried by the user | The next poll shows the reply, or a [Retry] | `failure` | L |
| FX-16 | **SSE connection cut** by a proxy or a mobile network | Stream closed | The reply is saved regardless; heartbeat every 15 s keeps idle connections open | The reply appears at the next poll | `failure` | L |
| FX-17 | **Secrets unavailable at startup** | Startup check | The service refuses to start and logs which secret is missing (never its value) | Deploy fails visibly; the old version keeps running | `manual` + deploy check | M |
| FX-18 | **Routing service down, slow or over its free quota** | Error or timeout (N-41) | **Straight-line distance** with an estimated time, labeled "about" (`source = straight`); the cache keeps recent times; alert if it lasts (R-RT1) | Times shown as "about 3 km" | `failure` (fake router) | L |

---

## 3. FA: the agent

| ID | Failure | Detected by | What the system does | User sees | Test | Sev |
|---|---|---|---|---|---|---|
| FA-1 | **Unknown tool** called | Tool router | Returns `UNKNOWN_TOOL` to the model; counted; the model can correct itself | Nothing unusual | `agent` (fake LLM script) | L |
| FA-2 | **Invalid tool arguments** | Pydantic validation | Returns `INVALID_ARGUMENTS` with details; counted | Nothing unusual | `agent` | L |
| FA-3 | **Tool-call loop** (more than 6 calls) | Counter (N-17) | Only `reply` is allowed after the 6th call; the turn closes | A normal (maybe shorter) answer | `agent` | L |
| FA-4 | **No `reply` / malformed final output** | Graph end state | Plain text accepted as the reply (after the output guard); empty → neutral template + this turn's cards | A short answer, possibly the neutral template | `agent` | L |
| FA-5 | **Forged or foreign card ID** in `reply` | Output guard: proposal must exist, belong to this conversation, be open, come from a tool | One repair attempt, then the template; `guardrail_triggered{type: card}` | The cards that are valid, or the template | `agent` | H |
| FA-6 | **Medical advice** in the reply | Output guard: clinical patterns | One repair attempt, then the **clinical refusal template** (`07` §7) | "I can't advise on medicines or doses; a pharmacist or doctor can…" | `agent` + `eval` (E4) | H |
| FA-7 | **Personal data** in the reply | Output guard: email / phone patterns | Repair, then the template | Safe reply | `agent` | H |
| FA-8 | **Wrong language** | Output guard: script check | Repair once; if it still fails, the reply is sent (low risk) and counted | Reply in another language (rare) | `agent` + `eval` (E1) | L |
| FA-9 | **Invented product, price or pharmacy in the text** | Can't be caught by a simple rule. Cards are always correct (rendered from tools). Measured in `eval` (false claims). | Prompt rule 7; cards are the source of truth; regression tests from E1/E4 failures | Text might be wrong; the card isn't | `eval` (E1, E4) | M |
| FA-10 | **False action claim** ("I reserved it") | `eval` check: claim phrases without a matching tool result | Prompt rule 3; measured; failures → regression set | Misleading text; the reservations page shows the truth | `eval` (E4) | M |
| FA-11 | **Prompt injection** in a chat message | Input guard flag | Processed as data; the agent has no harmful tool; flagged for metrics and abuse rules (R-AB) | Normal help continues | `eval` (E4) + `security` | H |
| FA-12 | **Injection through tool data** (e.g. catalog names) | Same | Tool outputs are data; **pharmacy text never reaches the model** (R-AG8) | Nothing | `security` + `agent` | H |
| FA-13 | **Agent asked to act for another client** ("cancel R-001043") | Tool ownership check | `NOT_FOUND` to the model; nothing changes | "I can only see your own reservations." | `security` + `eval` (E4) | H |
| FA-14 | **"Put me first" / emergency claim** | Prompt rule 4 | Emergency template; optional escalation; **the allocation can't change** (no tool or endpoint exists) | Explanation + emergency services + [Talk to a person] | `eval` (E4) + `unit` (allocator) | H |
| FA-15 | **Conversation busy** (another turn holds the lease) | Lease check | Chat: `409 CONVERSATION_BUSY` + auto-retry; worker: waits for the next pass | "One moment…" | `api` + `agent` | L |
| FA-16 | **Lease expires during a very long turn** | Save step checks the lease | The save is refused (no double writes); the turn is retried whole | A short delay | `agent` | M |
| FA-17 | **Worker turn keeps failing** (4 attempts) | `turn_attempts` | Escalate `cannot_resolve` + alert; the request keeps working in code | The request page still updates; a person may reply | `failure` | M |
| FA-18 | **Too many turns on one request** (> 20) | Counter (N-17) | Escalate `cannot_resolve`; no more agent turns for it | "A person from DawaLink will look at this." | `agent` | L |
| FA-19 | **Client's daily AI budget used up** | Input guard | `TOKEN_BUDGET_EXCEEDED`; degraded mode for that client until midnight | "Assistant paused for today. [Use Search]" | `api` + `agent` | L |
| FA-20 | **Event storm** (many events for one conversation) | `pending_turn_at` is one flag | **Coalesced (FM-D5):** one turn reads all new events from the history | One coherent update | `agent` | L |
| FA-21 | **Follow-up outside the window or too frequent** | Tool bounds (N-39) | Tool returns an error code; nothing is scheduled | Nothing | `agent` | L |
| FA-22 | **Stale plan** (listing taken between the card and the tap) | Re-validation at the tap | `NOT_ENOUGH_STOCK` / `GROUP_ITEM_FAILED`; nothing reserved; the agent gets a turn and offers the rest (R-RQ6) | "Aspirin was just taken… Reserve Concor alone?" | `api` + `integration` | M |
| FA-23 | **Expired or reused card** | Proposal `expires_at` / `used_at` | `PROPOSAL_EXPIRED` / `PROPOSAL_USED` | "This option has expired; ask the assistant for fresh options." | `api` | L |
| FA-24 | **Context too long** for the model | Token count before the call | Older messages dropped first (the last 20 are already a cap); the case state is capped at 8 KB (N-33) | Nothing | `agent` | L |
| FA-25 | **The model ignores per-item reporting** | `eval` (E2 check on the first reply) | Prompt + examples; failures → regression set. The request page always shows each item's status (code-owned). | The page is still complete | `eval` (E2) | L |
| FA-26 | **The agent recommends a box that doesn't last, or a closed pharmacy** | Impossible by design: tools only return boxes that fit, with their hours; `propose_reservation` re-checks the fit; the output guard checks the `recommended` card (R-F5) | The proposal is refused with `DOES_NOT_FIT`; the agent picks another | Only valid recommendations | `agent` | M |

---

## 4. FR: races and timing

| ID | Failure | Detected by | What the system does | User sees | Test | Sev |
|---|---|---|---|---|---|---|
| FR-1 | **Two clients tap the last box** | Row lock (`05` §6) | One reservation; the other gets `NOT_ENOUGH_STOCK` (INV-1, INV-12) | "Someone reserved this a moment ago." + options | `integration` (two connections) | H |
| FR-2 | **Double tap / network retry** | Idempotency key | The same result is returned; nothing is duplicated | One reservation | `api` | H |
| FR-3 | **Group reserve: one item fails** | All-or-none transaction | Nothing reserved; `GROUP_ITEM_FAILED`; the agent offers the rest | As FA-22 | `integration` | H |
| FR-4 | **Same client, two tabs, exceeding a limit** | Client row lock | The second fails with `LIMIT_*` (INV-3) | "You have 5 open reservations." | `integration` | M |
| FR-5 | **Price changed between view and tap** | `expected_price_lbp` check | Higher → `PRICE_CHANGED`, nothing reserved; lower → reserved at the lower price (INV-5) | "The price changed to … Reserve at the new price?" | `api` | M |
| FR-6 | **Two offers for the same need accepted at once** | Partial unique + locks (INV-20) | One reservation; the other offer is withdrawn | One confirmation; the other card shows "No longer available" | `integration` | H |
| FR-7 | **Offer accepted just as it expires** | Lock + state re-check | Whoever commits first wins: either reserved, or `OFFER_NOT_OPEN` | Consistent: never both | `integration` | M |
| FR-8 | **Pharmacy presses [Picked up] twice / from two devices** | State re-check | The second gets `RESERVATION_NOT_ACTIVE` ("already picked up") | "Already picked up" | `api` | L |
| FR-9 | **[Picked up] after the deadline** | Deadline check | `PICKUP_DEADLINE_PASSED`; the reservation already expired (no late pickup, SM-5) | "This reservation expired at 21:00." | `api` | M |
| FR-10 | **The clock check and a tap race on the same reservation** | Locks + re-check | Exactly one outcome (picked up or expired) | Consistent | `integration` | M |
| FR-11 | **Upload or edit lowers stock below what's reserved** | R-U3 | Reserved units are kept; warning shown; use [Not available] instead | "1 unit kept for R-1042" | `integration` | H |
| FR-12 | **Matching and a direct reservation at the same moment** | Lock order: clients → items (`05` §6) | No deadlock; one gets the unit | Consistent | `integration` | M |
| FR-13 | **Two matching runs on the same medicine group** | Advisory lock per group | Run one at a time; deterministic allocation (INV-17) | Consistent | `integration` | M |
| FR-14 | **Paused or at-limit client would win a matching hold** | R-PRI3 | Skipped this round; the next claim gets the unit (reason logged) | Nothing for them; the next person gets the offer | `unit` + `integration` | M |
| FR-15 | **Pharmacy accepts early release after the need was covered** | R-E6 check | Ask → WITHDRAWN; nothing locked | Pharmacy: "Thank you, this need was just met." | `integration` | L |
| FR-16 | **Search window ends while an offer is pending** | R-RQ9 | The offer stays valid for its 2 h; the request closes after it's resolved | The offer still works | `integration` | L |
| FR-17 | **Request or watch at night** | Request hours (R-T3, INV-22) | `OUTSIDE_REQUEST_HOURS` with the opening time | "Please come back tomorrow from 08:00." | `api` (07:59, 08:00, 20:00) | L |
| FR-18 | **A box would expire before the chosen pickup day** | The deadline is never after the expiry date (R-T4); the fit is checked at the tap (R-F1) | Such a pickup day is never offered; at the tap → `DOES_NOT_FIT` | Only valid days are shown | `unit` | M |
| FR-19 | **An item's zone changes at midnight** | Derived at read time (R-T9) | Visibility and price follow `today` automatically; matching sweeps | New prices the next day | `unit` (boundaries) | L |
| FR-20 | **Pharmacy has no opening hours in the coming days** | R-F3 | No pickup day can be offered, so the listing can't be reserved for now | "Closed for now" | `unit` | L |
| FR-21 | **DST change in Beirut** | Time-zone database | Business times in Beirut time, stored in UTC; tested around the change dates | Correct times | `unit` | L |
| FR-22 | **Pharmacy suspended with active offers and reservations** | SM-1 | OFFERED → cancelled (requests re-plan); RESERVED kept and can be picked up | "Pharmacy unavailable: we're looking elsewhere" (offers only) | `integration` | M |
| FR-23 | **Client suspended mid-request** | SM-2 | Sessions revoked; open orders cancelled; requests and watches cancelled | Logged out | `integration` | M |
| FR-24 | **Product becomes controlled after a catalog import** | Import script + O6 | Listings hidden; open orders cancelled by the system; claims cancelled | "This medicine is no longer available on DawaLink." | `integration` | M |
| FR-25 | **New price list lowers the public price below an override** | R-C8 | The override is capped at the new public price; existing reservations keep their snapshot | New price on listings | `integration` | L |
| FR-26 | **Out-of-date inventory: the client arrives and there's nothing** | Pharmacy presses [Not available] (O3) | Reservation cancelled for those units; the agent re-plans (request or chat orders); never a client penalty | "Pharmacy A didn't have it after all. Here's another option…" | `integration` + `eval` (E6) | M |
| FR-27 | **The pharmacy forgets to press [Picked up]** after the client really collected the medicine | Deadline passes while still RESERVED | The reservation expires and would count as a no-show. **The client can contest it (FM-D9):** the expiry notice (CN-7) has a [I picked it up] button, which opens an escalation (`complaint`). An admin checks and removes the no-show (lifting a pause if one was set). The pharmacy's dashboard lists "pickups due today" as a reminder, and its stock is corrected with its next edit or upload. | "Expired: did you pick it up? [I picked it up]" | `integration` + `api` | M |
| FR-28 | **A box stops fitting before the tap** (midnight passes, or the client changes the pickup day to tomorrow) | Fit re-checked at the tap (R-F5) | `DOES_NOT_FIT`; nothing reserved; other boxes offered | "This box expires on 21 Oct, before your last day of use." | `api` (time boundaries) | M |

---

## 5. FI: invalid or ambiguous input

| ID | Failure | Detected by | What the system does | User sees | Test | Sev |
|---|---|---|---|---|---|---|
| FI-1 | **Ambiguous medicine** ("augmentin") | The agent (J1) | Asks with chips; never guesses a strength | Chips: [1 g] [625 mg] [457 mg syrup] | `eval` (E1) | L |
| FI-2 | **Unknown or misspelled name** | `search_catalog` empty / `did_you_mean` | Suggests close names; after 2 tries, suggests the Search page | "Did you mean Glucophage?" | `agent` + `eval` (E1) | L |
| FI-3 | **Request mixes logistics and a clinical question** | Agent + output guard | Helps with the logistics, refuses the clinical part | Options + "I can't advise on doses" | `eval` (E1, E4) | H |
| FI-4 | **Unsupported language** (e.g. French) | Agent | **Replies in English (FM-D6)** and continues; Arabic and Arabizi remain the focus | English reply | `eval` | L |
| FI-5 | **Budget in an unexpected currency** (e.g. EUR) | `MoneyIn` accepts LBP/USD only | The agent asks the client to give it in LBP or USD | "Can you give the budget in $ or LBP?" | `agent` | L |
| FI-6 | **Empty, emoji-only or very long message** | API validation | Empty → `422`; > 1,000 chars → `MESSAGE_TOO_LONG`; emoji-only → the agent asks what they need | Clear message | `api` | L |
| FI-7 | **Invalid API payload** (bad types, quantity 0 or 4, 6 items, the same product twice) | Pydantic | `422 VALIDATION_ERROR` with field details | Form errors next to the fields | `api` | L |
| FI-8 | **Controlled product requested** | Catalog filter (R-C6) | Never returned by search; `PRODUCT_NOT_ALLOWED` on direct IDs | "Not available on DawaLink." | `api` + `eval` (E4) | H |
| FI-9 | **Upload: wrong file type, > 5 MB, > 10,000 rows, missing columns, formulas or macros** | SM-4 checks | `UPLOAD_FAILED` / `FILE_TOO_LARGE`; nothing applied | Clear reason + template link | `api` | M |
| FI-10 | **Upload: bad rows** (bad date, negative or non-numeric quantity, past expiry, unmatched product, controlled) | R-U5 | Row errors with "did you mean…"; other rows unaffected | Summary: "13 errors [Download errors]" | `unit` + `api` | L |
| FI-11 | **Upload: duplicate rows, odd encodings, YYYY-MM dates** | R-U1, R-T7 | Duplicates summed; UTF-8/UTF-8-BOM accepted (others → row errors); month-only dates = last day of the month | Correct summary | `unit` | L |
| FI-12 | **Manual add of an existing batch** | Unique key | `ITEM_EXISTS` with the item to edit instead | "This batch exists: edit it instead" | `api` | L |
| FI-13 | **Override above the public price; negative price** | R-PR1 + trigger | `PRICE_ABOVE_PUBLIC` / `422`; the database trigger is a second guard | Clear message | `api` + `integration` | M |
| FI-14 | **Early-release answer with too many units or a too-high price** | R-E6 | `UNITS_INVALID` / `PRICE_ABOVE_PUBLIC` | Clear message | `api` | L |
| FI-15 | **Opening hours that overlap or are invalid** | Service check | `422` with the conflicting range | Form error | `api` | L |
| FI-16 | **Catalog import file malformed** (missing columns, new format) | Import script | Aborts with a report; the old catalog stays (one transaction) | Admins see the import report | `integration` | M |
| FI-17 | **Expired or reused verification link** | R-AU4 | `TOKEN_INVALID` | "This link expired. [Resend]" | `api` | L |
| FI-18 | **Location not shared, or GPS inaccurate** | No coordinates, or accuracy > 1 km reported by the browser | The profile's district is used; times labeled "about"; the client can share again | "Showing times from Hamra. [Use my location]" | `api` | L |
| FI-19 | **Client doesn't know the days of use** | Field empty / the agent asked | 1 day assumed (N-44); every card shows the expiry date with the warning (R-F2) | "Expires 25 Oct: make sure that's enough; the pharmacist can check your prescription." | `api` + `eval` (E1) | L |

---

## 6. FS: security (behavior under attack; the analysis is in `10`)

| ID | Failure | Detected by | What the system does | User sees | Test | Sev |
|---|---|---|---|---|---|---|
| FS-1 | **Password guessing** | Failed-login counter (R-AU2) | Lock 15 min after 5 failures; admins alerted for admin accounts | `ACCOUNT_LOCKED` | `security` | H |
| FS-2 | **Sign-up flood** | Per-network counter (R-AU5) | `SIGNUP_LIMIT` | "Please try again later" | `security` | M |
| FS-3 | **Chat flood / API scraping** | Rate limits (`06` §4) | `RATE_LIMITED` with `Retry-After`; availability capped at 5 (no exact stock) | "Slow down" | `security` | M |
| FS-4 | **Accessing someone else's object** (IDOR) | Ownership check | `404 NOT_FOUND` (INV-8, INV-9) | "Not found" | `security` (each endpoint) | H |
| FS-5 | **Wrong role** (a client calling pharmacy or admin endpoints) | Role check | `403 FORBIDDEN` | "Not allowed" | `security` | H |
| FS-6 | **Cross-site request (CSRF)** | `SameSite=Strict` + `Origin` check | `403 ORIGIN_REJECTED` | Nothing happens | `security` | H |
| FS-7 | **Forged or replayed card** | Proposal owner, expiry, one use, re-validation (INV-21) | `NOT_FOUND` / `PROPOSAL_USED` / `PROPOSAL_EXPIRED` | Nothing happens | `security` | H |
| FS-8 | **Script in a chat message or field (XSS)** | Rendering as text | React escapes everything; chat text is never rendered as HTML; strict security headers (`12`) | The text shows literally | `security` | H |
| FS-9 | **SQL injection** | Parameterized queries (SQLAlchemy) | Treated as plain text | Normal result | `security` | H |
| FS-10 | **Spreadsheet formula injection** in an error report | CSV export | **Cells starting with `=`, `+`, `-` or `@` are prefixed with `'` (FM-D7)** | Safe file | `unit` | M |
| FS-11 | **Oversized payload** | Size limits (64 KB JSON, 5 MB upload) | `413` / `422` | Clear message | `security` | L |
| FS-12 | **Session stolen or reused after logout** | Server-side session check | Revoked sessions → `401`; the cookie is unreadable by scripts (httpOnly) | Logged out | `security` | H |
| FS-13 | **Personal data in logs or traces** | Redaction + log filters | Request bodies aren't logged; messages are redacted before storage and tracing; a scan in `eval` (E6) must find 0 | Nothing | `security` + `eval` (E6) | H |
| FS-14 | **Early-release spam against pharmacies** | Anti-spam (R-E3, R-E5) | Asks skipped; the tool returns the reason | Nothing | `unit` | M |
| FS-15 | **Agent tricked into a consequential action** | Structural: no such tool exists | Nothing can happen; an `audit_events` scan must find 0 agent-made state changes (E6) | Nothing | `security` + `eval` (E6) | H |
| FS-16 | **Demo clock used outside demo mode** | Config flag | `404 DEMO_MODE_OFF` | Not available | `security` | H |
| FS-17 | **Compromised admin account** | Audit log; short sessions (12 h); lockout | Every admin action is audited with a reason; **no admin endpoint can change stock, prices or priority**. Residual risk: 2FA is postponed (P-1); analyzed in `10`. | n/a | `security` + `10` | H |
| FS-18 | **Coordinates leak into AI traffic or traces** | Trace scan (E6) | Location is stored outside `case_state`; tools return minutes and areas only (INV-24); the scan must find 0 | Nothing | `security` + `eval` (E6) | H |

---

## 7. FO: operations, deployment and demo

| ID | Failure | Detected by | What the system does | User sees | Test | Sev |
|---|---|---|---|---|---|---|
| FO-1 | **Migration fails during deploy** | One-off migration task fails | The deploy stops; the old version keeps running; migrations are tested up **and down** in CI | Nothing | CI + `12` | H |
| FO-2 | **Bad release** (errors after deploy) | Health check, error-rate alarm | Roll back to the previous task definition (`12`) | A short disruption at most | `manual` runbook | M |
| FO-3 | **Reconciliation finds stock that doesn't add up** (INV-2) | The daily reconciliation query (`05` §4) | Alert with the item IDs; investigated by hand; regression test added | Nothing | `integration` | H |
| FO-4 | **Retention task fails** | Clock-check daily task error | Retried the next day; alert if 2 days in a row | Nothing | `failure` | L |
| FO-5 | **AWS budget alarm** ($50 / $80) | Budget alerts | The team scales down or destroys test stacks (`12`) | Nothing | `manual` | M |
| FO-6 | **Langfuse deletes traces after 30 days** | Known limit | Evidence exported to `docs/evidence/` after each evaluation run; `agent_runs` keeps the numbers | Nothing | `manual` (export checklist) | M |
| FO-7 | **Live demo: the AI is down or slow** | Demo checklist | Show degraded mode (it's a demo scenario anyway); switch to the recorded backup video for the agent parts | The demo continues | `manual` (demo rehearsal) | M |
| FO-8 | **Live demo: emails don't arrive** | Demo checklist | Pre-verified demo accounts; show the in-app notifications | The demo continues | `manual` | L |
| FO-9 | **Database storage nearly full** | RDS storage alarm | Alert; retention removes old data; increase storage | Nothing | `manual` | L |

---

## 8. Failure injection: how the tests cause failures on purpose

`tests/failure/` uses small **fakes with fault modes**, switched on per test:

| Fake | Fault modes | Used by |
|---|---|---|
| `FakeChatModel` | `down`, `slow`, `rate_limited`, `malformed`, `no_reply`, `unknown_tool`, `bad_args`, scripted replies (e.g. containing a dose or a forged card ID) | FX-1–FX-5, FA-1–FA-10 |
| `FakeMailer` | `down`, `throttled`, `bounce` | FX-7, FX-8 |
| `FakeTracer` | `down`, `slow` | FX-6 |
| Database helpers | stop the container; set a 1 ms statement timeout; a pool of size 1; hold a row lock from a second connection | FX-10–FX-12, FR-1–FR-13 |
| Worker helpers | kill the worker in the middle of a clock-check pass; run two workers at once | FX-13, FX-14 |
| **Test clock** | set and advance `now` (midnight, 07:59/08:00/20:00, DST dates, deadlines) | FR-7, FR-9, FR-17–FR-21 |

Every test asserts **three things**:
1. the response or behavior in the row;
2. **the invariants still hold** (the reconciliation queries of `05` §4 run after every integration and failure test);
3. **the failure left a trail** (a log line with `request_id`, a metric, or an audit event).

---

## 9. Keeping it alive
- **Every PR** that adds or changes behavior **adds or updates rows here** and moves their status (⏳ → 🔨 → ✅ with the test path). This is Definition of Done #6.
- **Every failure found later** (in a test, an evaluation run, a 👎 report or the demo rehearsal) becomes **a new row + a regression test**.
- **Before submission**, every row must be ✅ or explicitly marked as an accepted limitation with a reason. This is the evidence for deliverable D-5 and for the reliability part of the grade (15%).

---

## 10. Decisions

| ID | Decision | Validated | Why |
|---|---|---|---|
| FM-D1 | **Format:** the 6 groups (FX, FA, FR, FI, FS, FO); per row: detection, behavior, what the user sees, test folder, severity; status ⏳ → 🔨 → ✅; updated in every PR | ✅ 2026-10-20 | Required by the course; traceable to tests |
| FM-D2 | **Principles P1–P8**, especially "fail closed" for stock, money, safety and privacy, and "degrade gracefully" for the AI, email and tracing | ✅ 2026-10-20 | One consistent answer to "what happens when X fails" |
| FM-D3 | **Tracing is best-effort:** a Langfuse failure never fails a turn (background sending, dropped with a counter); `agent_runs` always records | ✅ 2026-10-20 | Observability must not reduce availability |
| FM-D4 | **The failure-injection fakes** in §8, and every failure test also checks the invariants and the trail | ✅ 2026-10-20 | Proves "safely and predictably" instead of claiming it |
| FM-D5 | **Event coalescing:** many events for one conversation produce **one** agent turn that reads them all | ✅ 2026-10-20 | Cheaper, and one coherent message instead of five |
| FM-D6 | **Unsupported language** (e.g. French) → the reply is in English, and the agent continues | ✅ 2026-10-20 | Predictable behavior; Arabic and Arabizi stay the focus |
| FM-D7 | **CSV exports are escaped** against formula injection | ✅ 2026-10-20 | A known spreadsheet attack, one line to prevent |
| FM-D8 | **Timeouts everywhere** (P6): database statements 5 s and outbound HTTP 10 s join the agent timeouts → new numbers N-40 (DB statement 5 s) and N-41 (outbound HTTP 10 s) in `04` §5 | ✅ 2026-10-20 | No call can hang forever |

| FM-D9 | **Contesting a no-show:** the expiry notice has an [I picked it up] button that opens a `complaint` escalation; an admin can clear the no-show (new endpoint `POST /reservations/{id}/contest`, and the admin can set `counts_as_no_show = false` with a reason, audited) | ✅ 2026-10-20 | An honest client shouldn't be paused because a pharmacy forgot a button |

**Applied on validation (2026-10-20):**
- N-40 and N-41 are in `04` §5;
- the contest flow is in `04` (R-N3, INV-4), `05` (`orders.contested_at`, trigger exception), `03` (CS-10, CN-7, AS-5) and `06` (two endpoints + `NOT_CONTESTABLE`);
- FM-D1–FM-D9 are recorded in the decision log (§R);
- checklist rows G-6 and T-9 point here.
