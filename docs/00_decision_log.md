# DawaLink: Decision Log and Validation Checklist

**Purpose:** every decision taken so far, in one place, so the team can validate them together before each next step. Each line links to where it is specified. **Rows marked *superseded* or *postponed* are history: follow the section they point to.**

**How to validate:** go section by section. Tick ✅ in the **Validated** column, or write the change.

**Repository:** https://github.com/Mohammed-Farhat/Dawa_Link (public)

**Status of this log:** 2026-10-18, covers steps 01–06 and design review #2. Sections A–F and I–O validated by the team (2026-10-13 to 2026-10-18). §G is superseded by `04` §5; §H is open.

---

## A. Project and scope

| ID | Decision | Where | Validated |
|---|---|---|---|
| S1 | Path A (application). Logistics-only boundary: no clinical functions. Topic proposed and approved by the professor. | 01 §1 | ✅ 2026-10-13 |
| S2 | Goal: connect clients who can't afford full price with pharmacies selling near-expiry stock at a discount. | 01 §1 | ✅ 2026-10-13 |
| S3 | Users: client, pharmacy, admin, plus the DawaLink Assistant (agent). | 01 §2 | ✅ 2026-10-13 |
| S4 | Marketplace model: clients browse and reserve online, **pay at the counter**. No online payment, no delivery. | 01 §3, §8 | ✅ 2026-10-13 |
| S5 | Pharmacies upload their **full inventory** (only after approval). Items in the near-expiry window are published automatically; the rest stays **private**. | 01 C3–C4 | ✅ 2026-10-13 |
| S6 | ~~**Every order is confirmed by the pharmacy**. Unanswered orders auto-cancel.~~ *Superseded by §N (DR2-A2): reservations are instant; the pharmacy marks [Picked up] or [Not available].* | 01 C7 | ✅ superseded (§N) |
| S7 | **One main agent: the client assistant.** Chat with cards and buttons, Arabizi OK. No Telegram; no pharmacy-side agent as the main agent. *Extended by §K AF-3: one agent, two modes (assistant + sourcing).* | 01 C6 | ✅ 2026-10-13 (extended) |
| S8 | A normal **search page** is kept next to the chat: non-chat UI, evaluation baseline, and fallback. | 01 C5 | ✅ 2026-10-13 |
| S9 | **Early release:** the agent can ask pharmacies to release privately held stock. **Watches:** notify clients when stock appears. | 01 C8–C9 | ✅ 2026-10-13 |
| S10 | Notifications by **email (SES) + in-app**. WhatsApp later (A1). All templates; the LLM never writes emails. | 01 C10 | ✅ 2026-10-13 |
| S11 | **No internal deadlines.** We finish when every requirement is satisfied. The only fixed date is the live demo (Nov 30). *(Changed by the team on 2026-10-13; it replaces "core by Oct 31".)* | 01 header | ✅ 2026-10-13 |
| S12 | Add-ons in priority order: WhatsApp, smart inventory import, pack splitting, box-photo recognition, basket optimization, trust score, impact dashboard, Arabic UI. *Basket optimization was promoted to the core (§K AF-2).* | 01 §7 | ✅ 2026-10-13 (updated) |
| S13 | Out of scope: clinical functions, online payment, delivery, mobile apps, controlled substances, opened or expired packs, real-time POS integration, prescription upload or reading. | 01 §8 | ✅ 2026-10-13 |

## B. Architecture and process

