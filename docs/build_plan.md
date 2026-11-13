# DawaLink: Build Plan and Progress

**Updated:** 2026-11-13 · **Status:** 🟡 living: updated at the end of every build step.

This is the one place that says **what is built, what comes next, and what was left for later**. A new session reads it to continue exactly where the last one stopped. Decisions stay in the [decision log](00_decision_log.md); this file only tracks the build.

---

## In short

- **Done:** steps 1 to 4: the code skeleton, the domain core (the exact rules as tested code), the database (tables, logins, the real catalog, demo data) and the services (everything the app does with those tables, and the worker's tasks).
- **One question is waiting for the owner** (§5): Q4, how strict "same medicine" is. The others were answered on 2026-11-13. It has a safe default in place, and doesn't block step 5.
- **Next:** step 5, the agent, when the owner says so.
- **Order:** the agent and its evaluation come before the website screens (`02` §9).

---

## 1. How each step works

1. Claude builds the step and its tests, runs every check, and tries it on the local website.
2. Claude updates this file, the Failure Matrix marks (`09`) and any doc the step touches.
3. The owner checks it, commits and pushes.
4. The next step starts only when the owner says so.

Work happens on `main`, in one commit per step. There are no feature branches (`12` §1).

---

## 2. The steps

The order was proposed by Claude from `02` §9 ("the agent first"). The owner can change it.

| # | Step | What it includes | Built from | Status |
|---|---|---|---|---|
| 1 | **Code skeleton** | Docker Compose; settings and logs; the API with `/health`, the error format and CORS; the worker loop and its heartbeat; the database step; the website shell; the root README | `02`, `06` §1–§3, `12` | ✅ 2026-11-10 |
| 2 | **Domain core** | The exact rules as plain, tested Python with no database: expiry zones and prices, the expiry fit, pickup days and deadlines, request hours, the state machines, order numbers, first come first served, the multi-medicine planner (`plan_basket`), the app clock | `04` | ✅ 2026-11-10 |
| 3 | **Database** | Every table, constraint, trigger and index; migrations; the three database roles; the catalog import and the demo seed | `05` | ✅ 2026-11-12 |
| 4 | **Services** | Search, reserve and group reserve, [Picked up] and [Not available], claims and matching, offers, early release, sourcing requests, the notification outbox, and the worker's clock-check tasks | `04`, `05` §6 | ✅ 2026-11-12 |
| 5 | **The agent** | The 17 tools and `reply`, proposals, the turn graph, guards, prompts, the fake, local and Claude models, turns in the worker, tracing and `agent_runs` | `07`, ADR-001 | ⏳ next |
| 6 | **Simulator and evaluation** | The simulated world and client, the three contenders, suites E1–E6, the development datasets, results | `08` | ⏳ |
| 7 | **Accounts and API** | Login and sessions, registration, every endpoint, limits, idempotency, chat streaming and polling, contract tests | `06`, `10` | ⏳ |
| 8 | **Website** | The client portal, the pharmacy portal and the admin console | `03`, `11` | ⏳ |
| 9 | **Hardening** | Every Failure Matrix row tested, the security tests, a load test, the accessibility passes | `09`, `10`, `11` §9 | ⏳ |
| 10 | **Cognito** | Passwords, email verification and admin codes move to Cognito, behind our API | `12` §10 | ⏳ |
| 11 | **Deploy** | AWS by hand, following the checklist | `12` §11–§14 | ⏳ |
| 12 | **Report and demo** | The final report, the demo script and rehearsal, exported evidence | checklist §3 | ⏳ |

---

## 3. Log

### Step 1: code skeleton (2026-11-10) ✅

**Built:**
- `docker-compose.yml`: `postgres`, `prepare-db` (runs once), `api`, `worker`, `web`.
- `backend/`:
  - `config.py` (every setting, from environment variables);
  - `api/` (`/health`, the one error format, request IDs, CORS for the website only);
  - `worker/` (the clock-check loop with no tasks yet, and its heartbeat);
  - `ops/` (`prepare_db`, `export_openapi`);
  - Alembic with no migration yet.
- `frontend/`: Vite, React, Mantine with the v2 theme, self-hosted Readex Pro, one temporary status page, API types generated from `docs/openapi.json`.
- `README.md` and `.env.example` at the root.

**Checked:**
- 40 backend tests and 7 website tests pass; ruff, mypy, oxlint and `tsc` are clean.
- `docker compose up --build` runs everything; the status page shows the website, API and database connected, with no browser errors.
- With the database stopped, `/health` still answers `200` and says the database is down (FX-10).

**Details added to the docs:**
- `04` N-40: connecting to the database times out after 2 s.
- `06` §3.2: the error code `METHOD_NOT_ALLOWED`.
- `12` §2 and §6: the local database port, and the ALB health check timeout of 6 s.
- `02` §1: the website's linter is oxlint.

### Step 2: domain core (2026-11-10) ✅

**Built** (`backend/src/dawalink/domain/`, plain Python with no database and no network):

| Module | Rules it holds |
|---|---|
| `numbers.py` | Every number of `04` §5 the code uses, by ID |
| `clock.py` | The app clock (system and manual), Beirut time |
| `expiry.py` | Expiry dates, days left, zones, **the expiry fit** (R-F1) |
| `pricing.py`, `money.py` | Discount tiers, the effective price, the early-release suggestion; LBP and USD |
| `opening_hours.py`, `pickup.py`, `windows.py` | Opening hours; pickup days and deadlines; request hours, search windows, offer times |
| `state_machine.py` | Who may make which change |
| `accounts.py`, `orders.py`, `claims.py`, `requests.py`, `early_release.py` | The state machines SM-1, SM-2, SM-5, SM-6, SM-7, SM-8, with their guards |
| `inventory.py` | Stock quantities, protected reserved units, the visibility rule |
| `limits.py` | Open-order and per-medicine limits; the no-show pause |
| `refs.py` | Order and request numbers |
| `allocation.py` | **First come, first served** |
| `search.py` | Search ordering; "5+" availability |
| `planning.py` | **The multi-medicine planner** (`plan_basket`) and the best visiting order |

**Checked:**
- 304 backend tests pass (264 of them for these rules); ruff and mypy are clean; every rule module is fully covered.
- Boundaries from the docs: days left −1, 0, 180, 181, 270, 271; request hours 07:59, 08:00, 20:00; "today" with 60 and 59 minutes of opening time left; the examples of R-F1 and R-T4; both daylight-saving changes of 2026.
- The planner's first plan matches an independent brute-force search on about 290 random baskets, and it answers in 0.3 s at its largest size.
- First come, first served gives the same result however the claims are ordered (INV-17).
- No agent action appears in the order, request, claim or account machines (INV-11).

**Details added to the docs:**
- `04` N-48: a plan visits at most 4 pharmacies, and the planner weighs at most 16.
- `04` R-RQ5: only the plans that cover the most units are returned.

### After step 2: the pickup-day decision (2026-11-10) ✅

The owner decided Q1 (§5): one set of pickup days everywhere, and a later pickup day leaves fewer days before the box expires (decision log §W).

**Built** (rules only; search, the reserve check and the agent's tools use them in steps 4 and 5):
- `domain/pickup.py`:
  - `pharmacy_pickup_days`: the days a pharmacy accepts (today, then its next open days, 3 at most);
  - `pickup_choice`: the days on which one box still lasts, and whether the expiry is what rules a later day out;
  - `upcoming_days`: the 7 days the agent can name (N-49).
- `domain/expiry.py`: `last_pickup_day_that_fits`.

**Checked:**
- 316 backend tests pass (276 of them for the rules); ruff and mypy are clean; every rule module is fully covered.
- The owner's example is a test: a box expiring in 7 days, a pharmacy that allows 3 days. Picked up on the third day, 5 days are left. 2 days of use fit on every day; 7 days of use fit today and tomorrow only; 8 days today only; 9 days never.
- On 500 random opening schedules, the days that fit are always the pharmacy's earliest days, and never more than 4 days are offered.
- `last_pickup_day_that_fits` agrees with the fit rule on every combination tried (about 3,500).

**Docs changed:** `01` v5.3 · `03` v4.5 · `04` v4.3 (R-F1, R-F3, R-F6, N-49) · `06` v1.4 · `07` v1.4 (tools, hard rule 11, case state, worked turn A2) · `08` v1.3 · `09` v1.4 (FA-27) · `11` v1.4 · decision log §W.

### Step 3: the database (2026-11-12) ✅

**Built:**

| Part | Where | What |
|---|---|---|
| The 34 tables | `backend/src/dawalink/db/models/` (8 files, one per area of `05` §3) | Every column, check, unique rule and index |
| The first migration | `backend/migrations/versions/20261112_1816_initial_schema.py` | The tables, 5 SQL functions (zone, price, fit, visible listings, area label) and 3 triggers (finished orders, price override, audit log) |
| The database logins | `db/roles.py` | Master, migrator, app and retention, each with exactly its privileges |
| The preparation step | `ops/prepare_db.py` | Logins → migrations → privileges → reference data → catalog → demo data. Safe to run twice. |
| The catalog | `catalog/` and `ops/fetch_moph.py`, `build_catalog.py`, `import_catalog.py` | Download the Ministry's two sources, join them, load them. "Same medicine" keys, the controlled flag and the prescription notice are decided here. |
| The team's catalog rules | `backend/data/catalog_overrides.toml` | Controlled medicines, the no-prescription list (empty for now), corrections for single products |
| Reference data | `backend/data/districts.csv`, `db/reference.py` | Lebanon's 26 districts with a reference point; the discount tiers |
| Demo data | `ops/seed_demo.py` | 16 pharmacies with hours, 6 clients, 960 boxes of stock. The same seed gives the same data. |

**Checked:**
- 622 backend tests pass: 198 on the database, 108 on the catalog code, 276 on the rules. Ruff and mypy are clean.
- Every constraint and trigger has a test that tries to break it, and a test fails if a constraint is added without one.
- Every SQL function gives the same answer as its Python rule on every boundary (about 1,600 price cases, 800 zone cases, 700 fit cases).
- Every list of allowed values in the database equals the rules' own list (37 lists).
- The tests connect as each login: the app login can't change the schema, the catalog or an audit event; the retention login deletes old chats and nothing else.
- The migration runs up, down to nothing and up again, and matches the models.
- The whole stack starts with `docker compose up --build`, and the local database holds the real catalog.

**The real catalog (the Ministry's list of 11 November 2026):** 5,628 medicines imported out of 5,739 on the list. 3,405 have at least one other brand of the same medicine. 168 are flagged as controlled and hidden. The details are in `05` §12.

**Docs changed:** `05` v3.3 (§12 "As built", DB-D19–DB-D23) · `04` v4.4 (the catalog's real sources, R-C2, R-C5–R-C7) · `09` v1.5 · `10` v1.3 · `12` v2.1 · decision log (BLD-D3, BLD-D4; O5 closed; O6 and O7 opened).

### Step 4: the services (2026-11-12) ✅

The services are the code between the rules (step 2) and the tables (step 3): each one does one thing a client, a pharmacy, the agent or the clock can do, inside one database transaction. Nothing here has a screen or an endpoint yet: the agent's tools (step 5) and the API (step 7) will call these same functions.

| # | Slice | Status |
|---|---|---|
| S0 | Foundations: the `services/` package (transaction context, error codes, audit, app clock with the demo offset, notifications and email outbox, chat events), the second migration, the service test setup (runs as the app login) | ✅ |
| S1 | Catalog search, listing search, travel times (cache + straight-line estimate) | ✅ |
| S2 | Reserve (single and group), client cancel, [Picked up], [Not available] | ✅ |
| S3 | Clock check, part 1: no-shows and the pause, the pickup reminder, lifting a pause; the worker runs the tasks | ✅ |
| S4 | Watches and claims, matching (first come, first served), offers: accept, decline, expire, withdraw | ✅ |
| S5 | Early release: asks, a pharmacy's answer, expiry, resolution | ✅ |
| S6 | Sourcing requests: create, items, decision events, the window check, closing | ✅ |
| S7 | Inventory: manual edits, pause and resume, price override, CSV upload; system cancel when a product becomes controlled | ✅ |
| S8 | Sending the email outbox (mailpit locally), the daily tasks (retention, stale inventory) | ✅ |
| S9 | Race tests (two connections), reconciliation after every flow, docs | ✅ |

**What exists** (`backend/src/dawalink/services/`):

| File | What it does |
|---|---|
| `context.py`, `errors.py`, `audit.py`, `clock.py` | One transaction per action; work that must wait for the commit; the error codes of `06`; one audit event per state change; the app clock with the demo offset |
| `catalog.py`, `search.py`, `travel.py`, `pharmacies.py`, `clients.py` | Finding medicines and visible boxes, with the days each box can be picked up and still last; travel times from the cache or a straight-line estimate |
| `orders.py`, `counter.py` | Reserve (one box, or a group all-or-none), cancel, no-show and the pause, [Picked up], [Not available], offers |
| `claims.py`, `matching.py`, `needs.py` | Watches, first come first served, what happens to a need when a reservation is gained or lost |
| `early_release.py` | Asking up to 3 open pharmacies, their answers, expiry, the result |
| `requests.py` | Sourcing requests: items, decision events for the agent, the window check, closing with an outcome |
| `inventory.py`, `controlled.py` | Manual edits, CSV uploads (check, then apply), and ending what is open for a medicine that became controlled |
| `notify.py`, `email.py`, `events.py` | In-app notifications, the email outbox and its sending, cards and decision events in a conversation |
| `daily.py`, `clock_check.py` | The once-a-day purge and reminder; the 12 tasks the worker runs every 5 seconds |

**Also changed:**
- the second migration: `claims.source`, `orders.reminder_sent_at`, one open early-release request per claim (`05` §12);
- `docker-compose.yml`: `mailpit` catches every email at http://localhost:8025, and nothing leaves the laptop;
- the catalog import command ends open orders, watches and request items for a medicine that became controlled.

**Decided for this step (Claude):** services use SQLAlchemy sessions and never commit themselves; the caller owns the transaction; matching and other follow-up work run after the commit, never inside a transaction that holds client or item locks; rows are always locked in the same order; each clock-check row is its own transaction. Recorded as BLD-D5 in the decision log.

**Checks:**
- 898 backend tests pass (unit 414, database 200, services 250, races 15, API 13, security 4, failure 2); 96% of the code is covered; `ruff` and `mypy` are clean. The website is unchanged.
- The service tests run **as the app login**, so a missing database privilege fails there and not later in Docker.
- The race tests use a throwaway database and two real connections. Both actions are started inside open transactions before either may continue, so the result never depends on luck. They cover two taps at once, and the clock check against a tap made a second before a deadline.
- After **every** service test and every race, the stock and the requests are reconciled (INV-2, INV-18), and every queued email is checked for a complete subject.
- Tried in Docker from the rebuilt images: the second migration applied; a demo client reserved a box through the services inside the worker container; both emails arrived in mailpit within seconds, with the time in Beirut time and the price in LBP and USD; the purge ran with the real retention login and logged what it deleted.

**Docs changed:** `04` v4.5 (N-50) · `05` v3.4 (§12) · `06` v1.5 (two error codes; CSV only so far) · `09` v1.6 (29 rows marked) · the requirements checklist (T-6, T-8 and T-14 are under way) · `10` v1.4 (what an email holds) · `12` v2.2 (mailpit and the email settings) · decision log (BLD-D5) · the root README.

---

## 4. Left for a later step

| What | Joins in |
|---|---|
| **Road travel times from OpenRouteService:** the adapter, its fake and the rest of FX-18. Until then every travel time is the straight-line estimate ("about N min"). **Needs a free OpenRouteService API key from the owner.** | Step 5, with the agent's tools |
| Running an agent turn for a decision event: the services only store the event and mark the conversation (`pending_turn_at`) | Step 5 |
| Executing a proposal (the tap on an agent's card), and the retry schedule of agent turns (SM-12) | Step 5 |
| The escalation, answer-report and abuse-flag actions (SM-9 to SM-11); only the no-show abuse flag is raised so far | Steps 5 and 7, with what uses them |
| The agent's tools take `pickup_day`; the context lists the upcoming days; hard rule 11 (`07` v1.4) | Step 5 |
| Admin actions: approving, rejecting and suspending a pharmacy, suspending a client, and what they end (FR-22, FR-23); contesting a no-show (R-N3) | Step 7, with their endpoints |
| XLSX inventory files (CSV works) | Step 7, with the upload endpoint |
| The demo clock's admin endpoint (the service that moves the clock exists) | Step 7 |
| The `Origin` check on state-changing calls (FS-6) | Step 7 |
| `create_admin`, password hashes and the demo accounts' passwords (they can't log in yet) | Step 7, with logins |
| The reserve board on the v2 canvas still shows two cards ("Today", "Tomorrow"). `11` v1.4 wins: one card per allowed day | Step 8 |
| The sender for SES (the local one speaks plain SMTP to mailpit) | Step 11, with the deployment |
| The districts' reference points should be checked on a map | Before the demo |

---

## 5. Found while building: checked, or waiting for a decision

The owner's rule (2026-11-10): **don't follow the docs blindly.** Anything that looks wrong, missing or unproven is checked and tested, then written here.

### Checked

| What | Result |
|---|---|
| The planner assumes an extra stop never shortens a trip. Real road times can be irregular. | Measured on 1,331 random baskets. With regular distances it always finds the best plan. With times bent by up to 30%, 1.7% of baskets get a trip about 2 minutes longer. It never covers fewer units. A test now guards this. |
| The price formula in `05` §5 uses decimals and has no cap at the public price. | The code uses whole numbers and caps the price. The database function must do the same in step 3. |
| **The Ministry's price list has no ingredients, ATC code or brand/generic** (the decision log's O3 said it had). | They are on the Ministry's drug database web pages. The import joins the two sources by name and price, then strength and form: 5,628 of 5,725 priced products match. A product that can't be matched safely is left out. |
| The price list **does** have a pack size, a code and a registration number (O3 said no pack size). | Stored on the product. The code is what a new list is matched on. |
| The price function could return two prices if two tiers overlapped. | Tiers can no longer overlap (a database constraint). |
| **"Same medicine" groups could mix different uses.** In the real list, 4 groups did: eye drops with ear drops, a mouth gel with a skin gel, two kinds of insulin. The form alone doesn't say what a product is for. | The ATC code is now part of the key. No group mixes ATC codes any more, and 3,405 products still have an alternative (5 fewer). |
| A trigger can't check "older than 1 year" without the database's own clock, which the design forbids. | Only the retention login may delete audit events; its task passes the date. |
| The 30-day chat purge would have been blocked by an escalation pointing at the chat. | The link is emptied instead. |
| An error while creating a database login would have printed the password in the logs. | The error names the login and nothing else. A test checks it. |
| Road times: the reference points of the 26 districts were written by hand. | Each is inside Lebanon (a test), but they should be checked on a map before the demo. |
| **Step 4.** The state machines of step 2 lacked three moves the flows need: a secured item goes back to searching after [Not available]; a secured item can be cancelled; a fulfilled claim is cancelled with its request. | Added, each with a test. |
| A sold-out box in a group reserve was reported as "no longer listed". | It now says "not enough stock, 0 left", which is what the client needs to read. |
| One email that couldn't be written (a bad value in its data) would have been tried first on every pass, and stopped every email behind it. | It fails on its own, is retried, then given up. The others go out. |
| When a medicine became controlled, a client who was watching it was told nothing. | They get "watch ended" (CN-11). The Failure Matrix row FR-24 now says what really happens. |
| The first emails printed the stored values as they were: times in UTC (2 to 3 hours off), prices as bare numbers. | Emails are now written in code: Beirut time, LBP with the USD amount. The "Reserved" email has the address and the opening hours, as R-NT asks. Every email queued by any service test is checked for a complete subject. |
| Follow-up work (matching, closing a request, ending an early-release request) runs after the commit. If it failed, the caller would have seen an error for work that had succeeded, and nothing would have done the follow-up later. | The failure is logged and the rest still runs. The clock check now looks for all three kinds of follow-up on every pass, so it is done a few seconds later. |
| With the mail server down, a pass of the clock check would have waited one timeout per queued email. | The first "server down" ends that pass's sending. One refused address (normal in the SES sandbox) doesn't stop the others. |
| Ending everything open for a newly controlled medicine in one transaction would lock many clients at once. | One row per transaction, as in the clock check. |
| The upload summary used other field names than `06`. | Aligned with `06` (`zeroed`, `reserved_kept`). |
| `06` and N-15 say uploads are CSV or XLSX. | Only CSV is built; XLSX joins with the endpoint (§4). |
| Can one need really have two offers at once (R-W3)? | Yes, but only one from matching and one from early release: a second pharmacy that accepts an ask is thanked, and nothing is held. A race test accepts both offers at the same moment: one wins, the other box goes back. |
| **Is the controlled list right?** It was built from the international lists, not from a list of the Ministry's own. | Checked on the real catalog (2026-11-13). No visible product holds a substance of the international narcotic or psychotropic lists, and every product has an ATC code and its ingredients, so none escapes the check. About 9 products are hidden although not controlled (atomoxetine, one bupropion with naltrexone): their class is hidden as a whole. Not on those lists and left visible: gabapentin, pseudoephedrine, dextromethorphan, muscle relaxants, trihexyphenidyl. |

### Decided

| # | What the docs disagreed on | The owner's decision |
|---|---|---|
| Q1 | **Pickup day.** The rule let a client pick today or the pharmacy's next 1–3 **open** days, but the reserve screen, the search filter and the agent's tools only knew "today / tomorrow". | **2026-11-10:** the rule and the agent use the same pickup days (3 open days at most), as dates. The agent must also know that a later pickup day leaves fewer days before the box expires. Applied in the docs and the rule code (decision log §W, BLD-D1 and BLD-D2). |
| Q6 | **Can the agent open a claim after 20:00 for a request that is still open?** A request started at 19:30 searches until 01:30, but R-W1 allowed new claims only during request hours. | **2026-11-13:** yes, for as long as the request is open. Watches made from search or chat keep the request hours. Applied in `04` v4.6 (R-W1), the service and a test (decision log BLD-D6). |
| Q8 | **What the emails say.** `03` and R-NT name each email, but not the wording. | **2026-11-13:** keep the wording as built (`backend/src/dawalink/services/email.py`), and review it once the project is finished. |
| Q2 | **Which medicines are controlled?** The Ministry publishes no list that can be downloaded. | **2026-11-13:** the list as built is final, with no pharmacist's check (decision log BLD-D8; O6 closed). |
| Q3 | **Which medicines need no prescription?** | **2026-11-13:** the list stays empty for now, so every product shows the notice. The tests cover both kinds with invented products. A short true list may be added before the demo (O7). |
| Q5 | **A client cancels a reservation that belongs to an open request, or doesn't come for it.** | **2026-11-13:** that medicine is finished in the request and nothing is searched again; the others carry on (`04` R-RQ11, decision log BLD-D7). This is what was built. |
| Q7 | **The straight-line travel estimate** (N-50). | **2026-11-13:** kept. It is only the fallback; road times come from OpenRouteService first, and the owner may switch to Google Maps later (decision log BLD-D9). |

### Waiting for a decision

None of these blocks step 5. Each has a safe default in place.

| # | Question | What is in place now | Recommendation |
|---|---|---|---|
| Q4 | **Is "amlodipine besylate 5 mg" the same medicine as "amlodipine 5 mg"?** | No: an ingredient keeps its salt as the Ministry writes it, so these are not offered as alternatives of each other. 3,405 of 5,628 products still have at least one alternative. | Keep it strict. **The owner will decide later** (2026-11-13), and may also remove alternatives from the agent, leaving them to the pharmacist. Until then they are built as designed: removing them later means dropping one tool and one prompt rule. |

---

## 6. Good to know on this laptop

- **Docker Desktop** may be off after a restart: start it first.
- **The database has four logins.** `.env` holds their four addresses; `.env.example` shows them. If your `.env` is older than 2026-11-12, copy the new lines from `.env.example`.
- **The Ministry's files** live in `backend/data/moph/` and are ignored by git. A teammate gets them with the commands in the root README.

- A Windows PostgreSQL service holds port 5432, so the project's database is at `127.0.0.1:5433`.
- Use `127.0.0.1` for the database, not `localhost`: `localhost` tries IPv6 first here and waits for seconds.
- `npm install` and Docker pulls can take many minutes on this connection.
- Docker Desktop must be running before any `docker compose` command.
