# Design Review #2: Everything so far (docs 00–05), before the API

**Reviewed:**
- `Project_Requirements.md` and the proposal;
- `CLAUDE.md`, `README`, `00` decision log;
- `01` v3.0, `02` v1.0, `03` v2.0, `04` v2.0, `05` v1.0;
- `requirements_checklist.md`;
- ADR-001–003 and design review #1.

**Questions asked:**
1. Does the plan satisfy every course requirement?
2. Do the documents agree with each other?
3. Will the designed system actually work end to end (state machines, concurrency, timers, the agent loop, the evaluation, the deployment)?
4. Is it still simple enough for a three-person Python team?

**Date:** 2026-10-13 · **Status:** ✅ **closed.** The team answered §A with a simplification (see "Team decisions on §A") and accepted §B, §C and §D. Applied to `01` v4.0, `02` v2.0, `03` v3.0, `04` v3.0, `05` v2.0, ADR-001/002/003 (amended), the checklist and decision log §N.

---

## Verdict

**The design is sound, and no redesign is needed.**
- Every course requirement maps to a planned artifact.
- The agent's role is clearly justified.
- The split between agent, code and humans holds everywhere.

**The review found:**
- **12 correctness gaps** in the rules and the schema (§A). Most would show up as real bugs the first time the sourcing agent runs a request with early release in parallel, which is our main demo scenario. They should be fixed before step 06, because the API is built directly on them.
- **9 items** for later steps (§B). The most valuable is adding a **no-LLM baseline** to the evaluation (B6).
- **Document inconsistencies** to clean up (§C).
- **3 requirements or process risks** (§D).

### What is strong and should stay

| Strength | Why it matters for grading |
|---|---|
| Taps execute, the agent proposes; no tool creates orders (INV-11) | "Human approval for consequential actions" is enforced by design, not by prompt |
| Priority is a fixed rule (ADR-003) | A clear, testable answer to "what must stay deterministic"; a red-team case with a pass/fail result |
| One Postgres for data, jobs, outbox and audit | Transactions cover state + timer + notification together |
| `today` injected everywhere; a simulated clock | Makes the time-based evaluation possible at all |
| Agent metrics in our own tables (DB-D8) | Cost per fulfilled request survives Langfuse's 30-day limit |
| Requirements checklist + Definition of Done | Compliance is built into every PR |

---

## A. Fix before step 06 (they change rules or tables)

### A1 · High: stock can expire before the client needs it
- **Where:** `04` R-RQ5, R-PRI, SM-7 and the `find_options` / `plan_basket` tools. Only early release (R-E2) checks `expiry − 14 days ≥ need-by`.
- **What goes wrong:**
  - A client needs Concor by a date 50 days away.
  - A listing with 23 days left is planned, reserved and picked up.
  - It expires 27 days before the client needs it.
  - The evaluation would still count this as "fulfilled before need-by".
- **Fix:** one rule, **R-C10 "usable at need-by"**. Whenever a need has a need-by date (claims, request items, early release, a chat need with a date), only stock with `expiry_date − 14 days (N-2) ≥ need_by` qualifies.
  - It's one SQL predicate, used by matching, `plan_basket`, `find_options` and early release.
  - It matches what R-E2 and the prescription rule already do.

### A2 · High: two offers for the same need break the client limits
- **Where:** RF-1 deliberately runs early release **and** watching in parallel for the same item. In chat, AF-8 can do the same (a watch plus early release).
- **What goes wrong:**
  - Both paths can create an OFFERED hold for one need.
  - OFFERED counts as an open order, so 3 + 3 units in the same group breaks R-L2 / INV-3.
  - The client can also get two offers for one need, and accepting the second leaves the first holding stock.
- **Fix: the claim is the single "need" object.**
  - `early_release_requests` point to a **claim**, replacing `request_item_id` with `claim_id`. In chat, the agent's early release uses (or creates) a watch claim.
  - Each path may hold **at most one offer per claim**. **Accepting one withdraws the others**: extend O14's rule to O13.
  - **For the limits, a claim's simultaneous offers count once.**
  - Once the need has a PENDING or CONFIRMED order, matching stops offering to it, and its open asks are **withdrawn** ("no longer needed", no penalty for the pharmacy). If that order fails, the decision event re-plans as today.

