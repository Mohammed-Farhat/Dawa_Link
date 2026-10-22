# DawaLink: guide for Claude Code sessions

DawaLink connects clients who can't afford a medicine at full price with pharmacies selling **near-expiry stock at a discount**. The needs are **urgent**: the client reserves now and picks up within a day or so. At its center is **one agent with two modes**: a chat **assistant**, and an **autonomous sourcing agent** that owns a client's request for 1–5 medicines during a **6-hour search window**. **The agent's purpose (the professor's words): bring the client's need to the right pharmacy.** It **decides** which pharmacy or route, from facts computed by code.

- **Course:** Agentic Systems 503N/798S, Dr. Ammar Mohanna, Fall 2026, **Path A** (application). The professor proposed and approved the topic. The scope stays **logistics-only** (no clinical functions).
- **Team:** Mohammed Farhat (repo owner), Mohamad Natafgi, Anthony John Kanaan. They know **Python only**. **Claude writes all the code**, and the team reviews every PR.
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
2. [docs/requirements_checklist.md](docs/requirements_checklist.md): every requirement mapped to an artifact, plus the **Definition of Done** for every PR (§1).
3. [docs/01_scope_and_features.md](docs/01_scope_and_features.md) §1–§6: the product, the agent's features, why an agent, the demo scenarios.
4. The doc for the **current step** (§2 below) and the docs it says it builds on.

## 2. Where we are

The status column in [docs/README.md](docs/README.md) is the source of truth. As of 2026-10-22:

- **Planning steps 00–11 are all validated** (decision log sections A–U). **Current versions:**
  - `01` v5.1 · `02` v3.1 · `03` v4.2 · `04` v4.1 · `05` v3.1;
  - `06` v1.2 · `07` v1.2 · `08` v1.1;
  - `09` v1.2 (living: every PR updates it) · `10` v1.1 (threat model; living: a PR that adds an attack surface updates it);
  - `11` v1.0 (UI design) + the design canvas https://claude.ai/artifact/HYBxFhP96TUvhi1V9cCDLG (the user's private artifact; read it with the Artifact tool);
  - ADR-001–004.
