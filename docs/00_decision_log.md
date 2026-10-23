# DawaLink: Decision Log and Validation Checklist

**Purpose:** every decision taken so far, in one place, so the team can validate them together before each next step. Each line links to where it is specified. **Rows marked *superseded* or *postponed* are history: follow the section they point to.**

**How to validate:** go section by section. Tick ✅ in the **Validated** column, or write the change.

**Repository:** https://github.com/Mohammed-Farhat/Dawa_Link (public)

**Status of this log:** 2026-10-23, covers steps 01–11, design review #2 and the professor's guidance. Sections A–F and I–U validated by the team (2026-10-13 to 2026-10-23; §U amended on 2026-10-23 with the v2 design, UI-D13). §G is superseded by `04` §5; §H is open.

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
| T6 | Auth: ~~JWT in an httpOnly cookie~~ **server-side sessions** (§N DR2-B4), argon2, rate limits, email verification. *(Password reset postponed by §K. Admin TOTP 2FA was postponed by §K, then restored by §T TM-D8.)* | 02 §1 | ✅ 2026-10-13 (updated by §K, §N) |
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
| A-D2 | Two-factor login for admins | 03 §3.5 | ✅ restored 2026-10-22 (§T TM-D8; postponed by §K until then) |
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
| AF-1 | **Simplify or postpone non-agent platform features:**<br>• fixed CSV upload template (no column mapping or encoding detection)<br>• one system-wide discount table + per-item override<br>• weekly opening hours only (no closures)<br>• offers last 2 h of real time (no client hours)<br>• no license document upload<br>• no change requests<br>• postponed: admin 2FA *(restored by §T)*, password reset, delete account<br>• only agent-related abuse rules + the no-show pause<br>• catalog via import script (read-only admin view)<br>• essential notifications only<br>• no extra pharmacy screens | ✅ |
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
| DB-D1 | **UUID** keys for business entities + readable refs (`R-7K3Q2F` orders, `Q-4HX9TM` requests); `bigint` for logs. *Refs made random by §T (TM-D4); they were sequential.* | 05 §1 | ✅ 2026-10-13 (amended §T) |
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
| DR2-A9 | ~~**District only:** same district → same governorate → rest of Lebanon; no coordinates or km~~ *Superseded by §S (PG-2, PG-3): real locations and road travel times.* | 04 R-S2 | ✅ superseded (§S) |
| DR2-A10 | **Clock check instead of a jobs table;** deadlines live on the rows; `created_at` in real time; every time limit from the app clock | 04 R-T10, R-T11 | ✅ 2026-10-13 |
| DR2-A11 | **Matching** also runs on new claims and in a sweep; it locks clients first and skips paused clients or clients at a limit | 04 R-PRI1, R-PRI3; 05 §6 | ✅ 2026-10-13 |
| DR2-A12 | **One idempotency key per order** (group reserve); **regular Fargate**, no Spot | 05 §3.4; 02 §7 | ✅ 2026-10-13 |
| DR2-A13 | **Small rules:** items end only when the window ends (the agent may propose removing one); unticked items go back to the agent; a second escalation is appended; the deadline cap; event routing by source (search orders never wake the agent) | 04 R-RQ4, R-RQ6, SM-9, R-T4, R-AG5 | ✅ 2026-10-13 |
| DR2-B1 | **Cards come only from tools** (stored proposals); a tap sends the proposal ID and is re-validated | 04 R-AG7; 05 `proposals` | ✅ 2026-10-13 |
| DR2-B2 | **Text typed by pharmacies never reaches the LLM** *(except the admin-approved pharmacy name, §T TM-D2)* | 04 R-AG8 | ✅ 2026-10-13 (clarified §T) |
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

## P. Agent decisions (step 07)

