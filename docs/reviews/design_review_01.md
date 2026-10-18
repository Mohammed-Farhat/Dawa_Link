# Design Review #1: Docs 00–04, before database design

**Reviewed:** `00_decision_log.md`, `01` v2.2, `02` v0.4, `03` v1.0, `04` v1.0, `requirements_checklist.md`
**Method:** three engineering review lenses:
- **architecture** (decisions and trade-offs);
- **system design** (components, data flow, reliability, scale);
- **documentation** (clarity, consistency, audience).

**Date:** 2026-10-13 · **Status:** ✅ **All decisions DR-1–DR-7 approved by the team and applied** to `01` v2.2, `02` v0.5, `03` v1.1, `04` v1.1 (2026-10-13). Documentation fixes C1–C5 applied.

---

## Verdict

**The design is sound and well justified.** Its strongest parts are:
- the clear split between agent, code and humans;
- buttons that call the API directly, which is a strong safety property;
- one datastore (Postgres) for data, jobs and outbox;
- pure, testable domain rules with invariants;
- full requirements traceability.

Complexity sits where the product's value is (orders, offers, time rules), and step 04 now specifies it precisely.

**7 findings should be fixed before step 05**, because they change tables or state machines. **6 smaller findings** are handled in later steps. **5 documentation fixes** make the docs easier for teammates and graders.

---

## What is good and should stay

| Strength | Why it matters |
|---|---|
| The agent proposes; **the client's tap executes through the API** | No reservation can come from the model misreading text; it still works when the LLM is down |
| **One datastore** (Postgres) for data, timers, email outbox and audit | Fewer moving parts; transactions cover state + timer + notification together |
| **Pure domain core** (rules, state machines) separate from I/O | Fully unit-testable; invariants become tests |
| LLM by stage (fake → local → real) | $0 while building; deterministic CI |
| Search page as baseline **and** fallback | One feature serves the evaluation and reliability requirements |
| Requirements checklist + Definition of Done | Compliance is built in, not bolted on at the end |

---

## A. Findings to fix before database design (they change tables or state machines)