### A3 · Medium: request items have no rules after confirmation
- **Where:** `04` SM-8, INV-18.
- **What goes wrong:**
  - INV-18 says "SECURED ⇔ has a CONFIRMED order". It becomes **false right after a normal pickup**, because the order moves to PICKED_UP.
  - Nothing says what happens to the item on a no-show, or when the pharmacy releases the reservation.
  - PARTLY_SECURED (1 of 2 confirmed) has no way to source only the missing unit.
- **Fix:**
  - Items track `qty_secured`. **SECURED ⇔ units in CONFIRMED or PICKED_UP orders ≥ qty.**
  - Picked up → the item stays SECURED.
  - No-show → CANCELLED (reason: missed pickup; no automatic re-sourcing).
  - Released by the pharmacy ("other") → SEARCHING, as a decision event.
  - Client asked the pharmacy to cancel → CANCELLED.
  - PARTLY_SECURED keeps its confirmed units and sources only the missing ones.

### A4 · Medium: a request can close while an order is still waiting for the pharmacy
- **Where:** `04` R-RQ8 closes the request at the end of the need-by day.
- **What goes wrong:** an item may still be ORDERED at that moment. The outcome is computed too early, and a confirmation that arrives later updates nothing.
- **Fix:**
  - At the end of the need-by day, open offers are withdrawn.
  - Closing then **waits until no item is ORDERED**. This is bounded: at most 2 h of opening time.
  - Only then is the outcome computed.

### A5 · Medium: matching never runs when a claim starts
- **Where:** `04` R-PRI1 and R-T8. Matching is triggered only by stock events, and the daily job only looks at "items that entered the window today".
- **What goes wrong:**
  - A claim that is created, or that becomes ACTIVE, never sees stock that's **already** visible. This breaks the late-prescription watch (R-W4: it becomes active at P − 5 days, while suitable stock may have been listed all along).
  - If the daily job misses a day, items that entered the window that day are never matched.
- **Fix: matching runs**
  - **(a)** when a claim is created or becomes ACTIVE;
  - **(b)** on any change that can make a listing visible or cheaper (resume, reinstate, manual edit, price override);
  - **(c)** in a **daily sweep of all ACTIVE claims**, instead of "entered today". The sweep is idempotent thanks to `claim_skips`.

### A6 · Medium: matching takes locks in the wrong order and doesn't check the winner's limits
- **Where:** `05` §6. Matching locks the item and then creates offers.
- **What goes wrong:**
  - The winning claim's client must be ACTIVE and within R-L1/R-L2, and checking that needs the **client row lock**.
  - The global lock order puts client rows **first**, so locking them after the item risks a deadlock with a concurrent reservation.
  - Today nothing checks those limits at all, so offers can break INV-3.
- **Fix:**
  - Matching takes the advisory lock, loads the candidate claims, locks their clients (sorted), then locks the items (sorted), then allocates.
  - Claims whose client is not ACTIVE, or is at a limit, are **skipped** for this round, with the reason logged.

### A7 · Medium: a group reserve collides with the idempotency constraint
- **Where:** `05` orders: `UNIQUE (client_id, idempotency_key)`.
- **What goes wrong:** a group reserve inserts several orders under one key, so the second insert fails.
- **Fix:** `UNIQUE (client_id, idempotency_key, inventory_item_id)`. A retry still finds "the existing orders" by key.

### A8 · Medium: a crashed job stays RUNNING forever
- **Where:** `05` §6. The runner selects only QUEUED and FAILED jobs.
- **What goes wrong:**
  - The worker runs on Fargate **Spot** and can be stopped at any moment.
  - A job marked RUNNING at that moment is never picked up again, so timers (order timeouts, pickup expiries) silently stop.
  - That breaks INV-14 and the checklist's "worker crash and resume" test.
- **Fix:**
  - A **lease**: a RUNNING job whose `locked_at` is older than 5 minutes goes back to QUEUED, and the attempt is counted.
  - Test: kill the worker in the middle of a job; the job completes after the restart.

### A9 · Medium: the database clock bypasses the simulated clock
- **Where:**
  - DB-D6 covers `today`.
  - But the job runner uses `run_at <= now()`.
  - And `created_at` defaults to the database's `now()`. It is the 3rd priority key, and retention uses it too.