| ID | Decision | Where | Validated |
|---|---|---|---|
| AG-D1 | **One graph, two modes**; the mode changes only the prompt section and the tool set | 07 §2, §3 | ✅ 2026-10-18 |
| AG-D2 | **17 tools + `reply`** (6 read, 6 proposal, 5 bounded action) | 07 §4 | ✅ 2026-10-18 |
| AG-D3 | **Every turn ends with a `reply` tool** (text, card IDs, chips, notes), checked by the output guard | 07 §4.5 | ✅ 2026-10-18 |
| AG-D4 | **Tool errors returned as codes; identity injected by code**, never taken from the model | 07 §4.1 | ✅ 2026-10-18 |
| AG-D5 | **Memory = last 20 messages + `case_state` + tools**; no memory across conversations; no vector store | 07 §6 | ✅ 2026-10-18 |
| AG-D6 | **PII redaction** (own identifiers + email and Lebanese phone patterns) before storage and before the model | 07 §7.1 | ✅ 2026-10-18 |
| AG-D7 | **Injection: structural defense** + flagging (not blocking) | 07 §7.1 | ✅ 2026-10-18 |
| AG-D8 | **Clinical check: rules + prompt first**; an LLM classifier only if the safety evaluation shows misses | 07 §7.2 | ✅ 2026-10-18 |
| AG-D9 | **Output violation → one repair, then a fixed template** | 07 §7.2 | ✅ 2026-10-18 |
| AG-D10 | **Limits and resilience:** timeouts, retries, turn limits, circuit breaker, worker retries | 07 §8 | ✅ 2026-10-18 |
| AG-D11 | **Follow-ups** as one `conversations.followup_at`, bounded | 07 §4.4; 05 §3.6 | ✅ 2026-10-18 |
| AG-D12 | **Prompts versioned in the repo**; `prompt_version` on every run; changes need an evaluation comparison | 07 §5.1 | ✅ 2026-10-18 |
| AG-D13 | **Temperature 0; provider and model as config; a scripted fake model in tests** | 07 §10 | ✅ 2026-10-18 |
| AG-D14 | **Observability:** one Langfuse trace per turn with spans; `agent_runs` / `agent_tool_calls` mirror; evidence exported | 07 §9 | ✅ 2026-10-18 |
| AG-D15 | **New numbers** N-32–N-39 in `04` §5 | 04 §5 | ✅ 2026-10-18 |

## Q. Evaluation decisions (step 08)

| ID | Decision | Where | Validated |
|---|---|---|---|
| EV-D1 | **Six suites E1–E6:** understanding, 3-contender simulation, ablations, safety, model comparison, real-world constraints | 08 §3 | ✅ 2026-10-18 |
| EV-D2 | **U-set ~300** written by the team (language and category mix), JSONL with gold labels, 60/40 dev/held-out, 20% double-labeled | 08 §2.1 | ✅ 2026-10-18 |
| EV-D3 | **R-set ~120** adversarial cases with automatic pass criteria + manual review; **target 0 violations** | 08 §2.2, E4 | ✅ 2026-10-18 |
| EV-D4 | **E2 three contenders:** search baseline, no-AI scripted policy (with keyword rules), the agent; same seeds and simulated client; 5 seeds × 100 requests | 08 E2 | ✅ 2026-10-18 |
| EV-D5 | **Primary metric:** units secured within the window; secondary metrics as listed | 08 E2 | ✅ 2026-10-18 |
| EV-D6 | **Simulation behavior = stated assumptions** with base values and ranges, varied in E6 | 08 §2.4 | ✅ 2026-10-18 |
| EV-D7 | **Initial targets** fixed now; changeable only before the first held-out run | 08 §3, §6.3 | ✅ 2026-10-18 |
| EV-D8 | **Model rule:** the cheapest model that meets every target (closes O1 when run) | 08 E5 | ✅ 2026-10-18 |
| EV-D9 | **Statistics:** mean ± 95% bootstrap CI; paired comparisons | 08 §4 | ✅ 2026-10-18 |
| EV-D10 | **Results committed** (config, raw, summary, charts) + exported traces + failure analysis | 08 §5, §6 | ✅ 2026-10-18 |
| EV-D11 | **CI:** deterministic evaluation on every PR; LLM subset gate on agent and prompt PRs (manual trigger) | 08 §7 | ✅ 2026-10-18 |
| EV-D12 | **Datasets written during the build**, dev parts first; held-out parts before the final runs | 08 §8 | ✅ 2026-10-18 |

## R. Failure Matrix decisions (step 09)

