# DawaLink: Decision Log and Validation Checklist

**Purpose:** every decision taken so far, in one place, so the team can validate them together before each next step. Each line links to where it is specified. **Rows marked *superseded* or *postponed* are history: follow the section they point to.**

**How to validate:** go section by section. Tick ✅ in the **Validated** column, or write the change.

**Repository:** https://github.com/Mohammed-Farhat/Dawa_Link (public)

**Status of this log:** 2026-11-14 (BLD-D15 to BLD-D18 added the same day), covers steps 01–12, design review #2, the professor's guidance and the decisions taken during the build (§W). Sections A–F and I–W validated (2026-10-13 to 2026-11-10; §U amended on 2026-10-23 with the v2 design, UI-D13, and on 2026-11-02 with the AI notice, UI-D14). §G is superseded by `04` §5; §H is open.

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
| T3 | Agent framework **LangGraph** ~~(+ langchain-anthropic)~~. *The model is chosen by measurement (T13, O1).* *As built: our own model interface with Anthropic's SDK (§W BLD-D10).* | 02 §1 | ✅ 2026-10-13 (updated by §W) |
| T4 | Worker process ~~+ Postgres job table~~. *Updated by §N (DR2-A10): one **clock check** loop reads the deadlines stored on the rows; no jobs table.* | 02 §1 | ✅ 2026-10-13 (updated by §N) |
| T5 | Chat over **SSE** streaming. | 02 §1 | ✅ 2026-10-13 |
| T6 | Auth: ~~JWT in an httpOnly cookie~~ **server-side sessions** (§N DR2-B4), argon2, rate limits, email verification. *(Password reset postponed by §K. Admin TOTP 2FA was postponed by §K, then restored by §T TM-D8.)* *The token moved to a header, and Cognito comes later (§V INF-D6, INF-D12).* | 02 §1 | ✅ 2026-10-13 (updated by §K, §N, §V) |
| T7 | ~~Private S3 for license documents and raw uploads~~ → **no file storage**: uploads are processed in memory and discarded (license upload postponed, §K) | 02 §1 | ✅ 2026-10-13 (updated by §K) |
| T8 | Tracing with **Langfuse**; JSON logs to CloudWatch. | 02 §1 | ✅ 2026-10-13 |
| T9 | AWS: **ECS Fargate + ALB + one CloudFront + S3 + RDS + SES**, no NAT, built with **CDK (Python)**, budget alerts at $50 / $80, destroyed after the demo. *Updated by §N (DR2-B7): internal ALB via a CloudFront VPC origin; tasks in public subnets; regular Fargate, no Spot.* *Updated by §V: no CDK; set up by hand in Ireland; two CloudFronts and a public ALB.* | 02 §7 | ✅ 2026-10-13 (updated by §N, §V) |
| T10 | ~~CI/CD: GitHub Actions (OIDC), CodeQL, Dependabot, Trivy, offline eval gate.~~ *Superseded by §V (INF-D14): no CI/CD; the owner and Claude check every change.* | 02 §1, §8 | ✅ superseded (§V) |
| T11 | **Claude writes the code;** ~~every change goes through a PR the team reviews and can explain.~~ *Updated by §V (INF-D14): the owner and Claude check every change, and the owner can explain it.* | 02 §9 | ✅ 2026-10-13 (updated by §V) |
| T13 | **LLM by stage:** automated tests and CI use a **fake, scripted LLM** ($0). Day-to-day development uses a **local model** via Ollama (`qwen2.5:7b`, already installed). Evaluation and the demo use the real model chosen by measurement. *Since T14, the candidates are Claude models only.* *Updated by §W (BLD-D11): development uses Claude Haiku 5.5; the local model is a spare.* | 02 §1 | ✅ 2026-10-13 (updated by T14) |
| T12 | **Buttons call the API directly.** The assistant only proposes; it never executes consequential actions. | 02 §3.1 | ✅ 2026-10-13 |
| T14 | **The real LLM is Anthropic's Claude API.** Which Claude model stays open (O1). The local model stays for development only. | 02 §1, §10 | ✅ 2026-11-02 |
| T15 | **The owner's Claude Max plan pays for the real LLM:** $100 of API credits per billing cycle. Unused credit doesn't roll over. When it runs out, API calls stop until the next credit, unless more is bought. Closes O2. | 02 §10 | ✅ 2026-11-02 |

