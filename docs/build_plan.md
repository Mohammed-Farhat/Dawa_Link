# DawaLink: Build Plan and Progress

**Updated:** 2026-11-12 · **Status:** 🟡 living: updated at the end of every build step.

This is the one place that says **what is built, what comes next, and what was left for later**. A new session reads it to continue exactly where the last one stopped. Decisions stay in the [decision log](00_decision_log.md); this file only tracks the build.

---

## In short

- **Done:** steps 1 to 3: the code skeleton, the domain core (the exact rules as tested code) and the database (tables, logins, the real catalog, demo data).
- **Three questions are waiting for the owner** (§5, Q2 to Q4): the controlled list, the no-prescription list, and how strict "same medicine" is. None of them blocks step 4.
- **Next:** step 4, the services. It starts only when the owner says so.
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
| 4 | **Services** | Search, reserve and group reserve, [Picked up] and [Not available], claims and matching, offers, early release, sourcing requests, the notification outbox, and the worker's clock-check tasks | `04`, `05` §6 | ⏳ next |
| 5 | **The agent** | The 17 tools and `reply`, proposals, the turn graph, guards, prompts, the fake, local and Claude models, turns in the worker, tracing and `agent_runs` | `07`, ADR-001 | ⏳ |
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

---

## 4. Left for a later step

| What | Joins in |
|---|---|
| `mailpit` in Docker Compose | Step 4, with email |
| The worker's part of FX-10 (pause and retry when the database is down) | Step 4, with its first task |
| FX-13's test that kills the worker in the middle of a pass | Step 4 |
| The `Origin` check on state-changing calls (FS-6) | Step 7 |
| The demo clock: reading its stored offset from `app_state` (the table exists) | Step 4, with the demo clock's service |
| Two connections racing (the last unit, two [Picked up] clicks, two offers, two matching runs), and the clock-check tests (`05` §10) | Step 4, with the services |
| The reconciliation queries (INV-2, INV-18) | Step 4 |
| Cancelling open orders when a new import makes a product controlled (O6, FR-24) | Step 4 |
| The retention task itself (the retention login and its privileges exist) | Step 4, with the daily tasks |
| `create_admin`, password hashes and the demo accounts' passwords (they can't log in yet) | Step 7, with logins |
| The districts' reference points should be checked on a map | Before the demo |
| Upload rules (R-U1, R-U2, R-U4, R-U5) and month-only dates in files | Step 4, with uploads |
| Rounding locations and the straight-line travel estimate (R-RT1) | Step 4, with routing |
| The client's early-release limits (R-E5) | Step 4 |
| Retry schedules (SM-12) and the escalation, report and flag states (SM-9 to SM-11) | Steps 4 and 5, with what uses them |
| Search and the check at the tap take the pickup day as a date, and return `pickup_days_allowed` and `expiry_limits_pickup` (`06` v1.4) | Step 4, with search and reservations |
| The agent's tools take `pickup_day`; the context lists the upcoming days; hard rule 11 (`07` v1.4) | Step 5 |
| The reserve board on the v2 canvas still shows two cards ("Today", "Tomorrow"). `11` v1.4 wins: one card per allowed day | Step 8 |

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

### Decided

| # | What the docs disagreed on | The owner's decision |
|---|---|---|
| Q1 | **Pickup day.** The rule let a client pick today or the pharmacy's next 1–3 **open** days, but the reserve screen, the search filter and the agent's tools only knew "today / tomorrow". | **2026-11-10:** the rule and the agent use the same pickup days (3 open days at most), as dates. The agent must also know that a later pickup day leaves fewer days before the box expires. Applied in the docs and the rule code (decision log §W, BLD-D1 and BLD-D2). |

### Waiting for a decision

None of these blocks step 4. Each has a safe default in place.

| # | Question | What is in place now | Recommendation |
|---|---|---|---|
| Q2 | **Which medicines are controlled?** The Ministry publishes no list that can be downloaded. | Built from the international narcotic and psychotropic schedules, the matching ATC classes, plus tramadol and pregabalin: 168 products are hidden. When in doubt, a medicine is hidden. Pseudoephedrine (in cold medicines) and gabapentin are **not** hidden. | Ask a pharmacist to check `backend/data/catalog_overrides.toml` against the Ministry's own list before the demo (open item O6). |
| Q3 | **Which medicines need no prescription?** | The list is empty, so every product shows "Prescription needed: bring it to the pharmacy", even paracetamol. The notice is all it changes. | The team fills the list in the same file (open item O7). A short list of everyday medicines is enough for the demo. |
| Q4 | **Is "amlodipine besylate 5 mg" the same medicine as "amlodipine 5 mg"?** | No: an ingredient keeps its salt as the Ministry writes it, so these are not offered as alternatives of each other. 3,405 of 5,628 products still have at least one alternative. | Keep it strict. A missed alternative only hides an option; a wrong one could hurt someone. A pharmacist can add safe pairs to the corrections in the same file. |

---

## 6. Good to know on this laptop

- **Docker Desktop** may be off after a restart: start it first.
- **The database has four logins.** `.env` holds their four addresses; `.env.example` shows them. If your `.env` is older than 2026-11-12, copy the new lines from `.env.example`.
- **The Ministry's files** live in `backend/data/moph/` and are ignored by git. A teammate gets them with the commands in the root README.

- A Windows PostgreSQL service holds port 5432, so the project's database is at `127.0.0.1:5433`.
- Use `127.0.0.1` for the database, not `localhost`: `localhost` tries IPv6 first here and waits for seconds.
- `npm install` and Docker pulls can take many minutes on this connection.
- Docker Desktop must be running before any `docker compose` command.