| ID | Decision | Where | Validated |
|---|---|---|---|
| T1 | Backend **Python 3.12 + FastAPI**; frontend **React + TypeScript + Mantine**. | 02 §1 | ✅ 2026-10-13 |
| T2 | **PostgreSQL** + SQLAlchemy (sync) + Alembic migrations. | 02 §1 | ✅ 2026-10-13 |
| T3 | Agent framework **LangGraph** (+ langchain-anthropic). *The model is chosen by measurement (T13, O1).* | 02 §1 | ✅ 2026-10-13 (updated) |
| T4 | Worker process ~~+ Postgres job table~~. *Updated by §N (DR2-A10): one **clock check** loop reads the deadlines stored on the rows; no jobs table.* | 02 §1 | ✅ 2026-10-13 (updated by §N) |
| T5 | Chat over **SSE** streaming. | 02 §1 | ✅ 2026-10-13 |
| T6 | Auth: ~~JWT in an httpOnly cookie~~ **server-side sessions** (§N DR2-B4), argon2, rate limits, email verification. *(Admin TOTP 2FA and password reset postponed by §K.)* | 02 §1 | ✅ 2026-10-13 (updated by §K, §N) |
| T7 | ~~Private S3 for license documents and raw uploads~~ → **no file storage**: uploads are processed in memory and discarded (license upload postponed, §K) | 02 §1 | ✅ 2026-10-13 (updated by §K) |
| T8 | Tracing with **Langfuse**; JSON logs to CloudWatch. | 02 §1 | ✅ 2026-10-13 |
| T9 | AWS: **ECS Fargate + ALB + one CloudFront + S3 + RDS + SES**, no NAT, built with **CDK (Python)**, budget alerts at $50 / $80, destroyed after the demo. *Updated by §N (DR2-B7): internal ALB via a CloudFront VPC origin; tasks in public subnets; regular Fargate, no Spot.* | 02 §7 | ✅ 2026-10-13 (updated by §N) |
| T10 | CI/CD: GitHub Actions (OIDC), CodeQL, Dependabot, Trivy, offline eval gate. | 02 §1, §8 | ✅ 2026-10-13 |
| T11 | **Claude writes the code; every change goes through a PR the team reviews and can explain.** | 02 §9 | ✅ 2026-10-13 |
| T13 | **LLM by stage:** automated tests and CI use a **fake, scripted LLM** ($0). Day-to-day development uses a **local model** via Ollama (`qwen2.5:7b`, already installed). Evaluation and the demo use the real model chosen by measurement; the local model is one of the candidates. | 02 §1 | ✅ 2026-10-13 |
| T12 | **Buttons call the API directly.** The assistant only proposes; it never executes consequential actions. | 02 §3.1 | ✅ 2026-10-13 |

## C. Agent rules

| ID | Decision | Where | Validated |
|---|---|---|---|
| G1 | **Tools = code the agent calls** (they validate and execute). **Automatic code** (timers, emails, stock locks) runs without the agent. | 02 §3.2 | ✅ 2026-10-13 |
| G2 | The agent never sees names, phone numbers or emails; it acts only with the logged-in client's permissions. | 01 C6, C13 | ✅ 2026-10-13 |
| G3 | **No medical advice**: fixed refusal + referral to the pharmacist, backed by an output check. | 01 C6, 03 AF-14 | ✅ 2026-10-13 |
| G4 | Alternatives: **same composition only** (ingredient + strength + form), only with the client's consent. | 01 §1, 03 AF-13 | ✅ 2026-10-13 |
| G5 | ~~**Prescription rule:** the agent asks when the client will have the prescription; code refuses or extends the deadline.~~ *Superseded by §N (DR2-A5): a prescription is a **notice** only; the pharmacist checks it at the counter.* | 04 R-P1 | ✅ superseded (§N) |
| G6 | Memory: one conversation thread per client (kept 30 days); preferences as structured profile fields; everything else read through tools. *Extended: each sourcing request has its own thread (ADR-002), plus a case state (ADR-001).* | 02 §3.3 | ✅ 2026-10-13 (extended) |
| G7 | Client can ask for a **human** (escalation → admin replies as "DawaLink team"). | 03 AF-21 | ✅ 2026-10-13 |
| G8 | 👎 on any reply → admin review → confirmed problems become **regression tests**. | 03 CS-9, AS-8 | ✅ 2026-10-13 |
| G9 | **Degraded mode:** if the LLM is down or over budget, "use Search"; everything else keeps working. | 01 C15 | ✅ 2026-10-13 |

## D. Client-side decisions

| ID | Decision | Where | Validated |
|---|---|---|---|
| D1 | Login required to search | 03 §1.10 | ✅ 2026-10-13 |
| D2 | Email verification before reserving | 03 §1.10 | ✅ 2026-10-13 |
| D3 | Password reset by email | 03 §1.10 | ⏸ postponed (§K) |
| D4 | "Delete my account" in the core | 03 §1.10 | ⏸ postponed (§K) |
| D5 | No pickup extension. *Updated by §N: the pharmacy's pickup time applies, with no prescription exception.* | 03 §1.10 | ✅ 2026-10-13 (updated) |
| D6 | [Notify me] (watch) on the search page too. *A 6-hour watch since §N.* | 03 §1.10 | ✅ 2026-10-13 |
| D7 | Availability shown exactly up to 5, then "5+" | 03 §1.10 | ✅ 2026-10-13 |
| D8 | Assistant mirrors the client's language; UI labels in English | 03 §1.10 | ✅ 2026-10-13 |
| D9 | One active chat + [New chat]; archives kept 30 days | 03 §1.10 | ✅ 2026-10-13 |
| D10 | Mobile-first client portal | 03 §1.10 | ✅ 2026-10-13 |