## C. Agent rules

| ID | Decision | Where | Validated |
|---|---|---|---|
| G1 | **Tools = code the agent calls** (they validate and execute). **Automatic code** (timers, emails, stock locks) runs without the agent. | 02 §3.2 | ✅ 2026-10-13 |
| G2 | The agent never sees names, phone numbers or emails; it acts only with the logged-in client's permissions. | 01 C6, C13 | ✅ 2026-10-13 |
| G3 | **No medical advice**: fixed refusal + referral to the pharmacist, backed by an output check. | 01 C6, 03 AF-14 | ✅ 2026-10-13 |
| G4 | Alternatives: **same composition only** (ingredient + strength + form), only with the client's consent. *Updated by §W (BLD-D17): another brand is shown with "ask the pharmacist first"; it is never reserved or waited for automatically.* | 01 §1, 03 AF-13 | ✅ 2026-10-13 |
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
| DR2-B4 | **Server-side sessions** instead of JWT + refresh tokens. *The token moved from a cookie to a header (§V INF-D6).* | 04 R-AU3; 05 `sessions` | ✅ 2026-10-13 (updated by §V) |
| DR2-B5 | **Turn lease** instead of an advisory lock | 04 R-AG2; ADR-001 (amended) | ✅ 2026-10-13 |
| DR2-B6 | **Evaluation with three contenders** (search baseline, a no-AI scripted policy, the agent); several runs; success = secured within the window; pharmacy behavior from stated assumptions, tested across a range of values (DR2-E3) | 01 C16 | ✅ 2026-10-13 |
| DR2-B7 | **Networking:** public-subnet tasks (no NAT); ~~a CloudFront VPC origin to an internal ALB~~ *Replaced by §V (INF-D5): two CloudFronts and a public ALB.* | 02 §7 | ✅ 2026-10-13 (updated by §V) |
| DR2-B8 | **Demo practicalities:** SES demo accounts ~~or production access; short test deploys; the final deploy close to the demo~~ *Updated by §V: one deploy after the project is finished; production access only if there's time.* | 02 §7 | ✅ 2026-10-13 (updated by §V) |
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
| API-D12 | **CSRF:** ~~`SameSite=Strict` cookie +~~ `Origin` check. *Updated by §V (INF-D6): the login token travels in a header, plus CORS.* | 06 §2.1 | ✅ 2026-10-18 (updated by §V) |
| API-D13 | **OpenAPI generated and exported** *(by script, not CI, §V)*; interactive docs only in development; contract tests (3 per endpoint + every error code + Schemathesis) | 06 §9 | ✅ 2026-10-18 |
| API-D14 | **New numbers:** polling 3 s · 120 requests/min per session · proposal validity 2 h · max page size 50 | 04 N-28–N-31 | ✅ 2026-10-18 |

## P. Agent decisions (step 07)

| ID | Decision | Where | Validated |
|---|---|---|---|
| AG-D1 | **One graph, two modes**; the mode changes only the prompt section and the tool set | 07 §2, §3 | ✅ 2026-10-18 |
| AG-D2 | **17 tools + `reply`** (6 read, 6 proposal, 5 bounded action). *Since 2026-11-14: 19 tools, with `set_area` (§W BLD-D14) and `show_other_brand` (§W BLD-D17).* | 07 §4 | ✅ 2026-10-18 |
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
| AG-D13 | **Provider and model as config; a scripted fake model in tests.** *Temperature 0 now applies to the local model only: Claude models reject sampling settings (T14).* | 07 §10 *As built: our own model interface, not LangChain chat models (§W BLD-D10).* | ✅ 2026-10-18 (updated by T14, §W) |
| AG-D14 | **Observability:** one Langfuse trace per turn with spans; `agent_runs` / `agent_tool_calls` mirror; evidence exported | 07 §9 | ✅ 2026-10-18 |
| AG-D15 | **New numbers** N-32–N-39 in `04` §5 | 04 §5 | ✅ 2026-10-18 |

