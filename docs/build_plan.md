# DawaLink: Build Plan and Progress

**Updated:** 2026-11-10 · **Status:** 🟡 living: updated at the end of every build step.

This is the one place that says **what is built, what comes next, and what was left for later**. A new session reads it to continue exactly where the last one stopped. Decisions stay in the [decision log](00_decision_log.md); this file only tracks the build.

---

## In short

- **Done:** steps 1 and 2: the code skeleton and the domain core (the exact rules as tested code).
- **Next:** step 3, the database. It starts only when the owner says so.
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
| 3 | **Database** | Every table, constraint, trigger and index; migrations; the three database roles; the catalog import (needs O5) and the demo seed | `05` | ⏳ next |
| 4 | **Services** | Search, reserve and group reserve, [Picked up] and [Not available], claims and matching, offers, early release, sourcing requests, the notification outbox, and the worker's clock-check tasks | `04`, `05` §6 | ⏳ |
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
- 303 backend tests pass (263 of them for these rules); ruff and mypy are clean; every rule module is fully covered.
- Boundaries from the docs: days left −1, 0, 180, 181, 270, 271; request hours 07:59, 08:00, 20:00; "today" with 60 and 59 minutes of opening time left; the examples of R-F1 and R-T4; both daylight-saving changes of 2026.
- The planner's first plan matches an independent brute-force search on about 290 random baskets, and it answers in 0.3 s at its largest size.
- First come, first served gives the same result however the claims are ordered (INV-17).
- No agent action appears in the order, request, claim or account machines (INV-11).

**Details added to the docs:**
- `04` N-48: a plan visits at most 4 pharmacies, and the planner weighs at most 16.
- `04` R-RQ5: only the plans that cover the most units are returned.

---

## 4. Left for a later step

| What | Joins in |
|---|---|
| `mailpit` in Docker Compose | Step 4, with email |
| The worker's part of FX-10 (pause and retry when the database is down) | Step 4, with its first task |
| FX-13's test that kills the worker in the middle of a pass | Step 4 |
| The `Origin` check on state-changing calls (FS-6) | Step 7 |
| The first Alembic migration | Step 3 |
| The price function in SQL must use whole-number maths, like `pricing.py` (`05` §5 shows a decimal formula) | Step 3 |
| The demo clock's stored offset | Step 3, with the `app_state` table |
| Upload rules (R-U1, R-U2, R-U4, R-U5) and month-only dates in files | Step 4, with uploads |
| Rounding locations and the straight-line travel estimate (R-RT1) | Step 4, with routing |
| The client's early-release limits (R-E5) | Step 4 |
| Retry schedules (SM-12) and the escalation, report and flag states (SM-9 to SM-11) | Steps 4 and 5, with what uses them |

---

## 5. Good to know on this laptop

- A Windows PostgreSQL service holds port 5432, so the project's database is at `127.0.0.1:5433`.
- Use `127.0.0.1` for the database, not `localhost`: `localhost` tries IPv6 first here and waits for seconds.
- `npm install` and Docker pulls can take many minutes on this connection.
- Docker Desktop must be running before any `docker compose` command.
