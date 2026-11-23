# DawaLink: Design Documents

DawaLink connects clients who can't afford a medicine at full price with pharmacies selling **near-expiry stock at a discount**, for **urgent needs**: the client reserves now and picks the medicine up today or on one of the pharmacy's next open days (3 at most), and **the box must last the days they'll use it**.

**The agent's purpose** (the professor's words): *bring the client's need to the right pharmacy.* **The agent decides** which pharmacy (or route) the client should go to, from travel times, opening hours, price, stock and the expiry fit computed by code. It never sees coordinates.

At its center is **one agent with two modes**:
- an **assistant** clients chat with;
- an **autonomous sourcing agent** that owns a client's request for several medicines for a **6-hour window**. It plans, asks open pharmacies to release unlisted stock, and re-plans when things fail.

Everything that must be exact is plain code: stock, reservations, prices, deadlines, and **who gets scarce stock first** (first come, first served). Every consequential action needs a human tap.

**Repository:** https://github.com/Mohammed-Farhat/Dawa_Link · **Course:** Agentic Systems 503N/798S (Path A) · **Live demo:** 2026-11-30

---

## Start here (reading order)

| If you want to… | Read |
|---|---|
| Understand the product and the agent in 10 minutes | [`01`](01_scope_and_features.md) §1–§5 |
| See why the agent is designed this way | [ADR-002](adr/ADR-002-agent-role-assistant-and-sourcing.md) (two modes) · [ADR-004](adr/ADR-004-agent-decides-the-pharmacy.md) (the agent decides the pharmacy) · [ADR-003](adr/ADR-003-priority-is-a-rule-not-the-llm.md) (priority) · [ADR-001](adr/ADR-001-conversation-state-and-agent-turns.md) (agent turns) |
| See what each user does, screen by screen | [`03`](03_user_flows.md): read each part's "In short" box first |
| Know the exact rules (states, limits, timers, numbers) | [`04`](04_domain_rules.md) |
| Understand the tech | [`02`](02_architecture.md), then [`05`](05_database.md) |
| Run or deploy it | [`12`](12_infrastructure.md) |
| Check a decision | [`00`](00_decision_log.md) |
| Check we meet every course requirement | [Requirements checklist](requirements_checklist.md) |

---

## Documents

| # | Document | Content | Status |
|---|---|---|---|
| ✔ | [Build plan and progress](build_plan.md) | The build steps in order, what is done, what is next, what was left for later | 🟡 living |
| ✔ | [Requirements checklist](requirements_checklist.md) | Every course requirement → artifact, location, phase; Definition of Done | 🟡 living |
| 00 | [Decision log](00_decision_log.md) | Every decision and when it was validated | ✅ A–W validated |
| 01 | [Scope and features](01_scope_and_features.md) | Goal, the agent's two modes, features C1–C18, demo scenarios | ✅ v5.8 |
| 02 | [Architecture](02_architecture.md) | Stack, components, agent graph and tools, routing, deployment | ✅ v3.7 |
| 03 | [User flows](03_user_flows.md) | Screens and flows per role (what happens, not visual design) | ✅ v4.23 |
| 04 | [Domain rules](04_domain_rules.md) | State machines, rules, **all numbers**, invariants | ✅ v5.16 |
| 05 | [Database design](05_database.md) | ER diagram, 37 tables (10 migrations), constraints, triggers, indexes, concurrency, the clock check, retention, seeding | ✅ v3.14 |
| 06 | [API contracts](06_api.md) | Every endpoint: schemas, auth, errors, rate limits; SSE and polling; proposals; interfaces between components; the API as built (§12) | ✅ v1.23 |
| 07 | [Agent specification](07_agent.md) | The agent's decisions, modes, turn graph, 19 tools + reply, prompts, memory, guardrails, limits, observability; the agent as built (prompts v1.14) | ✅ v1.18 |
| 08 | [Evaluation plan](08_evaluation.md) | Questions, datasets, suites E1–E7 (understanding, 3-contender simulation, ablations, safety, models, constraints, conversations with a played client), targets, statistics, regular checks | ✅ v1.12 |
| 09 | [Failure Matrix](09_failure_matrix.md) | 212 failure modes in 6 groups: detection, behavior, what the user sees, test, severity (living) | ✅ v1.30 (living) |
| 10 | [Threat model](10_threat_model.md) | Assets, attackers, trust boundaries, 72 threats with mitigations, tests and residual risk, OWASP LLM Top 10, 29 accepted risks | ✅ v1.19 (living) |
| 11 | [UI design](11_ui_design.md) | Visual language, layout per portal, components, the assistant's screen, states, accessibility, low-end phones, frontend structure; mockups on the v2 design canvas | ✅ v1.13 |
| 12 | [Infrastructure and deployment](12_infrastructure.md) | How we work, local setup, AWS by hand in Ireland, two CloudFronts, login across two sites, secrets, the setup checklist, releases, cost | ✅ v2.8 |