| ID | Decision | Where | Validated |
|---|---|---|---|
| FM-D1 | **Format:** 6 groups (FX, FA, FR, FI, FS, FO); per row: detection, behavior, what the user sees, test folder, severity; status ⏳ → 🔨 → ✅; updated in every PR | 09 | ✅ 2026-10-20 |
| FM-D2 | **Principles P1–P8:** fail closed for stock, money, safety and privacy; degrade gracefully for the AI, email and tracing | 09 §1 | ✅ 2026-10-20 |
| FM-D3 | **Tracing is best-effort:** a Langfuse failure never fails a turn; `agent_runs` always records | 09 FX-6 | ✅ 2026-10-20 |
| FM-D4 | **Failure-injection fakes**; every failure test also checks the invariants and the trail | 09 §8 | ✅ 2026-10-20 |
| FM-D5 | **Event coalescing:** many events for one conversation → one agent turn | 09 FA-20 | ✅ 2026-10-20 |
| FM-D6 | **Unsupported language** → the reply is in English | 09 FI-4 | ✅ 2026-10-20 |
| FM-D7 | **CSV exports escaped** against formula injection | 09 FS-10 | ✅ 2026-10-20 |
| FM-D8 | **Timeouts everywhere:** database statements 5 s (N-40), outbound HTTP 10 s (N-41) | 04 §5 | ✅ 2026-10-20 |
| FM-D9 | **Contesting a no-show:** [I picked it up] → `complaint` escalation → an admin can clear the no-show | 04 R-N3; 06 | ✅ 2026-10-20 |

## S. The professor's guidance (2026-10-20)

The professor said the agent's purpose is to **bring the client's need to the right pharmacy**, that **the agent decides** which pharmacy based on the **best route** and other properties, and that the **expiry must cover the client's period of use**. The team settled the details on 2026-10-20 (ADR-004).