## Q. Evaluation decisions (step 08)

| ID | Decision | Where | Validated |
|---|---|---|---|
| EV-D1 | **Six suites E1–E6:** understanding, 3-contender simulation, ablations, safety, model comparison, real-world constraints | 08 §3 | ✅ 2026-10-18 |
| EV-D2 | **U-set ~300** written by the owner and Claude *(updated by §V, INF-D14; the held-out part in a separate session)* (language and category mix), JSONL with gold labels, 60/40 dev/held-out, 20% double-labeled | 08 §2.1 | ✅ 2026-10-18 |
| EV-D3 | **R-set ~120** adversarial cases with automatic pass criteria + manual review; **target 0 violations** | 08 §2.2, E4 | ✅ 2026-10-18 |
| EV-D4 | **E2 three contenders:** search baseline, no-AI scripted policy (with keyword rules), the agent; same seeds and simulated client; 5 seeds × 100 requests | 08 E2 | ✅ 2026-10-18 |
| EV-D5 | **Primary metric:** units secured within the window; secondary metrics as listed | 08 E2 | ✅ 2026-10-18 |
| EV-D6 | **Simulation behavior = stated assumptions** with base values and ranges, varied in E6 | 08 §2.4 | ✅ 2026-10-18 |
| EV-D7 | **Initial targets** fixed now; changeable only before the first held-out run | 08 §3, §6.3 | ✅ 2026-10-18 |
| EV-D8 | **Model rule:** the cheapest model that meets every target (closes O1 when run) | 08 E5 | ✅ 2026-10-18 |
| EV-D9 | **Statistics:** mean ± 95% bootstrap CI; paired comparisons | 08 §4 | ✅ 2026-10-18 |
| EV-D10 | **Results committed** (config, raw, summary, charts) + exported traces + failure analysis | 08 §5, §6 | ✅ 2026-10-18 |
| EV-D11 | ~~**CI:** deterministic evaluation on every PR; LLM subset gate on agent and prompt PRs (manual trigger)~~ *Updated by §V: the same checks run by hand.* | 08 §7 | ✅ 2026-10-18 (updated by §V) |
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
| TM-D8 | **Admin two-factor login (TOTP)** restored (A-D2), set up by the `create_admin` command; contact-detail views limited to 30 per hour per admin | 04 R-AU6, N-47; 05 `users` | ✅ 2026-10-22 |
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
| UI-D14 | **The AI notice:** one line that's always visible at the top of the chat and above a request's thread: "You're chatting with an AI assistant, not a pharmacist." Anthropic's Usage Policy requires it. | 11 §6; 03 CS-9, CS-16 | ✅ 2026-11-02 |

*Also from this step:*
- `03` v4.2 (the "Home" tab, folded alternatives, a stale zone label removed);
- `10` v1.1 (the [Directions] link).

*The 4 boards that were pending (CS-15, CS-7, PS-6, AS-10) are drawn on the v2 canvas (2026-10-23).* `03` → v4.3 for the v2 tabs and search layout.

## V. Infrastructure and deployment decisions (step 12)

From [`12_infrastructure.md`](12_infrastructure.md). The owner set this direction and validated the step on 2026-11-02. The earlier v1.0 draft (CDK, pipelines, one CloudFront, a domain) was never validated.