| # | Lens | Finding | Risk if ignored | Proposed fix |
|---|---|---|---|---|
| **A1** | Architecture | **The conversation is stored twice:** in our `chat_messages` (needed for the UI, retention and "delete my account") **and** in LangGraph's checkpoint tables. | Two copies drift. Deletion and 30-day retention must purge both, and a missed copy is a privacy bug. | **Our tables are the single source of truth.** LangGraph runs **stateless per turn** (no checkpointer): each turn loads the recent messages plus a structured "case state" from our DB. See **ADR-001**. |
| **A2** | System design | **Two writers on one conversation:** a client message (API, streaming) and a system event (worker) can run an agent turn on the same conversation at the same time. | Interleaved or duplicated replies; lost state. | **Serialize agent turns per conversation** with a Postgres advisory lock; an event that arrives during a turn retries shortly after. **Informational events** (order sent, confirmed, picked up, expired, prescription refusal) post a **template status card without any LLM call**. **Only events that need a decision** (declined, timed out, early release unfulfilled) run an LLM turn. This is cheaper, faster, and makes the LLM's role clearer. See **ADR-001**. |
| **A3** | System design | **Time-dependent values are stored and refreshed by the 03:00 job:** eligibility zone and policy price both depend on "days to expiry". | Between midnight and 03:00 an item that just fell below 17 days is still reservable, which breaks the 14-day guarantee. Stored prices go stale. | **Derive, don't store:** zone and policy price are computed **at query time** from `expiry_date` and today's date (pure functions). The daily job only **triggers events** (items entering the window → auto-publish notice and watch matching; reminders; purges). |
| **A4** | Consistency | **Early release, "keep it listed at that price"** (PS-9, R-E6, O15) conflicts with the visibility rule: an item 181–270 days from expiry is *not* in the publishable zone, so it can't be "kept public". | Undefined behavior; a bug source. | **Remove the option.** A declined or expired early-release offer simply **returns the item to private**. Simpler, and consistent with the zones. |
| **A5** | Correctness | **A watch is marked FULFILLED too early** (O13). The client accepts a watch offer, the order goes to the pharmacy, the pharmacy *declines*, and the watch is already closed. | The client silently loses their watch. | A watch becomes **FULFILLED only when its order is CONFIRMED**. If that order is declined or times out, the watch returns to **ACTIVE** (if `until` hasn't passed) and the assistant tells the client. |
| **A6** | System design | **Location is too coarse:** Beirut is **one district**, so every Beirut pharmacy measures from the same centroid. "Nearest" is meaningless exactly where most demo examples are (Hamra, Verdun). | Ranking by distance doesn't work in cities. | Add an **areas** table: localities and neighborhoods with coordinates, seeded from **OpenStreetMap** place data (open license, cited for data provenance). The client picks an area (default) or uses browser location for the session. Districts stay for grouping. |
| **A7** | Documentation → data model | **Entity names disagree:** `02` §4 lists "listings" and "reservations" as separate entities, while `04` defines **one Order** (which covers the reservation) and a **listing = an inventory item's publication state**. | The database could be built on the wrong model. | Align `02` §4 with `04`, and add a **glossary** (order, reservation, listing, offer, hold, watch, early release, zone, opening time, client hours). |

## B. Findings handled in later steps

| # | Lens | Finding | Proposed fix | Step |
|---|---|---|---|---|
| B1 | Security / cost | **Unverified accounts can chat.** Anyone can create many accounts and burn LLM budget. | Require a **verified email to use the assistant** (search stays open after login); sign-ups rate-limited per IP. | 04 (small amendment) |
| B2 | Privacy | "PII never reaches the LLM" can't be guaranteed for free text: a client may type their own name or phone. | Redact the **account's known identifiers** (exact name, email, phone) plus phone and email patterns before every LLM call. INV-10 then becomes testable. | 07 |
| B3 | System design | **SSE through CloudFront → ALB** can be cut by idle timeouts. | Heartbeat comment every 15 s; turns bounded (≤ 6 tool calls); timeouts set in CDK. | 07, 12 |
| B4 | Reliability | Three clocks (opening time, client hours, wall clock) mean a high risk of edge-case bugs. | One pure `calendar` module with an injectable clock and **property-based tests** (e.g. "a deadline is never earlier than +48 h"). | Build |
| B5 | Consistency | Tool signatures in `02` §3.2 are out of date (`create_watch` lacks quantity and `active_from`). | The full tool contracts are defined in `07`; `02` keeps only the overview. | 07 |
| B6 | Cost / latency | The clinical-advice output check isn't specified (rules vs an extra LLM classifier call). | Decide in `07` with measured cost and latency. Start with rules plus the main prompt, and add a classifier only if the safety evaluation demands it. | 07, 08 |

## C. Documentation fixes

| # | Finding | Fix |
|---|---|---|
| C1 | There's no **reading order** for teammates and graders; the docs are long. | `docs/README.md` gets a "Start here" path and the glossary (A7). |
| C2 | **Numbers are repeated** in `01` and `03` as "(default …)", while `04` §5 is the real source. | A note at the top of `01` and `03`: "Numbers: `04` §5 is the source of truth." |
| C3 | Inconsistent version, "builds on" and status headers. | One header format for every doc. |
| C4 | Key decisions live in tables, but the course asks us to **"compare design choices"**. | Add `docs/adr/` with ADRs for the major decisions. ADR-001 is written with this review; the others are written from the decision log as we go. |
| C5 | `03` is ~900 lines. | Keep it as the reference, but add a short summary at the top of each part. |

---

## System-design snapshot

**Scale assumptions:**
- **Demo:** ~30 pharmacies, ~200 clients, ~10 concurrent chats.
- **National ceiling:** ~3,000 pharmacies, each up to 10k inventory rows (~30M rows).

The chosen design (one Postgres, two small Fargate services) handles the demo with a large margin.

**What we'd revisit at national scale:**

| Area | Change |
|---|---|
| Geo search | A spatial index (PostGIS) |
| Job queue | Move to SQS when job volume grows |
| Database | Multi-AZ RDS |
| LLM | Prompt caching and per-route model choice |
| Pharmacy software | Read-replica or real-time integrations instead of uploads |

---

## Decisions requested from the team

| ID | Decision | Recommendation |
|---|---|---|
| DR-1 | Apply A1 + A2 as described in ADR-001 | ✅ Yes |
| DR-2 | A3: derive zone and price at query time | ✅ Yes |
| DR-3 | A4: drop "keep listed" after a declined early-release offer | ✅ Yes |
| DR-4 | A5: watch fulfilled only on CONFIRMED | ✅ Yes |
| DR-5 | A6: areas table from OpenStreetMap + browser location | ~~Yes~~ **Reversed by the team:** district-only location, no maps (focus on the agent). A6 is accepted as a known limitation. |
| DR-6 | A7 + C1–C5: doc alignment, glossary, reading order, ADR folder | ✅ Yes |
| DR-7 | B1: verified email required for the assistant | ✅ Yes |