## E. Pharmacy-side decisions

| ID | Decision | Where | Validated |
|---|---|---|---|
| P-D1 | License document upload at registration (private, admin-only) | 03 §2.7 | ⏸ postponed (§K) |
| P-D2 | Inventory, listings and policy **only after approval** (team decision) | 03 §2.7 | ✅ 2026-10-13 |
| P-D3 | ~~Partial confirmation~~ → *partial **[Not available]** (§N)* | 03 §2.7 | ✅ superseded (§N) |
| P-D4 | Auto-publish ~~by default, with a manual-queue option~~ → *always on (§K)* | 03 §2.7 | ✅ 2026-10-13 (updated by §K) |
| P-D5 | One account per pharmacy (no staff accounts yet) | 03 §2.7 | ✅ 2026-10-13 |
| P-D6 | Pharmacies never see client identity (order ref only) | 03 §2.7 | ✅ 2026-10-13 |
| P-D7 | Free ($0) listings allowed | 03 §2.7 | ✅ 2026-10-13 |
| P-D8 | ~~Order countdown runs during opening hours only~~ *Removed by §N: no confirmation step, so no countdown.* | 03 §2.7 | ✅ superseded (§N) |
| P-D9 | ~~Refused-handover rules~~ *Removed by §N: the pharmacist's own process at the counter; the client can cancel without penalty.* | 03 §2.7 | ✅ superseded (§N) |
| P-D10 | Pharmacy portal desktop-first; orders and pickup also work on phones | 03 §2.7 | ✅ 2026-10-13 |

## F. Admin-side decisions

| ID | Decision | Where | Validated |
|---|---|---|---|
| A-D1 | Admin accounts created from the command line only | 03 §3.5 | ✅ 2026-10-13 |
| A-D2 | Two-factor login for admins | 03 §3.5 | ⏸ postponed (§K) |
| A-D3 | Admins can view client contact details for support; every view audited | 03 §3.5 | ✅ 2026-10-13 |
| A-D4 | Admins read chats only for escalated or reported cases, redacted | 03 §3.5 | ✅ 2026-10-13 |
| A-D5 | Clients can ask for a human | 03 §3.5 | ✅ 2026-10-13 |
| A-D6 | 👎 reports → regression tests | 03 §3.5 | ✅ 2026-10-13 |
| A-D7 | Admins can't edit pharmacy stock, prices or private inventory | 03 §3.5 | ✅ 2026-10-13 |
| A-D8 | Rules, model and prompts change only via config and deploy (read-only in the UI) | 03 §3.5 | ✅ 2026-10-13 |
| A-D9 | ~~Admins maintain the catalog~~ → *import script + team files; read-only admin view (§K)* | 03 §3.5 | ✅ 2026-10-13 (updated by §K) |
| A-D10 | Admins can reply to escalated clients in short free text (audited) | 03 §3.5 | ✅ 2026-10-13 |

---

## I. Domain-rule decisions (step 04)

| ID | Decision | Where | Validated |
|---|---|---|---|
| R-D1 | Prices **stored in LBP** and **always shown in LBP + ≈ USD**; client budgets accepted in either currency | 04 §2, §8 | ✅ 2026-10-13 |
| R-D2 | **Prescription required by default** + admin-maintained OTC list (option A) | 04 §2, §8 | ✅ 2026-10-13 |
| R-D3 | Conservative "same medicine" groups (coating variants only; XR ≠ normal) | 04 §2, §8 | ✅ 2026-10-13 |
| R-D4 | **Controlled substances removed from the platform entirely**, flagged from the MoPH Narcotics lists | 04 §2, §8 | ✅ 2026-10-13 |
| R-D5 | Pack size optional | 04 §2, §8 | ✅ 2026-10-13 |
| R-D6 | Month/year expiry = last day of the month | 04 §1, §8 | ✅ 2026-10-13 |
| R-D7 … R-D19 | Time, deadlines, limits, anti-abuse, uploads, watches: see `04` §8. *Partly superseded by §N (time, prescription, pickup and confirmation rules); `04` v3.0 wins.* | 04 §8 | ✅ 2026-10-13 (partly superseded) |