| ID | Decision | Where | Validated |
|---|---|---|---|
| INF-D1 | **Local first** in Docker; one AWS deployment after the project is finished; no staging | 12 §1, §2 | ✅ 2026-11-02 |
| INF-D2 | **Ireland** (`eu-west-1`) | 12 §3 | ✅ 2026-11-02 |
| INF-D3 | **AWS by hand in the console;** only the owner has access; images pushed from the laptop; no CDK, CloudFormation or pipelines. Replaces T9's CDK and T10. | 12 §11, §12 | ✅ 2026-11-02 |
| INF-D4 | **No domain:** `*.cloudfront.net` addresses | 12 §4 | ✅ 2026-11-02 |
| INF-D5 | **Two CloudFronts and a public ALB** that accepts only CloudFront's addresses (one security group rule). Reverses DR2-B7. | 12 §4, §5 | ✅ 2026-11-02 |
| INF-D6 | **The login token travels in the `Authorization` header,** kept in `localStorage`; CORS for the website only; the server-side session is unchanged. Changes API-D12 and R-AU3. | 12 §4.3; 06 §2.1 | ✅ 2026-11-02 |
| INF-D7 | **Network:** public subnets for the ALB and tasks, isolated for RDS, no NAT | 12 §5 | ✅ 2026-11-02 |
| INF-D8 | **One backend image, two services (`api`, `worker`), one ops task;** a worker heartbeat check; `/health` always `200` with the database's status | 12 §6; 06 §6.1 | ✅ 2026-11-02 |
| INF-D9 | **`prepare_db` run by hand before each service update;** migrations keep the previous version working | 12 §7; 05 §9 | ✅ 2026-11-02 |
| INF-D10 | **Secrets in Secrets Manager;** the API has no AWS permissions; the access key stays outside the project folder | 12 §8 | ✅ 2026-11-02 |
| INF-D11 | **SES from one verified address, staying in the sandbox;** production access only if there's time; no bounce webhook | 12 §9 | ✅ 2026-11-02 |
| INF-D12 | **Cognito after the project works, before deploying,** behind our API. The validated login is built first. | 12 §10 | ✅ 2026-11-02 |
| INF-D13 | **Release and rollback by hand;** rollback = the previous task definition | 12 §12 | ✅ 2026-11-02 |
| INF-D14 | **The owner and Claude check everything and write the datasets** (the held-out parts in a separate session); no CI, no PR reviews; the repo stays public. Replaces T10, T11's review, and Definition of Done #3 and #7. | 12 §1 | ✅ 2026-11-02 |
| INF-D15 | **Logs kept 30 days;** app alerts + the AWS budget (excluding credits); no CloudWatch alarms; demo mode on in AWS | 12 §13 | ✅ 2026-11-02 |

*Also from this step:*
- accepted risks RR-12–RR-16 (`10` §8), and TH-45 now covers the AWS access key;
- R-D54–R-D56 (`04`) and API-D16 (`06`);
- open item O5 (the Ministry price file);
- **what it gives up:** most of bonus B-1, B-2, B-3, B-4 and B-6, and the infrastructure-as-code part of B-7 (checklist §5).

## W. Decisions taken during the build

Questions found while building ([build plan](build_plan.md) §5) and decided by the owner. Each one changes validated docs, so it is recorded here.