- **What goes wrong:** with a fast simulated clock, timers and priority ties follow **real** time, so evaluation runs silently diverge from the model.
- **Fix:** one rule. **Every time that drives business logic comes from the app clock** (a `:now` parameter): job selection, `created_at` on claims, orders and requests, timers, retention. Database defaults remain only as a fallback for logs.

### A10 · Low–Medium: the emergency override only works for requests
- **Where:** the override columns live on `sourcing_requests`.
- **What goes wrong:** a client in chat with a watch (AF-26: "I'm dying, put me first") can't be prioritized by an admin.
- **Fix:**
  - Move the override to **`claims`**. A request-level override sets it on all of the request's item claims.
  - Matching then reads only `claims`.

### A11 · Low–Medium: "widen the area" has nowhere to be stored
- **Where:** RF-6, CS-16 and the `propose_constraint_change` example ("allow 15 km?"), while requests only store a district.
- **Fix:**
  - Add `max_distance_km` on requests and claims, defaulting to 20 km (N-23). Widening raises it, with a tap.
  - Fix the "15 km" examples to match.

### A12 · Low: small rule gaps
| # | Gap | Fix |
|---|---|---|
| a | SM-8 lets the agent "conclude an item is impossible" (→ UNAVAILABLE), but no tool does that | Drop it. Items become UNAVAILABLE only at need-by. The agent can *propose* removing an item (a tap). |
| b | Unticked items in a reserved plan card have no rule | They return to SEARCHING, and the agent gets a turn (a decision event) |
| c | A second escalation while one is open hits the one-open-per-client constraint | It's appended to the open escalation |
| d | R-T4: around closed days, the pickup deadline can pass the "14 days left at pickup" guarantee | Cap every deadline at the closing time on (expiry − 14 days) |
| e | Which thread receives events isn't defined per order source | Search orders get notifications only (**never an agent turn**, which keeps the baseline agent-free); assistant orders go to the active chat; request orders go to the request thread; agent-created watches go to the chat |

---

## B. Handle in the coming steps

| # | Step | Finding | Recommendation |
|---|---|---|---|
| **B1** | 06, 07 | **Card integrity.** If the LLM writes card text or button data, an injected or confused model could show "Reserve 1 box" on a button that does something else. | **Cards are created only by tools** and stored server-side as proposals. The LLM chooses which proposal IDs to show; the tap sends the proposal ID; the API re-validates everything. |
| B2 | 07, 10 | Free text written by **other parties** (pharmacy decline notes, upload fields) is an injection path into the agent. | Tools return enums, numbers and IDs only. Other parties' free text never reaches the LLM. |
| B3 | 06 | It isn't defined how worker-posted cards reach an open chat or request page, or what the chat API does while a worker turn holds the conversation. | **Polling every few seconds** for new messages (simple); SSE only for streaming a reply. If a turn is running, "one moment…" with an automatic retry. |
| B4 | 06 | **Auth is more complex than needed.** JWT + refresh rotation + family revocation, and a suspended user keeps access for up to 15 min. | *(Optional, recommended)* **Server-side sessions:** one opaque httpOnly cookie + a `sessions` table. Less code, and logout and suspension take effect instantly. Replaces `refresh_tokens`. |
| B5 | 07 | The agent-turn lock is a session advisory lock, so a DB connection stays held through every LLM call. | *(Optional, recommended)* A **lease row** on `conversations` (`turn_lease_until`): it holds no connection, expires on its own after a crash, and is easier to test. |
| **B6** | 08 | **The evaluation can't yet show what the LLM adds over a workflow.** The baseline (search + [Notify me]) has no early release, so the agent "wins" partly because it has a supply channel the baseline doesn't. | Add a **no-LLM scripted sourcing policy** that uses the same tools (always plan, always ask early release, fixed re-plan rules). Compare all three: baseline → scripted policy → agent. Also: run several trials per setup and report the spread; define success as "**secured** by need-by" (report pickups separately); test the simulation's pharmacy behavior across a range of values. |
| **B7** | 12 | **Networking.** (1) With no NAT gateway, Fargate tasks in private subnets can't reach the Anthropic API, Langfuse, ECR or Secrets Manager. (2) With no certificate, CloudFront → ALB is **plain HTTP over the internet**, so session cookies and passwords travel unencrypted on that hop. | Tasks in **public subnets with public IPs**, with inbound traffic allowed only from the ALB. A **CloudFront VPC origin** with an **internal ALB**: traffic stays inside AWS, and no secret header is needed. *(Alternative: a cheap domain + a free ACM certificate.)* |
| B8 | 12 | The SES sandbox only sends to verified addresses: a grader signing up live won't receive the verification email. At about $55–65 a month, deploying early uses most of the $100 credit. | Pre-created demo accounts, or request SES production access early. Short test deploys then `cdk destroy`; the final stack deployed close to the demo. Worker on regular (not Spot) Fargate for demo day. |
| B9 | 06, demo | The demo needs timeouts and need-by checks to happen live (D-1 "fast clock"). | An admin-only **"advance clock"** control, enabled only in demo mode. The injected clock already makes this possible. |

