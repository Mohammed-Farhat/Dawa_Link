# DawaLink: guide for Claude Code sessions

DawaLink connects clients who can't afford a medicine at full price with pharmacies selling **near-expiry stock at a discount**. The needs are **urgent**: the client reserves now and picks up within a day or so. At its center is **one agent with two modes**: a chat **assistant**, and an **autonomous sourcing agent** that owns a client's request for 1–5 medicines during a **6-hour search window**. **The agent's purpose (the professor's words): bring the client's need to the right pharmacy.** It **decides** which pharmacy or route, from facts computed by code.

You are the owner and long-term maintainer of this codebase, and its design is up to you.

**Who decides what** (agreed with Mohammed, 2026-11-12):
- **Claude decides, without asking first:**
  - how the code is written, structured, named and tested;
  - the database's technical design: tables, constraints, indexes, migrations, locking;
  - internal architecture, refactoring, and fixing anything that is wrong.

  Claude then says what changed and why, and records it in [docs/build_plan.md](docs/build_plan.md).
- **Mohammed decides:**
  - what the product does: the rules, numbers, safety limits, and what a client, pharmacy or admin sees;
  - when the next build step starts;
  - committing and pushing.
- **A validated technical decision that has to change** (for example in `02` or `05`): Claude changes it and adds the row to the decision log. If the change affects what the product does, Claude asks first.
- **Flag doubts at once.** When Mohammed proposes something, or when something in the design or the docs looks wrong or uncertain, Claude says so directly, before building on it, with the reason and a recommendation. Claude never goes along silently.

- **Course:** Agentic Systems 503N/798S, Dr. Ammar Mohanna, Fall 2026, **Path A** (application). The professor proposed and approved the topic. The scope stays **logistics-only** (no clinical functions).
- **Team:** Mohammed Farhat (repo owner), Mohamad Natafgi, Anthony John Kanaan. They know **Python only**. **Claude writes all the code.** Mohammed and Claude check every change; teammates read and edit files through GitHub.
- **Repo:** https://github.com/Mohammed-Farhat/Dawa_Link (public).
- **Only fixed date:** the live demo on **2026-11-30**.

---

## 1. Read at session start