| ID | Decision | Where | Validated |
|---|---|---|---|
| BLD-D1 | **One set of pickup days everywhere.** The search filter, the reserve screen and the agent's tools all use the rule's days: today (if the pharmacy stays open long enough), or the pharmacy's next open days within its pickup time, **3 open days at most**. A pickup day is a **date**; the "today / tomorrow" choice in `03`, `06`, `07` and `11` is gone. The agent takes the date from a list of upcoming days it is given, and never works one out (N-49). | 04 R-F3, N-49; 03 CS-6, CS-8; 06 §5.3, §6.2; 07 §3.1, §4.2, §6.2; 11 §5 | ✅ 2026-11-10 (owner) |
| BLD-D2 | **A later pickup day leaves fewer days before the box expires, and the agent takes that into account.** It passes the day the client said to the tools, and the fit is counted from that day. Each option lists the days on which it still lasts, and flags when the expiry, not the pharmacy, rules a later day out; the client is then told the last day that works.<br>*The owner's example:* 2 days of use, a box expiring in 7 days, picked up on the third day → 5 days are left, so it still fits. With 7 days of use, the same box fits today or tomorrow, but not on the third day. | 04 R-F1, R-F6; 06 §5.3; 07 §4.2, §5.2 (rule 11); 09 FA-27 | ✅ 2026-11-10 (owner) |
| BLD-D3 | **The catalog comes from the Ministry of Public Health's two public sources, kept outside git.** The price list (.xls) gives the products and prices; the Lebanon National Drugs Database pages add the ATC code, brand or generic, and the ingredients. They are joined by name and price, then strength and form; a product that can't be matched safely is left out. The Ministry's files and the catalog file built from them stay in `backend/data/moph/` on the laptop and are **never committed**; the small catalog file ships inside the backend image. Corrects O3 and closes O5. | 04 §2; 05 §9, §12 | ✅ 2026-11-12. **The owner decided:** download the marketed price list, and keep the Ministry's files outside git. **Claude decided, and reported it:** also reading the 200 public database pages (the price list has no ingredients), the join, and leaving out the products that can't be matched safely. |
| BLD-D4 | **The database as built.** The technical changes to `05` made while building: the price function in whole numbers with a cap, frozen numbers guarded by tests, four database addresses with fixed logins, the audit log's delete rule by login, commands as modules (DB-D19–DB-D23). | 05 §12 | ✅ 2026-11-12 (Claude, under "Who decides what") |
| BLD-D5 | **The services as built.** Technical decisions made while building step 4: a service never commits (the caller owns the transaction, and follow-up work runs after the commit); one lock order everywhere; one allocator per medicine group; each clock-check row in its own transaction; the second migration (`claims.source`, `orders.reminder_sent_at`, one open early-release request per claim); two error codes (`CLAIM_NOT_ACTIVE`, `LIMIT_EARLY_RELEASE`). **What it does not decide:** four product questions found on the way wait for the owner (build plan §5, Q5 to Q8). | 05 §12; 06 §3; build plan §3 | ✅ 2026-11-12 (Claude, under "Who decides what") |
| BLD-D6 | **The agent may start waiting for a medicine of an open request after 20:00.** A request started at 19:30 searches until 01:30; R-W1 as written stopped the agent from opening a claim for it after 20:00. Now `open_claim` works for as long as its request is open: the request itself was started during request hours, and the 6 hours are the promise made to the client. Watches made from search or chat keep the request hours. | 04 R-W1; build plan Q6 | ✅ 2026-11-13 (owner) |
| BLD-D7 | **A client's own cancel or no-show ends that medicine in its request.** The rules said what happens after [Not available] (the search starts again), but not when the client cancels a reservation of an open request, or doesn't come for it. The item becomes CANCELLED and nothing is searched again; the other medicines carry on. The owner's reason: the client had a reason to cancel, and a new search would propose the same pharmacy again. | 04 R-RQ11; build plan Q5 | ✅ 2026-11-13 (owner) |
| BLD-D8 | **The controlled list is final as built.** No pharmacist's check: most pharmacies wouldn't sell these medicines through DawaLink anyway. Before closing, Claude checked the list on the real catalog: of 5,628 products, 168 are hidden; no visible product holds a substance of the international narcotic or psychotropic lists; every product has an ATC code and its ingredients. Left visible on purpose, because they are not on those lists: gabapentin, pseudoephedrine, dextromethorphan, muscle relaxants, trihexyphenidyl. Hidden although not controlled (their class is hidden as a whole): atomoxetine, and one bupropion with naltrexone product. Closes O6. | 04 R-C6; `backend/data/catalog_overrides.toml`; build plan Q2 | ✅ 2026-11-13 (owner) |
| BLD-D9 | **Routing: OpenRouteService first.** The owner may switch to Google Maps later. The routing code sits behind one interface, so the switch is small in code. **To settle before switching:** Google's terms restrict storing travel times, and the design stores them (the 24-hour cache, N-43, and the evaluation's precomputed table, PG-9). | 04 R-RT1; 02 §1 | ✅ 2026-11-13 (owner) |
| BLD-D10 | **The agent as built.** Technical decisions made while building step 5:<br>• our own small model interface instead of LangChain chat models, with Anthropic's SDK for Claude; LangGraph kept for the graph (amends T3 and AG-D13);<br>• a turn is several short transactions, and the `agent_runs` row is written first;<br>• a turn checks again, under its lease, that it is still wanted, and remembers the last message it read;<br>• "only `reply` is left" is done by giving the model only that tool (newer Claude models reject a forced tool choice) *(changed by BLD-D18: the tool list never changes within a turn)*;<br>• `find_options` takes one medicine and its equivalents only; options carry the pharmacy's opening hours for each pickup day;<br>• a new guard for replies that show tool names, IDs or JSON; a recommended card may be shown again while it is open;<br>• the worker runs agent turns in their own loop;<br>• the third migration; the routing timeout inside a turn (N-51).<br>**What it does not decide:** three things that change what a client sees or a product number wait for the owner (build plan §5, Q9 to Q11). | 07 §14; 05 §12; 02 §1 | ✅ 2026-11-13 (Claude, under "Who decides what") |
| BLD-D11 | **Development uses Claude Haiku 5.5, not the local model.** The local model (`qwen2.5:7b`) proved the plumbing but can't follow the prompt, so it says nothing about the agent's behaviour. Tests stay on a scripted model ($0); Ollama stays as a free spare. Development is capped at $3 of the credit *(raised to $20 on 2026-11-14, BLD-D13)*. Amends T13. **One budget until the demo:** the credit renews on 2026-12-09, after the demo, so every paid run gets a cost estimate first. | 02 §1; 07 §10, §14.4; 12 §2 | ✅ 2026-11-13 (owner) |
| BLD-D12 | **Three defaults of the agent are approved** (build plan Q9, Q10, Q12):<br>• the daily token budget per client is **3,000,000 tokens**, counting cached tokens (about 100 turns, the same as the daily message limit);<br>• when the model's own safety system declines to answer, the client sees our neutral text ("Sorry, I couldn't answer that…"), and the circuit breaker doesn't count it;<br>• the Arabic and Arabizi wording of our fixed texts (`agent/templates.py`) stays as written. | 04 R-AS; 07 §10, §14.3; 09 FA-29 | ✅ 2026-11-14 (owner) |
| BLD-D13 | **The app's monthly LLM budget for development is $20** (was $3). It is the app's own safety net: a day may spend 10% of it. **Unchanged:** the credit renews on 2026-12-09, after the demo, so it is still one credit for development, the evaluation and the demo; development turns on Haiku need no estimate (cents), every bigger paid run still does. Amends BLD-D11. | 12 §2; `.env.example` | ✅ 2026-11-14 (owner) |
| BLD-D14 | **A client can name their area in chat instead of sharing a location** (build plan Q11). The owner's rule: "he can say Hamra, and then the agent must search for pharmacies in this area or closer."<br>**How (Claude):**<br>• a new tool, `set_area(place)`, in the chat only: the 18th tool;<br>• the name is looked up in **our own list** (`backend/data/areas.csv` → the `areas` table, the 35th): the 26 districts and about 90 neighbourhoods and towns, with their other spellings and Arabic script;<br>• only a name written like a listed one is accepted. Otherwise the tool returns close names and the agent or the client chooses: code never guesses, because a wrong area sends the client to the wrong pharmacy;<br>• the area's centre becomes the chat's location; the agent is told the area's name and never a coordinate (INV-24);<br>• the fourth migration; prompt v1.1; N-47's location limit stays for the phone's location only.<br>**Not needed:** Google Maps, or any outside place search. What a client types stays inside the system.<br>**Since BLD-D15:** the towns and villages come from OpenStreetMap, and the hand-written list keeps the districts, the well-known neighbourhoods and their spellings. | 04 R-S2, R-RQ4; 05 §12; 07 §4.4, §14.6; 09 FA-31, FA-32; 10 TH-57; 03 AF-5 | ✅ 2026-11-14. **The owner decided** that the agent sets an area the client names. **Claude decided, and reported it:** the tool, our own list, exact names only, the table and the migration. |
| BLD-D15 | **The towns and villages a client can name come from OpenStreetMap** (build plan Q13). The owner's ok, after an explanation of what OpenStreetMap is: "okay do it".<br>**How (Claude):**<br>• one download from OpenStreetMap's public query service (Overpass), 0.6 MB: the cities, towns, villages and neighbourhoods of each district, with their centres and names. Nothing about DawaLink or a client is sent, and the running app never calls it;<br>• the hand-written `areas.csv` stays and wins: the districts, the well-known neighbourhoods and the ways people spell them. `areas_osm.csv` is generated and adds 1,733 places: 1,853 in all;<br>• the hand-written centres are now the map's own (Beirut as a whole and 9 places the map has no point for stay by hand);<br>• careful joins: a place in no district we know is left out, never moved to the nearest one; inside one district a name means one place; a name is kept only if it is plain Latin or Arabic letters, because volunteers type these names and the agent reads them (`10` TH-58);<br>• building the list again never changes an id;<br>• the generated file is committed with its credit (© OpenStreetMap contributors, Open Database License); the raw download stays outside git;<br>• prompt v1.2: the agent passes the name as the client wrote it (Arabic script included), and offers the choices as quick replies.<br>**What a client notices:** many more names exist in several districts. 10 of our well-known areas now share a name with a village elsewhere ("Hamra" in Beirut, "El Hamra" in Nabatieh), so the agent asks "which one?" before it searches. **Unchanged:** exact names only, and code never chooses (BLD-D14).<br>**Decided by the owner the same day (build plan Q14):** the agent keeps asking; a well-known area never wins without the question. | 04 R-S2; 05 §9, §12; 07 §14.6; 09 FA-32, FA-33; 10 §4.3, TH-58 | ✅ 2026-11-14. **The owner decided** to use OpenStreetMap. **Claude decided, and reported it:** the join rules, the two files, the name filter and the prompt wording. |
| BLD-D16 | **A client can mark their place on a map** (build plan Q15). The owner's case: a client on a computer, or one who doesn't want to share the device's location, puts the pin where they are.<br>**How (Claude):**<br>• "Pick on the map" is a third choice wherever the website asks for the location, next to "Use my location" and the district;<br>• the map is the one the pharmacy uses for its own pin, loaded only when the client opens it (UI-D9);<br>• the server treats the point like a shared location: rounded to about 100 m, stored only on that search, chat or request, never sent to the AI, and counted in the 10 location changes per hour (N-47). The API, the agent and its tools don't change;<br>• the map pictures come from OpenStreetMap's servers straight to the browser, which therefore see which part of the map the client looks at, never the point they choose (`10` §4.3).<br>**When:** with the website screens (build step 8). Until then nothing shows a map to a client. | 04 R-S2; 03 CS-6; 11 §11; 10 §4.3 | ✅ 2026-11-14 (owner). **Claude decided, and reported it:** how the point is stored, and that the map loads on demand. |
| BLD-D17 | **Another brand is shown with "ask the pharmacist first", and never reserved for the client** (build plan Q4). The owner's rule: the agent still finds the strict alternatives, but it doesn't offer to reserve one. It tells the client there may be another brand, names the pharmacies that have it, and gives the pharmacy's name, place and phone number, so the client calls and asks first.<br>**The four details the owner agreed to:**<br>• the phone number is on the card, added when the card is displayed; it never passes the AI (R-AG8);<br>• after the pharmacist says yes, the client reserves in the app by asking for that brand: a normal reservation;<br>• **search shows only what was searched, never another brand** (the owner, the same day; first agreed as "other brands on the search page with [Call]"): the "include alternatives" filter is removed. Another brand is shown only by the assistant;<br>• waiting holds only the exact medicine: watches, waiting request items, offers, early-release asks and multi-medicine plans never include another brand.<br>**How (Claude):**<br>• a new card kind, `other_brand`, made by a 19th tool, `show_other_brand`; a tap on it changes nothing;<br>• `propose_reservation` refuses another brand (`ASK_PHARMACIST_FIRST`) unless the model states that the client asked for that brand, and code accepts that only in a turn a client's own message started, never in a worker turn;<br>• which products are "another brand" is known by code: in a request, from the item; in a chat, the first product searched of a medicine is the client's medicine, and every other brand of it stays another brand. **A limit, in a chat only:** if the agent never searches the client's medicine and goes straight to another brand, code can't know; the prompt forbids it and the safety evaluation checks it;<br>• consent is checked by code too (`OTHER_BRANDS_NOT_AGREED`): the request's setting, or in a chat the profile's default, an earlier yes, or a yes in the message being answered;<br>• the fifth migration drops `include_equivalents` from `claims` and `early_release_requests`, and adds the card kind;<br>• the reply guard also catches "take it instead", "works the same" and "this brand suits you"; prompt v1.3.<br>**Nobody checks the call** (the owner, the same day): what the pharmacist says is outside DawaLink. When the client asks for the brand, it is reserved like any medicine; the pharmacist decides at the counter as always, and the client was told to ask first, so a refusal there is theirs to bear. The evaluation doesn't simulate the call: the simulated client says thanks, asks to reserve, or asks to keep looking.<br>**The two costs the owner accepted:** the box is not held while the client calls; a closed pharmacy can't answer.<br>Closes Q4: matching stays strict, and the pharmacist makes the real judgement. Updates G4. | 04 R-C10, INV-26; 01 C6; 03 AF-13, CS-6; 05 §12; 06; 07 §14.7; 08; 09 FA-34, FA-35; 10 TH-59; 11 §4 | ✅ 2026-11-14 (owner). **Claude decided, and reported it:** the tool, the card kind, how code knows a brand is another brand and that the client asked for it, the migration, the guard rule. |
| BLD-D18 | **Three fixes found on the first real runs of the other-brand flow** (Claude Haiku 5.5, 2026-11-14):<br>• **The same tools on every model call of a turn.** After a turn's last allowed tool call we used to send the model only `reply`. Claude ties its reasoning to the tool list it was made with, and rejected the request (400) the first time a turn really used all 6 calls. Now the list never changes within a turn: after the last allowed call a note is added after the tool results ("end the turn with reply"), and a further tool call is refused as before. Amends BLD-D10 ("only `reply` is left");<br>• **This turn's card must be shown.** The model once wrote "here is the reservation card" and attached an older card. The reply guard now asks for a correction when a turn made a card and the reply shows only older ones;<br>• **No quick reply may claim the call.** The model offered "Pharmacist agreed, reserve Pharmacy B" as a quick reply: one tap would have said a call happened. The prompt forbids it and the reply guard refuses it next to an "another brand" card. | 07 §14.7; 09 FA-36 to FA-38 | ✅ 2026-11-14 (Claude, under "Who decides what") |