---

## C. Document consistency fixes (no decision needed)

| Where | Problem | Fix |
|---|---|---|
| `00` rows D3, D4, P-D1, P-D4, A-D2, A-D9, S7, G6, T3 | Still read as current, but were changed by §K, AF-3 or T13. **`CLAUDE.md` loads this log in every session**, so a new session could build 2FA or password reset. | Add "superseded by …" to each row |
| `requirements_checklist` | D-1 says "15 scenarios" (there are 12); T-1 says "one assistant"; T-3 memory omits request threads; T-6 points to SM-11 (it's SM-12) | Correct them |
| `01` C14, `03` AS-2, `04` O6 | "packs saved" | → "units saved" |
| `02` §3.2, `03` CS-16 | "allow 15 km" examples | Align with A11 |
| `03` PS-9 | "suggested −40%" for early release has no rule behind it | Suggest the mildest tier (25%); these items are furthest from expiry |
| `03` PS-1, PS-10 | "Responsible pharmacist" and "notification email" have no column in `05` | Drop both (the account email is used) |
| `02` §4, §6 vs `05` §9 | Upload staging rows not mentioned; scripts and data paths differ | Align (`backend/scripts/`, `backend/data/`) |
| `01` §6 | The professor asks for edge cases in the demo | Add two quick ones: a messy upload with row errors, and two clients racing for the last box |

---

## D. Requirements and process risks

| # | Risk | Recommendation |
|---|---|---|
| **D1** | The course text says healthcare projects **aren't accepted**. Our professor proposed DawaLink, but other graders read the same rules. | Keep **written proof** (his email or message), cite it in the report, and keep the logistics-only framing everywhere. *Dropped by the team (2026-10-18): the proposal and poster phase is complete.* |
| **D2** | The requirements "strongly encourage" grounding the problem with real users, and we have none yet. Our simulation's pharmacy behavior is currently guessed. | **Short interviews with 2–3 pharmacists** (and a few clients). They would back the problem statement, check our assumptions (do pharmacies track batch expiry? answer an ask within 4 h? upload weekly?) and give real numbers for the simulation. *Dropped by the team (2026-10-18): the proposal and poster phase is complete.* |
| D3 | **Scope vs the one fixed date** (30 tables, three portals, two agent modes, a simulation, AWS). No deadlines, but worth stating once. | Two changes that cost nothing: (1) build **agent-first vertical slices**, so the graded core (agent, evaluation, observability, tests) exists early and platform screens come last; (2) write `09` and `10` as short skeletons now and grow them with each PR (they're living documents anyway). |

---

## Team decisions on §A (2026-10-13, ✅ closed)

The team answered §A with a **simplification**. These decisions replace DR2-1–DR2-7 below.

| Finding | Team decision | What it means |
|---|---|---|
| A1, A4 | **Needs are urgent.** No need-by date and no 60-day horizon. A request or watch searches for **6 hours**, then stops and reports. **Requests and watches can't be started at night:** "come back tomorrow" (hours in `04` §5, proposed 08:00–20:00). | A1 is solved without a new rule: pickup within ≤ 3 days and ≥ 17 days left at listing gives ≥ 14 days at pickup. The "need-by in 2 days" check becomes "1 h before the 6 h end". Early-release asks go only to pharmacies open now, with 2 h to answer. |
| A1, A3 | **Each pharmacy sets its pickup time (1–3 days, until closing time).** Not picked up → back to stock automatically. **Default: 1 day** (until closing time on the next day the pharmacy is open). | Replaces the 48 h rule and the prescription extension. |
| A2 | **The first accepted offer wins; the others are cancelled immediately.** | Simultaneous offers for one need count once for the limits; asks are withdrawn once the item is reserved. |
| A3 | **A [Picked up] button on the pharmacy side.** If a pharmacy has only 1 of 2 boxes, the agent searches other pharmacies for the 2nd. | The secret pickup code, code entry and the lockout are removed; the client shows the order number. Plans may split one medicine's quantity across pharmacies. |
| A5 | **Prescription = a notice only** ("bring it to the pharmacy"). Pharmacies keep their quantities current by editing them. | R-P1, prescription statements, the deadline extension and the late-prescription watch are removed. Every stock edit triggers matching. |
| A6 | Fix as proposed | Matching locks clients first; it skips paused clients and clients at a limit. |
| A7 | **One receipt number per order** in a group | Each order in a group reserve has its own idempotency key. |
| A8 | **Regular Fargate, no Spot.** **No pharmacy confirmation step (option 1):** the tap reserves immediately. | The pharmacy is notified (screen + email) and puts the box aside. If it isn't there, the pharmacy presses **[Not available]** for all or some units: the reservation is cancelled for those units, the client is told, and the agent searches again. The confirmation countdown and opening-time counting are removed. |
| A9 | `created_at` in real time; **remove the jobs table** | Accepted: `created_at` only orders "who came first". Every time limit is computed from the app clock. The jobs table is replaced by **one "clock check" loop** that finds overdue rows every minute (deadlines live on the rows). |
| A10 | **Admins can't set priority.** | The priority rule becomes **first come, first served** (still code, never the LLM). The override is removed. Emergency claims: explain, point to emergency services, optional human help. |
| A11 | **District only:** same district first, other places as other choices | Same district → same governorate → rest of Lebanon. No km, no coordinates, no "widen the area" tap. |
| A12 | Accepted | Items become UNAVAILABLE at the end of the 6-hour window. |

These **supersede** earlier validated decisions:
- R-D21, AF-5 and ADR-003 (need-by priority and the admin override);
- G5 (prescription timing);
- the pickup code (R-PC);
- the 60-day need-by horizon (N-11);
- S6 (every order confirmed by the pharmacy).

They'll be marked in the decision log.

---

## Final decisions

| ID | Decision | Outcome |
|---|---|---|
| DR2-1 | A1: "usable at need-by" rule | **Replaced** by the team's simplification: needs are urgent (6-hour window), so it isn't needed (decision log DR2-A1) |
| DR2-2 | A2: the claim is the single need; the first accepted offer wins | ✅ Accepted (DR2-A7) |
| DR2-3 | A3 + A4: request items after confirmation; closing | ✅ Accepted in a simpler form: instant reservations, [Picked up] / [Not available], offers valid after the window ends (DR2-A2, A4, A6) |
| DR2-4 | A5 + A6: matching triggers, lock order, skipping ineligible clients | ✅ Accepted (DR2-A11) |
| DR2-5 | A7 + A8 + A9: idempotency, stuck jobs, app clock | ✅ Accepted in a simpler form: one key per order; **no jobs table** (a clock check); `created_at` in real time (DR2-A10, A12) |
| DR2-6 | A10 + A11: override on claims; `max_distance_km` | **Replaced:** nobody can set priority; district-only area order (DR2-A8, A9) |
| DR2-7 | A12 a–e: small rule gaps | ✅ Accepted (DR2-A13) |
| DR2-8 | B1 + B2: cards only from tools; no pharmacy free text to the LLM | ✅ Accepted (DR2-B1, B2) |
| DR2-9 | B4 + B5: server-side sessions; turn lease | ✅ Accepted (DR2-B4, B5) |
| DR2-10 | B6: the no-AI scripted baseline and evaluation hygiene | ✅ Accepted (DR2-B6) |
| DR2-11 | B7: public-subnet tasks + CloudFront VPC origin | ✅ Accepted (DR2-B7) |
| DR2-12 | §C document fixes | ✅ Applied (DR2-C) |
| (team) | D1 approval proof · D2 pharmacist interviews · D3 build order | D1 and D2 **dropped** by the team (2026-10-18, decision log DR2-E3); D3 kept (`02` §9) |