## J. Design review #1 decisions

| ID | Decision | Where | Validated |
|---|---|---|---|
| DR-1 | **Conversation state lives in our tables; LangGraph is stateless per turn; one turn at a time per conversation; informational events post template cards (no LLM)** | `adr/ADR-001`, 02 §3, 04 R-AG | ✅ 2026-10-13 |
| DR-2 | Eligibility zone and policy price **derived at query time**, never stored | 04 R-T9 | ✅ 2026-10-13 |
| DR-3 | A declined or expired early-release offer **returns the item to private** (no "keep listed" option) | 04 R-E6/O15, 03 PS-9 | ✅ 2026-10-13 |
| DR-4 | A watch is **fulfilled only when the pharmacy confirms**; a decline or timeout reactivates it | 04 SM-7/O13 | ✅ 2026-10-13 |
| DR-5 | ~~Areas from OpenStreetMap~~ → **reversed by the team (2026-10-13):** location is **district-only**, with no maps or GPS. Inside one district, ranking falls back to price. Reason: focus effort on the agent. | 04 R-S2, 03 | ✅ reversed |
| DR-6 | Docs aligned, glossary, reading order, one source for numbers, ADR folder | README, all docs | ✅ 2026-10-13 |
| DR-7 | **The assistant requires a verified email**; sign-ups limited per IP | 04 SM-2/R-AU5, 03 CS-4 | ✅ 2026-10-13 |

## K. Agent-first refocus (2026-10-13)

| ID | Decision | Validated |
|---|---|---|
| AF-1 | **Simplify or postpone non-agent platform features:**<br>• fixed CSV upload template (no column mapping or encoding detection)<br>• one system-wide discount table + per-item override<br>• weekly opening hours only (no closures)<br>• offers last 2 h of real time (no client hours)<br>• no license document upload<br>• no change requests<br>• postponed: admin 2FA, password reset, delete account<br>• only agent-related abuse rules + the no-show pause<br>• catalog via import script (read-only admin view)<br>• essential notifications only<br>• no extra pharmacy screens | ✅ |
| AF-2 | **Multi-medicine planning** (add-on A5) promoted into the agent's core | ✅ |
| AF-3 | **Keep the chat assistant AND add autonomous sourcing requests:** one agent, two modes (ADR-002) | ✅ (team: "we keep the agent chatbot, but also add the feature of sourcing for clients") |
| AF-4 | **Units:** quantities in units now; box splitting later (A3) | ✅ |
| AF-5 | **Priority is a fixed rule in code;** the agent never ranks clients. ~~Emergencies → admin override~~ *Amended by §N: first come, first served; nobody can override (ADR-003 amended).* | ✅ (amended by §N) |

*Applied in `01` v3.0, `02` v1.0, `03` v2.0, `04` v2.0, ADR-002, ADR-003 (2026-10-13). Details still to validate: §L.*

## L. Domain-rule decisions from the refocus (step 04 v2.0)

| ID | Decision | Validated |
|---|---|---|
| R-D20 | Units (`units_per_pack` = 1 by default; `splittable` = false) | ✅ |
| R-D21 | ~~Priority rule: override → need-by → creation; admin-only overrides~~ *Superseded by §N: first come, first served; no override.* | ✅ superseded (§N) |
| R-D22 | Sourcing request lifecycle (SM-8) and the agent's autonomy boundary (R-RQ4). *Updated by §N: a 6-hour window instead of a need-by date.* | ✅ (updated) |
| R-D23 | Group reserve: **the agent reports per item what it found and what it didn't**; a card can hold any subset; ticked items all or none; on failure it names the item and offers the rest | ✅ (with team clarification) |
| R-D24 | Limits raised for requests: 5 open orders; 2 requests × 5 items; 5 early-release requests | ✅ |
| R-D25 | Multi-medicine planning by the deterministic `plan_basket` tool; the agent chooses, explains, proposes. *Updated by §N: quantities can be split across pharmacies; area first.* | ✅ (updated) |
| R-D26 | Agent-first simplifications reflected in the rules | ✅ (§K) |