- **History of the big changes:**
  - [design review #2](docs/reviews/design_review_02.md) (§N, 2026-10-13);
  - API, agent, evaluation and Failure Matrix (§O–§R, 2026-10-18 to 10-20);
  - the threat model (§T, 2026-10-22): random order numbers, admin two-factor login, registration never reveals an account, plain-text agent replies, layered LLM cost caps, "reliability" removed (app stock is assumed real; [Not available] kept);
  - the UI design (§U, 2026-10-22): a search-first home, one meaning per color, cards rendered from proposals, WCAG AA, low-end phones; 10 boards on the design canvas. The UI can still change during the build; 4 more boards (CS-15, CS-7, PS-6, AS-10) will be drawn when the user asks.
- **The professor's guidance (2026-10-20) is applied** across 01–09 (decision log §S, [ADR-004](docs/adr/ADR-004-agent-decides-the-pharmacy.md)): the agent decides the pharmacy; real locations and road travel times; the expiry fit (days of use + pickup day); no fixed minimum before expiry.
- **Next: step 12, Infrastructure and CI/CD** (the last planning step). ⚠️ **Don't start it until the user explicitly says to.**
- **After planning:** build → test → evaluate → deploy → report and demo.
- **No code exists yet.** The repo holds the planning docs; the user commits and pushes doc updates themselves.
- **Open items:**
  - O1: which LLM model (chosen by measurement);
  - O2: who pays for the real LLM (needed only for the evaluation runs and the demo);
  - TM-D10, end-of-project hygiene (scan evidence before export, push protection, backup retention, delete everything after the demo): **postponed to the end** by the user. Don't raise it before then.
- **Team tasks (not Claude's):**
  - write and label the ~300-request understanding set (Arabizi / Arabic / English);
  - create realistic inventory files in the upload template;
  - review every PR.

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
6. **Code is for Python developers to review.**
   - Readable, typed, small PRs.
   - Every PR explains what changed and why, in plain language, and meets the Definition of Done.
7. **Git and publishing:**
   - Never commit, push, publish, or change `.gitignore` without the user's explicit permission.
   - Since 2026-10-18, `/docs`, `CLAUDE.md`, `DawaLink_Project_Proposal.md` and `Project_Requirements.md` are **tracked** (the user changed `.gitignore` so the team can read them). The user commits and pushes these updates themselves.
   - The repo is public: nothing secret or personal goes in tracked files. Before any doc is committed, check it for emails, keys and tokens.
8. **Secrets and privacy:**
   - Secrets live in `.env` locally and in AWS Secrets Manager in production, and are never committed.
   - **No PII is ever sent to the LLM.**
9. **Communication:** plain language, short, a recommendation rather than a survey of options. Explain technical terms the first time.

## 4. Design rules that must never be broken

The details are in the linked docs. If a request or code change would break one of these, stop and raise it.

- **The agent proposes; the client's tap executes** through the API. Agent tools never create, accept or cancel orders or requests, and never change priority, prices or stock ([02 §3](docs/02_architecture.md), [04](docs/04_domain_rules.md) R-AG).
- **Cards come only from tools** (stored proposals); a tap sends the proposal ID, and the API re-validates it. **Text typed by pharmacies never reaches the LLM**, except the admin-approved pharmacy name (04 R-AG7, R-AG8). **Agent replies are shown as plain text** (no links, images or HTML; `10` TM-D5).
- **Priority is first come, first served, in code.** Nobody can change it: not the LLM, not an admin ([ADR-003](docs/adr/ADR-003-priority-is-a-rule-not-the-llm.md), amended).
- **The agent decides where the client goes** (ADR-004): code computes the travel times, routes and expiry fit; the agent weighs them with what the client said and recommends one pharmacy with a reason. **Coordinates never reach the LLM** (04 INV-24): location is stored rounded, outside `case_state`.
- **A box is offered only if it lasts the client's days of use** from the chosen pickup day (04 R-F1, INV-25); unknown days → 1 day + an expiry warning.
- **Urgent needs:** requests and watches search for 6 hours and can only be started during request hours. Reservations are **instant** (no pharmacy confirmation); the pharmacy marks [Picked up] or [Not available]; the pickup time is set per pharmacy. A prescription is a **notice** only (04 §1, SM-5, R-P1).
- **Our tables are the source of truth** ([ADR-001](docs/adr/ADR-001-conversation-state-and-agent-turns.md)):
  - LangGraph is stateless per turn;
  - one agent turn runs at a time per conversation (a lease on the conversation row);
  - informational events post template cards with no LLM call; decision events run an agent turn.
- **Time is injected:** `today` and `now` always come from the app's clock (the simulated and demo clocks). Never `CURRENT_DATE`/`now()` for business logic in SQL, or `date.today()` in domain code. `created_at` may be real time (it only orders "who came first") ([04](docs/04_domain_rules.md) R-T11, [05](docs/05_database.md) DB-D6).
- **No jobs table:** one **clock check** loop acts on deadlines stored on the rows (04 R-T10).
- **Derived values are never stored.** The expiry zone and the discount price are computed live.
- **Money** is stored as LBP integers and shown as LBP + ≈USD. **Quantities** are counted in units.
- **Numbers** (windows, limits, timers) live only in [04 §5](docs/04_domain_rules.md). Reference them by ID; don't repeat them.
- **Safety:**
  - no medical advice;
  - alternatives must have the same composition, and are offered only with the client's consent;
  - controlled substances are excluded entirely;
  - a prescription notice by default (the pharmacist checks at the counter).
- **Observability:** every agent turn and tool call is recorded, in Langfuse plus our own `agent_runs` / `agent_tool_calls` tables.
- **Security:** follow the [threat model](docs/10_threat_model.md). A PR that adds an attack surface (an endpoint, tool, input, third party or role) updates it. Order and request numbers are random (`R-7K3Q2F`). Registration never reveals whether an email has an account. Admins log in with TOTP.

## 5. Reading map: read before working on…

| Working on | Read |
|---|---|
| Any rule, state, limit, timer, number or invariant | [04_domain_rules.md](docs/04_domain_rules.md) (**source of truth**) |
| Tables, migrations, models, locking, retention, seeding | [05_database.md](docs/05_database.md) |
| Stack, components, agent tools, repo layout, deployment | [02_architecture.md](docs/02_architecture.md) (repo layout in §6) |
| Security: auth, access, limits, attack surfaces, what third parties receive | [10_threat_model.md](docs/10_threat_model.md) |
| The frontend: look, components, states, accessibility, structure | [11_ui_design.md](docs/11_ui_design.md) + the design canvas (link in §2) |
| Screens and flows; what the agent says and when (AF-, RF-, CS-, PS-, AS- IDs) | [03_user_flows.md](docs/03_user_flows.md) |
| Agent turns, conversation state, case state | [ADR-001](docs/adr/ADR-001-conversation-state-and-agent-turns.md) |
| Why the design looks the way it does | [reviews/design_review_01.md](docs/reviews/design_review_01.md), [design_review_02.md](docs/reviews/design_review_02.md) |
| Original pitch | [DawaLink_Project_Proposal.md](DawaLink_Project_Proposal.md) |

**If docs conflict:**
- `04` wins on rules and numbers, and `05` wins on the schema.
- Raise the conflict with the user rather than picking silently.
- Changing a validated decision needs the user's approval and a new row in the decision log.

## 6. Tech at a glance (details in [02](docs/02_architecture.md))

- **Backend:** Python 3.12, FastAPI, Pydantic v2, uv.
- **Database:** PostgreSQL 16, SQLAlchemy 2.0 (sync, psycopg 3), Alembic.
- **Agent:** LangGraph.
- **Background work:** a worker running the clock check (no jobs table).
- **Chat:** SSE streaming for replies + polling for new cards.
- **Auth:** server-side sessions (opaque cookie + `sessions` table); admins also use TOTP.
- **Frontend:** React + TypeScript, Mantine.
- **Hosting:** AWS ECS Fargate (regular, public subnets), internal ALB behind one CloudFront (VPC origin), RDS, SES, built with CDK (Python).
- **LLM by stage:**
  - a fake scripted LLM in tests and CI;
  - Ollama `qwen2.5:7b` for development;
  - the real model, chosen by measurement, for evaluation and the demo.
- **Commands:** none yet. Add the run, test and lint commands here when the code skeleton lands.

## 7. Environment notes

- **Machine:** Windows 11. PowerShell is the main shell; Git Bash is also available.
- **Local LLM:** Ollama 0.40.3 on an RTX 3070 Laptop (8 GB VRAM, 16 GB RAM).
- **Console encoding:** the console uses cp1252, so printing emoji from Python fails. Set `PYTHONIOENCODING=utf-8` or avoid printing them.
- **Helper scripts:** write multi-line Python helpers to a file and run them. Don't inline them in shell heredocs.
- **Doc conventions:**
  - status icons: ✅ validated · 🟡 draft or living · ⏳ not started;
  - each doc opens with an "In short" section;
  - new step docs are named `NN_topic.md` and added to the README table.