**Supporting folders:**
- [`adr/`](adr/): decisions with the options compared (ADR-001–003, amended by review #2; ADR-004 from the professor's guidance, amended by the threat model; on 2026-11-23 ADR-001 is amended for the chat with the team, BLD-D52, ADR-004 for the questions and areas to look in, BLD-D53, BLD-D54, and ADR-002 carries a dated note with its boundary unchanged, BLD-D55).
- [`reviews/`](reviews/): design reviews ([#1](reviews/design_review_01.md) ✅ · [#2](reviews/design_review_02.md) ✅).

---

## Glossary

| Term | Meaning |
|---|---|
| **Agent: assistant mode** | The chat. It understands the client, asks **once** for what it wasn't told (where, for how many days, when) and then always searches, never car or on foot (`04` R-AG9, BLD-D53); it explains options and proposes reservations. For one medicine that no pharmacy lists, it starts a watch and asks pharmacies on its own, then says what it did (R-RQ4, BLD-D55). |
| **Agent: sourcing mode** | Works **on its own** on a sourcing request during its window: plans, opens claims, asks pharmacies, re-plans, escalates. It needs a client tap for anything consequential. |
| **Sourcing request** | "Find these 1–5 medicines for me now": items, district, optional budget. It starts in the chat, from the agent's [Start sourcing] card (there is no form). It searches for **6 hours** and can only be started **08:00–20:00**. Outcome: FULFILLED, PARTIAL, UNFULFILLED or CANCELLED. |
| **Search window** | Results for what's listed come **immediately**. The 6 hours is how long DawaLink keeps trying **in the background** for the items it didn't find (new stock, asking pharmacies). One hour before the end, the agent gets a last chance to re-plan. |
| **Request hours** | 08:00–20:00. Outside them: "come back tomorrow" (for requests and watches only; search and reserving always work). |
| **Request item** | One medicine in a request: searching → plan ready → **secured** (all units reserved), or waiting / unavailable. |
| **Plan / group reserve** | The agent's proposal for several medicines, one card per pharmacy (a quantity may be split across pharmacies). **[Reserve these]** reserves the ticked items **all or none**. |
| **Proposal** | A card created by a tool and stored server-side. The agent only chooses which to show; a tap sends the proposal's ID, and the server re-checks everything. |
| **Product** | One medicine from the Ministry (MoPH) list: name, ingredients, strength, form, public price (LBP), units per pack |
| **Units** | All quantities are counted in units. Today 1 unit = 1 pack; box splitting comes later. |
| **Equivalence group** | Same ingredient(s), strength and form ("same medicine, another brand"). XR never matches normal release. **Another brand is only ever shown**, with "ask the pharmacist first" and the pharmacy's phone: it is never reserved, planned or waited for automatically. |
| **Inventory item** | A pharmacy's private stock of one product batch: on hand, reserved, expiry. The pharmacy keeps quantities current (edits or uploads). |
| **Zone** | By days to expiry: *near-expiry* 0–180 (can be listed, and each pharmacy decides which; no fixed minimum) · *early-release* 181–270 (private; the agent may ask) · *private* > 270. Computed live. |
| **Listing** | An inventory item's publication state. Visible when it is near-expiry, in stock, its pharmacy is approved, and the pharmacy lists it: by its own rule ("at 60 days left or fewer") or by hand. Not a separate object. |
| **Order / reservation** | One quantity from one pharmacy. A tap **reserves it instantly** (no confirmation step). The client shows the **order number** (`R-…`) at the counter; the pharmacy presses **[Picked up]** or **[Not available]**. |
| **Pickup time** | Set by each pharmacy: how far ahead a client may choose the pickup day (1–3 days, default 1). Not picked up by closing time that day → back to stock (a no-show, called a "missed pickup" on the screens; the boxes of one tap count as one, R-N1, BLD-D46). |
| **Pickup day** | The day the client says they'll come: today (if the pharmacy stays open at least 1 h more) or a next open day within the pickup time, 3 open days at most. The same days everywhere: search, the reserve sheet and the agent. A later day leaves fewer days before the box expires. |
| **Days of use** | How many days the client will take the medicine (asked; 1 if unknown, with an expiry warning, and the agent then recommends the box with the latest expiry, R-F2) |
| **Expiry fit** | A box is offered only if it's still valid on the last day of use: `expiry ≥ pickup day + days of use − 1`. Otherwise: "No match: the boxes expire too early for N days." |
| **Location** | Shared from the phone ("Use my location"), or **a pin the client puts on a map** (website), or **an area the client names in chat** ("I'm in Hamra": looked up in DawaLink's own list of districts, towns and villages, its centre is used), or a district; pharmacies have a map pin. Stored rounded; **never sent to the AI**, which only knows the area's name. A place named as **where to look** ("I need it in Saida or Beirut") is not where the client is: see *Search area*. |
| **Search area** | An area the client names as where to look, up to N-58 together (`04` R-S2, BLD-D54): only the pharmacies of those areas are searched, travel times still count from where the client is, and when none has the medicine the agent says there is none in these areas. A town named to look in counts as its district. |
| **Travel time** | Road time by car and on foot, computed by code (OpenRouteService; straight-line "about" if it's down) |
| **Recommendation** | The agent's choice of pharmacy (or route), with a one-sentence reason, plus up to 2 alternatives |
| **Claim** | **One need for one medicine**, waiting for stock: a **watch** ([Notify me], or started by the agent in a chat for a medicine no pharmacy lists, BLD-D55) or a **waiting request item**. Matching and early release both work for the same claim; the first offer the client accepts wins. |
| **Offer / hold** | Stock held for one claim for **2 hours**, after matching or after a pharmacy accepts an early release. The client taps to accept, which reserves it. |
| **Priority rule** | Who gets scarce new stock first: **first come, first served** (the claim that started waiting first). Computed by code. **Nobody can change it**: not the AI, not an admin. |
| **Early release** | The agent asks up to 3 **open** pharmacies to release stock they keep off their listings: boxes 181–270 days from expiry, or nearer boxes their own rule holds back. They have 2 hours to answer, and set the price. In a request it is part of the agent's 6-hour work; in a chat the agent asks at once for one medicine no pharmacy lists (BLD-D55). |
| **Prescription notice** | "Prescription needed: bring it to the pharmacy." The pharmacist checks it at the counter; DawaLink doesn't schedule or judge prescriptions. Shown on every product except those on the Ministry's own no-prescription list (`04` R-C7, BLD-D50). |
| **The chat with the team** | After someone of DawaLink's team replies to an escalation, the client's chat is with the team: what the client writes goes to the person and starts no agent turn, until the case is closed, the client starts a new chat, or N-55 passes since the team's last reply (`04` SM-9, BLD-D52). |
| **Opening hours** | A pharmacy's weekly schedule. Used for "open now", pickup deadlines and the Open/Closed badge. |
| **Clock check** | The worker loop that runs every few seconds and acts on overdue rows (offers, reservations, windows, asks, agent turns, emails). There is no jobs table. |
| **Case state** | The agent's structured working memory for a conversation or request |
| **Informational vs decision event** | Informational events post a **template card** (no LLM). Decision events (not available, early release failed, the window check, unticked items) run an **agent turn** to re-plan. |
| **Tool** | Code the agent can call. It validates its input, returns codes and IDs (never text typed by pharmacies), and **can't** create, accept or cancel orders or requests, or change priority, prices or stock. |
| **Degraded mode** | LLM down or over budget: search and everything else work, and requests keep their state |
| **Demo clock** | An admin control, in demo mode only, that fast-forwards the app's time to show time-based behavior live |