*Also from this step:*
- new rule code with the owner's example as tests: `pickup_choice`, `pharmacy_pickup_days` and `upcoming_days` (`domain/pickup.py`), `last_pickup_day_that_fits` (`domain/expiry.py`);
- `08`: the U-set labels the pickup day as a number of days from today;
- **read as:** each pharmacy keeps its own pickup time setting (1–3 open days, default 1; N-6). 3 is the most a pharmacy can allow, not a new fixed value for every pharmacy.

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
| O1 | Which Claude model (chosen by measurement). The provider is settled: Anthropic's Claude API (T14). | Evaluation step |
| O2 | ~~Who pays for the real LLM~~ → the owner's Claude Max plan (T15) | ✅ |
| O3 | Catalog source: **checked 2026-10-13.** *Corrected 2026-11-12 (BLD-D3): the price list has no ATC code, brand/generic or ingredients; those are on the drug database's web pages. It does have a pack size, a code and a registration number.* The MoPH "Lebanon National Drugs Database" price list is public, with downloadable .xls/.xlsx per exchange-rate date. Columns: ATC, Name, B/G, Ingredients (with strengths), Dosage, Form, Price (LBP). **No pack size, no prescription/OTC flag, no controlled flag** (there is a separate Narcotics section). The rules for this gap are in `04` §2. | Step 04 decisions |
| O4 | ~~Values in §G~~ → done in `04` §5 | ✅ |
| O5 | ~~Where the Ministry price file lives~~ → outside git, in `backend/data/moph/` on the laptop; the catalog file built from it ships inside the backend image (BLD-D3) | ✅ |
| O6 | ~~The controlled list needs a pharmacist's check~~ → final as built, after a check on the real catalog (BLD-D8) | ✅ |
| O7 | **The no-prescription (OTC) list is empty,** so every product shows the prescription notice. The team fills it in the same file. | Before the demo |