| ID | Decision | Where | Validated |
|---|---|---|---|
| PG-1 | **The agent's purpose:** bring each need to the right pharmacy. **The agent decides** which pharmacy (or plan and route) to recommend, from facts computed by code plus what the client said; **one recommendation + up to 2 alternatives**; the client still taps | 04 R-AG9, N-45; 07 J2; ADR-004 | ✅ 2026-10-20 |
| PG-2 | **Location:** the client taps "Use my location" or picks a district; pharmacies pin themselves on a map at registration, checked by the admin. Stored **rounded to ~100 m**, outside the agent's case state, purged with its conversation or request. **Coordinates never reach the LLM.** | 04 R-S2, INV-24; 05 DB-D16 | ✅ 2026-10-20 |
| PG-3 | **Routes:** road travel times **by car and on foot** from OpenRouteService (OpenStreetMap data), cached 24 h, with a **straight-line fallback**; the best visiting order for multi-pharmacy plans; automatic reach = 30 min by car | 04 R-RT, N-23, N-43; 02 §1 | ✅ 2026-10-20 |
| PG-4 | **Days of use:** asked by the agent, with optional fields elsewhere. **If unknown → 1 day**, with the expiry date shown as a warning. No request is sent to the pharmacy for it (that would be a medical question). | 04 R-F2, N-44 | ✅ 2026-10-20 |
| PG-5 | **Pickup day:** today (if the pharmacy stays open at least 1 h more) or a next open day within the pharmacy's pickup time; the deadline is closing time that day, never after the expiry date | 04 R-T4, R-F3, N-42 | ✅ 2026-10-20 |
| PG-6 | **Expiry fit:** a box is offered only if `expiry ≥ pickup day + days of use − 1`; otherwise "no match" (with the latest expiry available) | 04 R-F1, R-F4, INV-25 | ✅ 2026-10-20 |
| PG-7 | **No fixed minimum before expiry:** any unexpired box (0–180 days) can be listed; the fit decides who it suits; the 60% tier now covers 0–30 days. No-shows are unchanged (the client's responsibility). | 04 N-1, N-2, N-4 | ✅ 2026-10-20 |
| PG-8 | **Early release and multi-medicine requests stay:** they also bring the need to the right pharmacy | 01 C8, C17, C18 | ✅ 2026-10-20 |
| PG-9 | **Evaluation:** E1 measures days of use, pickup day and situation; E2 measures **decision quality** (choices vs an oracle that knows the client's real situation), travel time, and boxes that don't last (must be 0); the simulation uses a precomputed travel-time matrix | 08 v1.1 | ✅ 2026-10-20 |

*This section supersedes: DR2-A9 (district only), N-1 (17–180 days), N-2 (14 days at pickup) and the BELOW_MIN zone, N-23 (district or governorate reach), and the area-first plan ranking in R-RQ5.*

## T. Threat model decisions (step 10)

From [`10_threat_model.md`](10_threat_model.md). The team validated these on 2026-10-22, after clarifying TM-D2, TM-D3, TM-D7 and TM-D9.

| ID | Decision | Where | Validated |
|---|---|---|---|
| TM-D1 | **Method:** a lightweight threat model: assets, attackers, trust boundaries, STRIDE per area, the OWASP Top 10 for LLM Applications (2025) for the agent, inherent and residual risk, a test per threat, accepted risks. Living: updated by every PR that adds an attack surface. | 10 §1 | ✅ 2026-10-22 |
| TM-D2 | **The pharmacy's name is the only pharmacy-typed text the agent sees.** It's safe because an admin approves it at registration, and only an admin can change it afterwards. R-AG8 and INV-23 reworded. | 04 R-AG8, INV-23 | ✅ 2026-10-22 |
| TM-D3 | **No "reliability" label:** the team assumes the stock on the app is real. **[Not available] is kept** for the rare exception (a box sold at the counter before the app was updated): it protects the client from an unfair no-show, triggers the agent's re-planning, and is the evaluation's main real-world constraint. "Reliability" removed from ADR-004, R-AG9 and J2. | 04 R-AG9, 07 J2, ADR-004 | ✅ 2026-10-22 |
| TM-D4 | **Random order and request numbers** (`R-7K3Q2F`): 6 characters without look-alikes. Amends DB-D1 (sequential). | 05 §1 | ✅ 2026-10-22 |
| TM-D5 | **Agent replies are plain text;** the output guard removes URLs | 07 §7.2 | ✅ 2026-10-22 |
| TM-D6 | **Layered cost caps:** per client per day; global per day (10% of the month); global per month; the provider's own spend limit; ≤ 10 location updates per hour | 04 R-AS, N-46, N-47 | ✅ 2026-10-22 |
| TM-D7 | **Registration never reveals whether an email has an account:** always "check your email"; an existing account's owner gets CN-18; the verification link logs the user in; pharmacies confirm their email before the approval queue | 04 R-AU4, R-AU7; 06 §6.1; 03 CS-2, PS-1 | ✅ 2026-10-22 |
| TM-D8 | **Admin two-factor login (TOTP)** restored (A-D2), set up by `create_admin.py`; contact-detail views limited to 30 per hour per admin | 04 R-AU6, N-47; 05 `users` | ✅ 2026-10-22 |
| TM-D9 | **What each third party receives** is stated (`10` §4.3) and kept to the minimum; `06` §2.3 corrected (the routing service gets the rounded point, with no identity). The exact data each outside API needs is confirmed during the build, and the table is updated then. | 10 §4.3; 06 §2.3 | ✅ 2026-10-22 |
| TM-D10 | **End-of-project hygiene:** scan evidence before export, push protection, backup retention, delete everything after the demo | 10 §10 | ⏸ postponed to the end of the project (team's choice) |

*Also from this step: R-AU8 (IP-based limits use CloudFront's address) and the Failure Matrix rows FS-19–FS-22.*

## U. UI design decisions (step 11)

From [`11_ui_design.md`](11_ui_design.md) and the design canvas. Validated by the team on 2026-10-22, noting that **the UI can still change during the build** (look changes on the canvas, rule changes in `11`, a decision-log row for any validated decision that changes).

| ID | Decision | Where | Validated |
|---|---|---|---|
| UI-D1 | **Visual language:** a green brand (`#0B6E4F`); one meaning per color (green done/fits · blue working · amber attention · red failed · grey info); Inter + Noto Sans Arabic + IBM Plex Mono for order numbers; borders, not shadows; Tabler line icons; light theme only. *The look was replaced by UI-D13 (v2).* | 11 §2 | ✅ 2026-10-22 (replaced by UI-D13) |
| UI-D2 | **Home is search first:** today's pickup → search box → two equal entry cards (Find medicines for me · Ask the assistant) → the open request | 11 §3.1, §5 | ✅ 2026-10-22 |
| UI-D3 | **Navigation:** client tabs Home · Assistant · Mine · Me; detail pages full screen with a back arrow; pharmacy and admin sidebars that stack on phones; a dark admin sidebar. *Updated by UI-D13: Home · Medicines · Ask · Me; pill tabs in a top bar for pharmacies and admins.* | 11 §3 | ✅ 2026-10-22 (updated by UI-D13) |
| UI-D4 | **One component per card kind**, rendered from the stored proposal: the same fact order everywhere, one main button, used or expired cards change state, "Recommended" = green border + badge + a reason, alternatives folded under "See N other options" | 11 §4, §6 | ✅ 2026-10-22 |
| UI-D5 | **The counter view:** the order number in large monospace, one tap from Home | 11 §4, §5 | ✅ 2026-10-22 |
| UI-D6 | **The reserve sheet asks the pickup day and days of use**, with a live fit badge (the server re-checks at the tap) | 11 §5 | ✅ 2026-10-22 |
| UI-D7 | **Language:** English labels; `dir="auto"` per message; Arabic font on demand; every UI string in one file | 11 §8 | ✅ 2026-10-22 |
| UI-D8 | **Accessibility:** WCAG 2.1 AA; `axe` in component tests; keyboard and screen-reader passes before the demo | 11 §9 | ✅ 2026-10-22 |
| UI-D9 | **Low-end phones:** per-portal code splitting, maps only where needed, no images, polling only while visible; budgets of ≤ 250 KB start-up JS and Lighthouse ≥ 80 | 11 §10 | ✅ 2026-10-22 |
| UI-D10 | **Maps and location:** maps only for the pin; [Directions] opens OpenStreetMap with the pharmacy's pin only; the location prompt only after the tap, with the privacy sentence | 11 §11; 10 §4.3 | ✅ 2026-10-22 |
| UI-D11 | **Frontend structure and tests:** React + TS + Vite + Mantine, TanStack Query, OpenAPI-generated types, Vitest + Testing Library + `axe`, Playwright demo flows; screenshots in every frontend PR | 11 §13 | ✅ 2026-10-22 |
| UI-D12 | **The design canvas is the visual reference;** `11` wins on rules; screens not drawn reuse the same components. *Since UI-D13, the reference is the v2 canvas.* | 11 §14 | ✅ 2026-10-22 (updated by UI-D13) |
| UI-D13 | **The v2 design direction** (v2 canvas, 15 boards: https://claude.ai/artifact/1pEPY1g3zNtYZX3Sbzv3mx):<br>• deep navy and a friendly blue, yellow for savings only;<br>• Readex Pro for English and Arabic; rounded cards and pill buttons; 17 px text;<br>• a floating menu Home · Medicines · Ask · Me, with a **My medicines** tracker;<br>• compact search rows showing the saving;<br>• a dark pickup ticket;<br>• the pharmacy's Today screen built around the counter;<br>• a navy admin bar.<br>It **replaces** the look of UI-D1 and the navigation of UI-D3, and **updates** UI-D4 (blue "Recommended"), UI-D5 (the ticket) and UI-D12.<br>**Later** (previewed on the boards): the savings total on Home, the text-size setting, Undo on [Picked up], the reminder button, the List/Map switch, the "why" chips. | 11 v1.1 §2, §3, §5, §14 | ✅ 2026-10-23 |

*Also from this step:*
- `03` v4.2 (the "Home" tab, folded alternatives, a stale zone label removed);
- `10` v1.1 (the [Directions] link).

*The 4 boards that were pending (CS-15, CS-7, PS-6, AS-10) are drawn on the v2 canvas (2026-10-23).* `03` → v4.3 for the v2 tabs and search layout.

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