**Loaded automatically with this file:**
- @docs/README.md — docs index, the status of every step, glossary
- @docs/00_decision_log.md — every decision and its validation (don't reopen validated decisions)
- @docs/adr/ADR-002-agent-role-assistant-and-sourcing.md — the agent's two modes and its autonomy boundary
- @docs/adr/ADR-003-priority-is-a-rule-not-the-llm.md — who gets scarce stock first is code, never the LLM

**Then read these with the Read tool before your first substantive reply:**
1. [Project_Requirements.md](Project_Requirements.md): the course requirements, which are what we're graded on. Read-only; never edit it.
2. [docs/requirements_checklist.md](docs/requirements_checklist.md): every requirement mapped to an artifact, plus the **Definition of Done** for every change (§1).
3. [docs/01_scope_and_features.md](docs/01_scope_and_features.md) §1–§6: the product, the agent's features, why an agent, the demo scenarios.
4. The doc for the **current step** (§2 below) and the docs it says it builds on.

## 2. Where we are

The status column in [docs/README.md](docs/README.md) is the source of truth for the plan, and [docs/build_plan.md](docs/build_plan.md) for the build: read it at the start of every session, and update it at the end of every build step. As of 2026-11-10:

- **Planning steps 00–12 are all validated** (decision log sections A–W). **Current versions:**
  - `01` v5.3 · `02` v3.2 · `03` v4.5 · `04` v4.3 · `05` v3.2;
  - `06` v1.4 · `07` v1.4 · `08` v1.3;
  - `09` v1.4 (living: every change updates it) · `10` v1.2 (threat model; living: a change that adds an attack surface updates it);
  - `12` v2.0 (infrastructure and deployment);
  - `11` v1.4 (UI design) + the **v2 design canvas**, the visual reference: https://claude.ai/artifact/1pEPY1g3zNtYZX3Sbzv3mx (the user's private artifact; read it with the Artifact tool). The v1 canvas is kept as history: https://claude.ai/artifact/HYBxFhP96TUvhi1V9cCDLG;
  - ADR-001–004.
- **History of the big changes:**
  - [design review #2](docs/reviews/design_review_02.md) (§N, 2026-10-13);
  - API, agent, evaluation and Failure Matrix (§O–§R, 2026-10-18 to 10-20);
  - the threat model (§T, 2026-10-22): random order numbers, admin two-factor login, registration never reveals an account, plain-text agent replies, layered LLM cost caps, "reliability" removed (app stock is assumed real; [Not available] kept);
  - the UI design (§U, 2026-10-22): a search-first home, one meaning per color, cards rendered from proposals, WCAG AA, low-end phones; 10 boards on the design canvas. The UI can still change during the build;
  - the v2 design (UI-D13, 2026-10-23): the user chose the friendlier v2 direction:
    - Readex Pro; navy and blue, yellow for savings only;
    - tabs Home · Medicines · Ask · Me, with a "My medicines" tracker;
    - compact search rows; a dark pickup ticket; the pharmacy's counter-first Today screen.

    The v2 extras wait until later: the savings total on Home, text size, Undo on [Picked up], the reminder button, the List/Map switch, and the "why" chips.
  - infrastructure (§V, 2026-11-02): a simple, manual deployment, chosen by Mohammed:
    - develop locally in Docker, then deploy once to AWS (Ireland) after the project is finished; only Mohammed touches AWS;
    - AWS is set up by hand in the console. No CDK, CloudFormation, CI/CD, PR reviews or advanced GitHub features: don't propose them again;
    - two CloudFronts (website on S3, API on a public ALB), no domain, no certificate;
    - the login token travels in the `Authorization` header (`localStorage`), with CORS;
    - build the validated login first, then switch to Cognito behind our API before deploying (`12` §10);
    - Mohammed and Claude check everything and write the datasets.
  - build decisions (§W, 2026-11-10), from questions found while building:
    - one set of pickup days everywhere, as dates: today or the pharmacy's next open days, 3 at most;
    - a later pickup day leaves fewer days before the box expires, and the agent passes the client's day to the tools.
- **The professor's guidance (2026-10-20) is applied** across 01–09 (decision log §S, [ADR-004](docs/adr/ADR-004-agent-decides-the-pharmacy.md)): the agent decides the pharmacy; real locations and road travel times; the expiry fit (days of use + pickup day); no fixed minimum before expiry.
- **Planning is finished, and the build started on 2026-11-10.** Order: build → test → evaluate → switch to Cognito → deploy → report and demo.
- **Built so far:** steps 1 and 2 of 12 (2026-11-10): the code skeleton, and the domain core (`backend/src/dawalink/domain/`: the rules of `04` as plain, tested Python). The steps, their order and the log are in [docs/build_plan.md](docs/build_plan.md).
- **Next: step 3, the database** (`05`: tables, constraints, triggers, migrations, roles, seed). ⚠️ **One build step at a time: don't start the next one until the user says to.** The user checks each step, then commits and pushes it themselves.
- **Open items:**
  - O1: which Claude model (chosen by measurement; the provider is settled: Anthropic's Claude API);
  - O5: where the Ministry price file lives (decided later);
  - TM-D10, end-of-project hygiene (scan evidence before export, push protection, backup retention, delete everything after the demo): **postponed to the end** by the user. Don't raise it before then.
- **Who does what:**
  - Mohammed and Claude write and label the ~300-request understanding set and the ~120-request safety set;
  - the team creates realistic inventory files in the upload template.

If the user's first message is general ("let's continue"), summarize where we are and ask before starting the next step.

## 3. How to work with this team

1. **One step at a time, validated together.**
   - Present each step with numbered decisions (e.g. `DB-D1`), a recommendation for each, and a plain-language reason.
   - Wait for the user's "ok" or their changes. Never start the next step before the current one is validated, **and before the user says to start it**.
   - For a review, take the user's answers section by section (A, then B, C, D), then apply all the changes in one pass.
   - When a step is validated, update all four of these:
     - the doc's version line;
     - its row in `docs/README.md`;
     - `docs/00_decision_log.md`;
     - §2 of this file.
2. **No internal deadlines or schedules.** "Done" means every course requirement is satisfied.
3. **Agent-first.** This is graded as an *Agentic Systems* course.
   - Put the effort into the agent's job and its evaluation.
   - Keep platform features minimal, and push back on scope creep that doesn't serve the agent.
4. **Skills:**
   - use `engineering:documentation` whenever writing or updating docs;
   - use `engineering:architecture` / `engineering:system-design` for design reviews and ADRs.
5. **UI and visual design follow [`11`](docs/11_ui_design.md) and its design canvas.** `03` says *what happens*; `11` says how it looks and behaves.
6. **Code is for Python developers to read.**
   - Readable, typed, small changes.
   - Claude runs each change's tests, tries it on the local website, and explains what changed and why, in plain language. It must meet the Definition of Done.
7. **Git and publishing:**
   - Never commit, push, publish, or change `.gitignore` without the user's explicit permission.
   - Since 2026-10-18, `/docs`, `CLAUDE.md`, `DawaLink_Project_Proposal.md` and `Project_Requirements.md` are **tracked** (the user changed `.gitignore` so the team can read them). The user commits and pushes these updates themselves.
   - The repo is public: nothing secret or personal goes in tracked files. Before any doc is committed, check it for emails, keys and tokens.
8. **Secrets and privacy:**
   - Secrets live in `.env` locally and in AWS Secrets Manager in production, and are never committed.
   - The AWS access key stays in `~/.aws`, outside the project folder.
   - **No PII is ever sent to the LLM.**
9. **Communication:** plain language, short, a recommendation rather than a survey of options. Explain technical terms the first time.
10. **Held-out data:** the held-out datasets are written in a separate Claude session. In the working session, never open those files.
11. **Don't follow the docs blindly** (Mohammed's rule, 2026-11-10).
    - When something looks wrong, missing or unproven (in a doc, in the code, or in your own assumption), check it and test it before building on it.
    - Fix what is clearly a mistake, and say so. Raise what needs a decision, with a recommendation.
    - Record both in [docs/build_plan.md](docs/build_plan.md) §5.
    - The same goes for what the user proposes: if it looks wrong or uncertain, flag it directly (see "Who decides what" at the top).

## 4. Design rules that must never be broken

The details are in the linked docs. If a request or code change would break one of these, stop and raise it.

- **The agent proposes; the client's tap executes** through the API. Agent tools never create, accept or cancel orders or requests, and never change priority, prices or stock ([02 §3](docs/02_architecture.md), [04](docs/04_domain_rules.md) R-AG).
- **Cards come only from tools** (stored proposals); a tap sends the proposal ID, and the API re-validates it. **Text typed by pharmacies never reaches the LLM**, except the admin-approved pharmacy name (04 R-AG7, R-AG8). **Agent replies are shown as plain text** (no links, images or HTML; `10` TM-D5).
- **Priority is first come, first served, in code.** Nobody can change it: not the LLM, not an admin ([ADR-003](docs/adr/ADR-003-priority-is-a-rule-not-the-llm.md), amended).
- **The agent decides where the client goes** (ADR-004): code computes the travel times, routes and expiry fit; the agent weighs them with what the client said and recommends one pharmacy with a reason. **Coordinates never reach the LLM** (04 INV-24): location is stored rounded, outside `case_state`.
- **A box is offered only if it lasts the client's days of use** from the chosen pickup day (04 R-F1, INV-25); unknown days → 1 day + an expiry warning. **One set of pickup days everywhere** (search, the reserve sheet, the agent's tools): a date among today and the pharmacy's next open days, 3 at most. A later day leaves fewer days before expiry, and the agent never works out a date itself (04 R-F3, R-F6, N-49).
- **Urgent needs:** requests and watches search for 6 hours and can only be started during request hours. Reservations are **instant** (no pharmacy confirmation); the pharmacy marks [Picked up] or [Not available]; the pickup time is set per pharmacy. A prescription is a **notice** only (04 §1, SM-5, R-P1).
- **Our tables are the source of truth** ([ADR-001](docs/adr/ADR-001-conversation-state-and-agent-turns.md)):
  - LangGraph is stateless per turn;
  - one agent turn runs at a time per conversation (a lease on the conversation row);
  - informational events post template cards with no LLM call; decision events run an agent turn.
- **Time is injected:** `today` and `now` always come from the app's clock (the simulated and demo clocks). Never `CURRENT_DATE`/`now()` for business logic in SQL, or `date.today()` in domain code. `created_at` may be real time (it only orders "who came first") ([04](docs/04_domain_rules.md) R-T11, [05](docs/05_database.md) DB-D6).
- **No jobs table:** one **clock check** loop acts on deadlines stored on the rows (04 R-T10).
- **Derived values are never stored.** The expiry zone and the discount price are computed live.
- **Money** is stored as LBP integers and shown as LBP + ≈USD. **Quantities** are counted in units.
- **Numbers** (windows, limits, timers) live only in [04 §5](docs/04_domain_rules.md). Reference them by ID; don't repeat them. In code they live only in `backend/src/dawalink/domain/numbers.py`.
- **Safety:**
  - no medical advice;
  - alternatives must have the same composition, and are offered only with the client's consent;
  - controlled substances are excluded entirely;
  - a prescription notice by default (the pharmacist checks at the counter);
  - the chat and the request thread always show the AI notice (`11` §6).
- **Observability:** every agent turn and tool call is recorded, in Langfuse plus our own `agent_runs` / `agent_tool_calls` tables.
- **Security:** follow the [threat model](docs/10_threat_model.md). A change that adds an attack surface (an endpoint, tool, input, third party or role) updates it. Order and request numbers are random (`R-7K3Q2F`). Registration never reveals whether an email has an account. Admins log in with TOTP. The login token travels in the `Authorization` header.

## 5. Reading map: read before working on…

| Working on | Read |
|---|---|
| Any rule, state, limit, timer, number or invariant | [04_domain_rules.md](docs/04_domain_rules.md) (**source of truth**) |
| Tables, migrations, models, locking, retention, seeding | [05_database.md](docs/05_database.md) |
| Stack, components, agent tools, repo layout | [02_architecture.md](docs/02_architecture.md) (repo layout in §6) |
| Local setup, AWS, deployment, login across two sites, how we check changes | [12_infrastructure.md](docs/12_infrastructure.md) |
| Security: auth, access, limits, attack surfaces, what third parties receive | [10_threat_model.md](docs/10_threat_model.md) |
| The frontend: look, components, states, accessibility, structure | [11_ui_design.md](docs/11_ui_design.md) + the v2 design canvas (link in §2) |
| Screens and flows; what the agent says and when (AF-, RF-, CS-, PS-, AS- IDs) | [03_user_flows.md](docs/03_user_flows.md) |
| Agent turns, conversation state, case state | [ADR-001](docs/adr/ADR-001-conversation-state-and-agent-turns.md) |
| Why the design looks the way it does | [reviews/design_review_01.md](docs/reviews/design_review_01.md), [design_review_02.md](docs/reviews/design_review_02.md) |
| Original pitch | [DawaLink_Project_Proposal.md](DawaLink_Project_Proposal.md) |

**If docs conflict:**
- `04` wins on rules and numbers, and `05` wins on the schema.
- Raise the conflict with the user rather than picking silently.
- Changing a validated decision needs a new row in the decision log. A change to what the product does needs the user's approval first; a purely technical change is Claude's to make (see "Who decides what" at the top).

## 6. Tech at a glance (details in [02](docs/02_architecture.md))

- **Backend:** Python 3.12, FastAPI, Pydantic v2, uv.
- **Database:** PostgreSQL 16, SQLAlchemy 2.0 (sync, psycopg 3), Alembic.
- **Agent:** LangGraph.
- **Background work:** a worker running the clock check (no jobs table).
- **Chat:** SSE streaming for replies + polling for new cards.
- **Auth:** server-side sessions (opaque token in the `Authorization` header + `sessions` table); admins also use TOTP. Cognito replaces password storage, email verification and TOTP before deploying (`12` §10).
- **Frontend:** React + TypeScript, Mantine.
- **Hosting:** AWS Ireland, set up by hand: ECS Fargate (regular, public subnets), a public ALB, two CloudFronts (website on S3, API on the ALB), RDS, SES.
- **LLM by stage:**
  - a fake scripted LLM in tests;
  - Ollama `qwen2.5:7b` for development;
  - a Claude model through Anthropic's API, chosen by measurement, for evaluation and the demo, paid by API credits from Mohammed's Max plan ($100 per billing cycle, no rollover).
- **Commands** (the full list is in the root [README.md](README.md)):
  - everything: `docker compose up --build` (website http://localhost:5173, API http://localhost:8000);
  - backend, inside `backend/`: `uv run --env-file ../.env pytest` · `uv run ruff check .` · `uv run ruff format .` · `uv run mypy`;
  - after an API change: `uv run python -m dawalink.ops.export_openapi ../docs/openapi.json`, then `npm run gen:api` inside `frontend/`;
  - website, inside `frontend/`: `npm test` · `npm run lint` · `npm run typecheck` · `npm run build`.

## 7. Environment notes

- **Machine:** Windows 11. PowerShell is the main shell; Git Bash is also available.
- **Local LLM:** Ollama 0.40.3 on an RTX 3070 Laptop (8 GB VRAM, 16 GB RAM).
- **Local ports:** the project's PostgreSQL container is at `127.0.0.1:5433` (a Windows PostgreSQL service holds 5432). Use `127.0.0.1`, not `localhost`, for the database: `localhost` tries IPv6 first here and waits for seconds.
- **Slow downloads:** `npm install` and Docker pulls can take many minutes on this connection; run them in the background.
- **Console encoding:** the console uses cp1252, so printing emoji from Python fails. Set `PYTHONIOENCODING=utf-8` or avoid printing them.
- **Helper scripts:** write multi-line Python helpers to a file and run them. Don't inline them in shell heredocs.
- **Doc conventions:**
  - status icons: ✅ validated · 🟡 draft or living · ⏳ not started;
  - each doc opens with an "In short" section;
  - new step docs are named `NN_topic.md` and added to the README table.