## M. Database decisions (step 05)

| ID | Decision | Where | Validated |
|---|---|---|---|
| DB-D1 | **UUID** keys for business entities + readable refs (`R-000123` orders, `Q-000045` requests); `bigint` for logs | 05 §1 | ✅ 2026-10-13 |
| DB-D2 | Status lists as **text + CHECK**, not native enums | 05 §1 | ✅ 2026-10-13 |
| DB-D3 | **One `claims` table** for watches and waiting request items (one priority implementation) | 05 §3.5 | ✅ 2026-10-13 |
| DB-D4 | Uploads go through a **staging table** until Apply, then deleted; the file is never stored | 05 §3.3 | ✅ 2026-10-13 |
| DB-D5 | **Triggers only for "must never break"** invariants; everything else in services + tests | 05 §4 | ✅ 2026-10-13 |
| DB-D6 | **`today` always passed by the app**, never `CURRENT_DATE` (simulated clock) | 05 §5 | ✅ 2026-10-13 |
| DB-D7 | Discount tiers in a **`pricing_tiers` table** seeded from config | 05 §3.2 | ✅ 2026-10-13 |
| DB-D8 | **Own agent-metrics tables** (`agent_runs`, `agent_tool_calls`) besides Langfuse | 05 §3.6 | ✅ 2026-10-13 |
| DB-D9 | 👎 reports keep a **redacted snapshot** that survives the 30-day chat purge | 05 §3.6 | ✅ 2026-10-13 |
| DB-D10 | **Three database roles** (migrator / app / retention) with least privilege | 05 §7 | ✅ 2026-10-13 |

## N. Design review #2 decisions (2026-10-13)

From [design review #2](reviews/design_review_02.md). The team answered §A with a simplification, and accepted §B, §C and §D.

| ID | Decision | Where | Validated |
|---|---|---|---|
| DR2-A1 | **Needs are urgent:** requests and watches search for **6 hours**, and can only be started **08:00–20:00** ("come back tomorrow") | 04 R-T3, R-T8, N-5, N-11 | ✅ 2026-10-13 |
| DR2-A2 | **Instant reservations:** no pharmacy confirmation step; the pharmacy marks **[Picked up]** or **[Not available]** (all or some units) | 04 SM-5 | ✅ 2026-10-13 |
| DR2-A3 | **Pickup time per pharmacy:** 1–3 days (default 1), until closing time, never after expiry − 14 days; not picked up → back to stock | 04 R-T4, N-6 | ✅ 2026-10-13 |
| DR2-A4 | **Pickup by order number** + the [Picked up] button; no pickup code | 04 SM-5 | ✅ 2026-10-13 |
| DR2-A5 | **Prescription = a notice** ("bring it to the pharmacy"); no timing questions | 04 R-P1 | ✅ 2026-10-13 |
| DR2-A6 | **Split quantities:** one medicine's quantity can come from several pharmacies; partial coverage keeps searching | 04 R-RQ5, R-W4 | ✅ 2026-10-13 |
| DR2-A7 | **The claim is the single need:** matching and early release in parallel; **the first accepted offer wins**, the others are cancelled at once; offers count once for the limits | 04 SM-7 (R-W3) | ✅ 2026-10-13 |
| DR2-A8 | **First come, first served;** nobody (agent or admin) can change priority | 04 R-PRI, ADR-003 (amended) | ✅ 2026-10-13 |
| DR2-A9 | **District only:** same district → same governorate → rest of Lebanon; no coordinates or km | 04 R-S2 | ✅ 2026-10-13 |
| DR2-A10 | **Clock check instead of a jobs table;** deadlines live on the rows; `created_at` in real time; every time limit from the app clock | 04 R-T10, R-T11 | ✅ 2026-10-13 |
| DR2-A11 | **Matching** also runs on new claims and in a sweep; it locks clients first and skips paused clients or clients at a limit | 04 R-PRI1, R-PRI3; 05 §6 | ✅ 2026-10-13 |
| DR2-A12 | **One idempotency key per order** (group reserve); **regular Fargate**, no Spot | 05 §3.4; 02 §7 | ✅ 2026-10-13 |
| DR2-A13 | **Small rules:** items end only when the window ends (the agent may propose removing one); unticked items go back to the agent; a second escalation is appended; the deadline cap; event routing by source (search orders never wake the agent) | 04 R-RQ4, R-RQ6, SM-9, R-T4, R-AG5 | ✅ 2026-10-13 |
| DR2-B1 | **Cards come only from tools** (stored proposals); a tap sends the proposal ID and is re-validated | 04 R-AG7; 05 `proposals` | ✅ 2026-10-13 |
| DR2-B2 | **Text typed by pharmacies never reaches the LLM** | 04 R-AG8 | ✅ 2026-10-13 |
| DR2-B3 | **Polling** for new cards; "one moment…" while a turn runs | 02 §1; 03 CS-9 | ✅ 2026-10-13 |
| DR2-B4 | **Server-side sessions** instead of JWT + refresh tokens | 04 R-AU3; 05 `sessions` | ✅ 2026-10-13 |
| DR2-B5 | **Turn lease** instead of an advisory lock | 04 R-AG2; ADR-001 (amended) | ✅ 2026-10-13 |
| DR2-B6 | **Evaluation with three contenders** (search baseline, a no-AI scripted policy, the agent); several runs; success = secured within the window; pharmacy behavior from stated assumptions, tested across a range of values (DR2-E3) | 01 C16 | ✅ 2026-10-13 |
| DR2-B7 | **Networking:** public-subnet tasks (no NAT); a CloudFront VPC origin to an internal ALB | 02 §7 | ✅ 2026-10-13 |
| DR2-B8 | **Demo practicalities:** SES demo accounts or production access; short test deploys; the final deploy close to the demo | 02 §7 | ✅ 2026-10-13 |
| DR2-B9 | **Demo clock** (admin, demo mode only, audited) | 04 R-DEMO; 03 AS-12 | ✅ 2026-10-13 |
| DR2-C | **Document fixes:** decision-log annotations; checklist corrections; "units saved"; early-release suggested price −25%; dropped pharmacy fields; aligned paths; demo scenarios; `CN-` notification IDs; `Q-` request refs | all docs | ✅ 2026-10-13 |
| DR2-D | **Team tasks:** ~~written proof of the professor's approval; 2–3 pharmacist interviews~~ (dropped, DR2-E3); agent-first build order | 02 §9, checklist §8 | ✅ (team) |
| DR2-E1 | **The 6-hour window is kept** (reconfirmed). The first search is immediate; the window is background follow-up for the items not found. "Immediate only" was rejected because it would remove early release, watching and re-planning, the agent's main job. | 04 R-T8, N-11 | ✅ 2026-10-18 |
| DR2-E2 | **Details inside §N:**<br>• watches follow the request hours;<br>• early-release asks go only to open pharmacies, with 2 h to answer;<br>• automatic offers and asks stay within the client's district or governorate;<br>• an offer made before the window ends stays valid for its 2 h;<br>• the pickup reminder comes 4 h before the deadline;<br>• no prescription at the counter → come back, cancel without penalty, or it counts as a no-show;<br>• the no-show rule is unchanged;<br>• the clock check runs every 5 s | 04 R-T3, R-E2, N-23, R-RQ9, N-8, R-P1, R-N1, N-26 | ✅ 2026-10-18 |
| DR2-E3 | **Approval proof and pharmacist interviews dropped:** the proposal and poster phase is complete, and the report cites the approved proposal. The simulation uses **stated assumptions** about pharmacy behavior (answer rates, acceptance, [Not available] rate), **tested across a range of values** and reported as a limitation. | 01 C16, checklist Q-3 | ✅ 2026-10-18 |

*This section supersedes: S6, G5, T4 (jobs table), T6 (JWT), AF-5 / R-D21 / the original ADR-003 (need-by + override), P-D3, P-D8, P-D9, A-D11, the 60-day horizon (N-11) and the pickup code (R-PC).*

## O. API decisions (step 06)

| ID | Decision | Where | Validated |
|---|---|---|---|
| API-D1 | **REST + JSON under `/api/v1`**; agent tools call the services in-process, not HTTP | 06 §1, §8 | ✅ 2026-10-18 |
| API-D2 | **One error format with stable codes**; someone else's object returns `404` | 06 §2.2, §3 | ✅ 2026-10-18 |
| API-D3 | **Three button paths:** search → `/reservations`; agent cards → `/proposals/{id}/execute`; system cards → the object's endpoint. Proposals expire after 2 h and are single-use. | 06 §5.5, §6.7 | ✅ 2026-10-18 |
| API-D4 | **Price protection:** the tap sends the price shown; if it went up → `PRICE_CHANGED`, nothing reserved | 06 §6.3 | ✅ 2026-10-18 |
| API-D5 | **`Idempotency-Key` on every creating tap**; a group stores one key per order | 06 §1 | ✅ 2026-10-18 |
| API-D6 | **Chat replies arrive whole, after the output check** (progress events; no word-by-word streaming) | 06 §6.6.1 | ✅ 2026-10-18 |
| API-D7 | **Polling every 3 s** for new messages and cards while a chat or request page is open | 06 §6.6 | ✅ 2026-10-18 |
| API-D8 | **Busy conversation → `409 CONVERSATION_BUSY`**, and the UI retries automatically | 06 §6.6 | ✅ 2026-10-18 |
| API-D9 | **Availability capped at 5** in responses (+ a "more" flag) | 06 §5.3 | ✅ 2026-10-18 |
| API-D10 | **Money:** integer LBP + `usd_approx` out; LBP or USD in, converted on the server | 06 §1 | ✅ 2026-10-18 |
| API-D11 | **Internal `event` messages never shown to clients**; pharmacy decline reasons are codes only | 06 §5.5, §6.9 | ✅ 2026-10-18 |
| API-D12 | **CSRF:** `SameSite=Strict` cookie + `Origin` check | 06 §2.1 | ✅ 2026-10-18 |
| API-D13 | **OpenAPI generated and exported in CI**; interactive docs only in development; contract tests (3 per endpoint + every error code + Schemathesis) | 06 §9 | ✅ 2026-10-18 |
| API-D14 | **New numbers:** polling 3 s · 120 requests/min per session · proposal validity 2 h · max page size 50 | 04 N-28–N-31 | ✅ 2026-10-18 |

## G. Default numbers (superseded)

**Superseded by `04_domain_rules.md` §5 (validated 2026-10-13).** Kept for history only.

| Area | Default |
|---|---|
| Near-expiry window (published) | expiry ≤ 180 days |
| Minimum remaining shelf life (unpublished below) | 14 days |
| Early-release window (private items the agent may ask about) | expiry ≤ 270 days (9 months) |
| Discount tiers | 91–180 days: 25% · 31–90 days: 40% · 14–30 days: 60% |
| Order confirmation timeout | 2 h of opening time; reminder 30 min before |
| Pickup deadline | 48 h after confirmation, aligned with opening hours |
| **Max prescription wait** | **5 days** (and never past expiry − 14 days) |
| Pickup reminder | 12 h before the deadline |
| No-show rule | 2 in 30 days → reservations paused 7 days |
| Client limits | 3 open reservations · 3 packs per product |
| Need-by date | at most 60 days ahead |
| Watch | until the need-by date; stock held 2 h on a hit; earliest need-by first |
| Early release | max 3 pharmacies per request; pharmacy answers within 4 h of opening time; client offer valid 2 h |
| Stale inventory warning | no upload for 7 days |
| Upload limits | 5 MB · 10,000 rows |
| Pickup code guessing | 5 wrong codes in 10 min → code entry locked 10 min |
| Login lockout | client / pharmacy: 15 min after repeated failures · admin: 5 failures → 15 min + alert |
| Reset link | 30 min, single use |
| Chat | max 1,000 characters per message · kept 30 days |
| Duplicate-location check | another pharmacy within 50 m |
| Alerts | assistant errors > 5% / 15 min · LLM spend > 80% of budget · email failures > 10 / h · job lag > 5 min |

## H. Still open

| ID | Item | Needed by (dependency, not a date) |
|---|---|---|
| O1 | Which LLM model (chosen by measurement) | Evaluation step |
| O2 | Who pays for the real LLM. Development runs on the local model, so this is only needed for the evaluation runs and the demo. | Before the evaluation runs |
| O3 | Catalog source: **checked 2026-10-13.** The MoPH "Lebanon National Drugs Database" price list is public, with downloadable .xls/.xlsx per exchange-rate date. Columns: ATC, Name, B/G, Ingredients (with strengths), Dosage, Form, Price (LBP). **No pack size, no prescription/OTC flag, no controlled flag** (there is a separate Narcotics section). The rules for this gap are in `04` §2. | Step 04 decisions |
| O4 | ~~Values in §G~~ → done in `04` §5 | ✅ |
