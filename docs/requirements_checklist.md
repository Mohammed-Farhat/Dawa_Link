# DawaLink: Requirements Compliance Checklist (living)

**Source:** `Project_Requirements.md` (Agentic Systems 503N/798S).
**Purpose:** every requirement maps to a **concrete artifact**, where it lives in the repo, and the phase that produces it. We update the **Status** column as work lands. Submission happens only when every row is ✅.

**Phases:**
- **Design:** docs 00–12.
- **Build:** every pull request.
- **Evaluate:** evaluation runs.
- **Deploy:** AWS.
- **Submit:** final package.

**Status:** ✅ done · 🟡 in progress · ⏳ not started.

---

## 1. How we guarantee it during development

### 1.1 Definition of Done for every pull request
A PR is merged only when **all** of the following hold:

| # | Check | Requirement it serves |
|---|---|---|
| 1 | The PR description names the feature (C-), rules (R-, SM-, INV-) and Failure Matrix rows it implements | Traceability; technically defensible |
| 2 | **Tests:** the happy path **plus every failure path** listed for this feature in the Failure Matrix; every invariant it touches; an **unauthorized-access test** for every new endpoint or tool | "Test beyond the happy path" |
| 3 | **CI is green:** lint (ruff), type check (mypy), tests with a coverage threshold, offline evaluation gate, security scans | QA; bonus CI/CD |
| 4 | **Observability:** every new LLM or tool call is traced; errors are logged with a code; the relevant metrics are emitted | AgentOps & observability |
| 5 | **Security:** input validation via schemas, ownership checks, no secrets in code, PII never sent to the LLM | Safety & security |
| 6 | **Docs updated:** Failure Matrix rows, threat model (if a new attack surface), API docs (OpenAPI is generated automatically), README (if setup changed), decision log (if a decision changed) | Documentation, reproducibility |
| 7 | **A teammate reviewed it and wrote a short summary of what it does** | "Students remain responsible for understanding… all submitted code" |

### 1.2 What the running system records automatically

| Recorded | Where | Covers |
|---|---|---|
| **Every LLM call:** input and output (PII-redacted), model, prompt version, tokens, cost, latency, retries, errors | Langfuse traces | "Agent traces", "logs and traces across model/tool interactions" |
| **Every tool call:** inputs, result or refusal reason, latency, failures | Langfuse (inside the same trace) + logs | Tool failures, retries |
| **Per assistant turn and per conversation:** success / fallback / guardrail triggered, cost | `agent_runs` table + admin dashboard (AS-10) | Task success, cost per successful task, agent errors |
| **Application logs:** JSON with request and trace IDs | CloudWatch (and the console locally) | Error handling, debugging |
| **Every state change**, with its actor | `audit_events` table | Human approval and accountability evidence |
| **Business metrics:** reservations, [Not available] rate, no-shows, early-release acceptance, units saved | Database → admin dashboard + evaluation reports | Task success, real-world value |
| **Infrastructure cost** | AWS Cost Explorer + budget alerts | System cost |

> ⚠️ **Langfuse's free tier keeps traces for 30 days.** We **export evidence** (selected traces, metrics summaries, evaluation results) into the repo (`eval/results/`, `docs/evidence/`) after each evaluation run, so graders can see it at any time.

---

## 2. Guardrails and scope

| ID | Requirement | What we deliver | Where | Phase | Status |
|---|---|---|---|---|---|
| G-1 | No healthcare projects | Logistics-only boundary; the professor proposed and approved the topic (approved proposal and poster), cited in the report | `01` §1, report | Design + Submit | ✅ |
| G-2 | Problem before technology | Proposal and poster; scope chosen before the stack | proposal, poster, `01` | Design | ✅ |
| G-3 | Agentic justification; what stays deterministic or human | Boundary tables, plus **measured** agent vs the search baseline **and vs a no-AI scripted policy** using the same tools | `01` §5, `02` §3, `04` §7, `08`, report | Design + Evaluate | 🟡 |
| G-4 | Identify **and evaluate** ≥ 1 real-world constraint | 7 constraints with measurements (stale inventory, pharmacy response, latency, cost, privacy, **location privacy**, human approval): suite E6 | `01` §9, `08` E6, results | Evaluate | 🟡 |
| G-5 | AuthN/Z, least privilege, secret and PII protection, I/O validation, prompt-injection defenses, human approval | Controls mapped in the threat model (`10` ✅ §7) + implemented controls + security tests | `01` C13, `04` R-AU, `10`, `tests/security/` | Design + Build | 🟡 |
| G-6 | Safe handling of bad or malicious input and external failures | Failure Matrix (`09` ✅: 122 modes, principles P1–P8) + failure-injection tests (`09` §8) | `09`, `tests/` | Build | 🟡 |
| G-7 | Public, authorized or synthetic data with provenance and ToS | MoPH source and date on every product; dataset description sheets; seeded synthetic generators | `04` R-C1, `eval/datasets/README.md` | Build + Evaluate | 🟡 |
| G-8 | Track model/API usage, system cost, **cost per successful task** | Langfuse + `agent_runs` + AWS cost; cost per fulfilled request reported per model (E2, E5) | `08` E2/E5, results, report | Evaluate + Deploy | 🟡 |
| G-9 | Students responsible for AI-written code | Teammate review on every PR (DoD #7); an **AI-usage statement** in the README and report | PRs, README, report | Build + Submit | ⏳ |

## 3. Final submission deliverables

| ID | Deliverable | What exactly | Where | Phase | Status |
|---|---|---|---|---|---|
| D-1 | Live demo + poster | Demo script covering the 17 scenarios (`01` §6) and the security challenges (`10` §9.3), **including failures and attacks**; the **demo clock** (AS-12, demo mode only); a recorded backup | `01` §6, `docs/demo_script.md` | Submit | 🟡 |
| D-2 | Full GitHub repo with setup and reproducibility docs | README: run everything locally with one command; seed data; how to run tests and reproduce the evaluation; `.env.example` | repo root | Build | ⏳ |
| D-3 | Evaluation suite, experiments, results | Plan ✅ (`08`): U-set, R-set, simulation, P-set; suites E1–E6; results in `eval/results/` | `eval/`, `08` | Evaluate | 🟡 |
| D-4 | Agent traces and operational metrics | Langfuse project + **exported traces and metrics** in the repo | `docs/evidence/`, `eval/results/` | Evaluate + Deploy | ⏳ |
| D-5 | Failure analysis and security/threat analysis | Failure Matrix (`09` ✅), threat model (`10` ✅), failure analysis of evaluation errors | `09`, `10`, `08` | Design + Build + Evaluate | 🟡 |
| D-6 | Architecture and API documentation | Architecture, database and API docs + exported OpenAPI spec | `02`, `05`, `06`, `docs/openapi.json` | Design + Build | 🟡 |
| D-7 | Final technical report | Problem, users, agentic justification, design choices and alternatives, evaluation, constraints, failures, security, limitations | `docs/report/` | Submit | ⏳ |
| D-8 | **Evidence, not only prepared examples** | Held-out tests (40% locked), 5 seeds × 100 simulated requests per contender, regression tests from real failures (`08` §5–§6) | `eval/`, `tests/regression/` | Evaluate | 🟡 |

## 4. Technical expectations

| ID | Requirement | What we deliver | Where | Phase | Status |
|---|---|---|---|---|---|
| T-1 | Agent core: explicit responsibilities and boundaries | One agent, two modes (assistant + sourcing); tools vs automatic code vs humans | `02` §3, `04` §7, `07` | Design | 🟡 |
| T-2 | Tools with validated interfaces | Typed schemas for every tool (`07` §4 ✅); error codes; tests | `07`, `tests/agent/` | Design + Build | 🟡 |
| T-3 | Memory: scope, lifetime, retrieval, privacy | Chat and request threads + case state + proposals; 30 days; loaded at each turn; PII-free | `02` §3.3, `04` R-RET, `07` | Design + Build | 🟡 |
| T-4 | Logs and traces across model/tool interactions | Langfuse + structured logs | §1.2 above | Build | ⏳ |
| T-5 | Metrics: end-to-end, model and tool latency, tokens, cost, task success, tool failures, retries, agent errors | `agent_runs` + Langfuse + dashboard + evaluation report | `05`, AS-10, `08` | Build + Evaluate | ⏳ |
| T-6 | Retries, timeouts, fallbacks, schema validation, error handling, graceful degradation | Clock-check retries, LLM timeouts, degraded mode, validated tool outputs | `04` R-T10, SM-12, `01` C15, code | Build | ⏳ |
| T-7 | Authorization, least privilege, secret management, injection defenses | Server-side sessions; role and ownership checks; client-scoped tools; **cards only from tools**; no pharmacy text to the LLM (except approved names); Secrets Manager; **admin TOTP**; threat model (`10` ✅) | `02`, `04` R-AG7/R-AG8/R-AU, `10` | Design + Build + Deploy | 🟡 |
| T-8 | **Test beyond the happy path:** invalid/ambiguous input, API/tool failures, malformed responses, rate limits, malicious input, unauthorized actions | One test category per item (§6 below) | `tests/` | Build | ⏳ |
| T-9 | **Maintain a Failure Matrix** | Living document (`09` ✅), updated in every PR; every row ✅ or an accepted limitation before submission | `09` | Build | 🟡 |
| T-10 | Failure analysis + lightweight threat model | Threat model ✅ (`10`: assets, attackers, trust boundaries, 55 threats with tests, OWASP LLM Top 10, accepted risks); analysis of failures found in evaluation | `10`, `08` | Design + Evaluate | 🟡 |
| T-11 | Evaluation: baselines, metrics, data, held-out testing | Search-page baseline + **no-AI scripted policy**; understanding set dev/held-out; simulation with several runs per setup; targets fixed before held-out runs | `08`, `eval/` | Evaluate | 🟡 |
| T-12 | Adversarial testing; **failures → regression tests** | R-set (~120 attacks, target 0 violations); 👎 report → admin confirms → regression case | `08` E4/§5, `eval/safety/`, `tests/regression/`, AS-8 | Build + Evaluate | 🟡 |
| T-13 | API and interface contracts: schemas, validation, auth, error behavior | Endpoint contracts (`06` ✅) + generated OpenAPI + contract tests (3 per endpoint, every error code, Schemathesis) | `06`, `tests/api/` | Design + Build | 🟡 |
| T-14 | Clean, modular code: separation of concerns, naming, no duplication, centralized config, secure dependencies and secrets, consistent errors, **no dead code** | Repo structure, `config.py`, linters, review checklist, dependency scanning | `02` §6, CI | Build | ⏳ |
| T-15 | UI designed around the user, not chat by default | Search page + assistant with cards; role-specific portals | `03`, `11` | Design + Build | 🟡 |
| T-16 | Reproducibility | Docker Compose, uv lockfile, seeds, "reproduce the results" commands | README, `eval/` | Build + Evaluate | ⏳ |

## 5. Bonus engineering practices (up to +10%)

| ID | Practice | What we do | Status |
|---|---|---|---|
| B-1 | Engineering workflow | GitHub Projects board, PRs with reviews, branch protection on `main` | ⏳ |
| B-2 | CI/CD | GitHub Actions: build, test, deploy with gates (deploy only if CI is green) | ⏳ |
| B-3 | Code quality automation | ruff, mypy, coverage reports (Codecov or SonarCloud, both free for public repos) | ⏳ |
| B-4 | Agent evaluation automation | Every PR: deterministic gates (P-set, guard rules, no-AI simulation); agent PRs: an LLM subset gate (0 safety violations, accuracy within 3 points), `08` §7 | 🟡 |
| B-5 | Advanced AgentOps | Langfuse: traces, cost, latency, prompt versions | ⏳ |
| B-6 | DevSecOps | CodeQL, Dependabot, secret scanning, Trivy image scan | ⏳ |
| B-7 | Reproducible deployment | Docker, **CDK (infrastructure as code)**, Alembic migrations run automatically on deploy | ⏳ |
| B-8 | Advanced testing | API contract tests, a load test (e.g. Locust), a red-team suite | ⏳ |
| B-9 | Production monitoring | CloudWatch alarms + admin alerts (AS-10); optionally Sentry (free tier) | ⏳ |
| B-10 | Controlled evolution | Versioned prompts, model as config, evaluation results per version, feature flags (e.g. early release on/off for comparisons) | ⏳ |

## 6. Test categories (how T-8 is covered)

| Category | Examples | Folder |
|---|---|---|
| Unit (pure rules) | Every rule and invariant in `04`: pricing, deadlines, prescription rule, limits, eligibility zones | `tests/unit/` |
| Integration (DB + services) | Order lifecycle end to end; two clients racing for the last box; upload sync with reserved stock | `tests/integration/` |
| API contract | Every endpoint: valid and invalid payloads, error codes, auth required | `tests/api/` |
| Agent (fake LLM) | Tool selection, re-planning when an option fails, malformed LLM output, LLM timeout → degraded mode | `tests/agent/` |
| **Invalid / ambiguous input** | Bad dates, negative quantities, messy uploads, "augmentin" with no strength | unit + agent |
| **External failures** | LLM down or slow, SES down, DB timeout, worker crash in the middle of a clock check and resume | `tests/failure/` |
| **Malformed responses** | LLM returns invalid JSON or calls an unknown tool or uses bad arguments | `tests/agent/` |
| **Rate limits** | Chat flood, login brute force, early-release spam | `tests/security/` |
| **Malicious input** | Prompt injection in chat, in uploaded names and in pharmacy fields; formulas in CSV; oversized files | `tests/security/` |
| **Unauthorized actions** | Pharmacy A touching pharmacy B's order; client reading another client's data; the agent attempting to create an order; a forged or reused card proposal | `tests/security/` |
| Regression | Every confirmed failure (from tests, evaluation or 👎 reports) gets a permanent test | `tests/regression/` |
| Evaluation (not in normal CI runs) | Understanding set, end-to-end simulation, safety set, model comparison | `eval/` |
| Load (bonus) | Search and chat under concurrent users | `tests/load/` |

## 7. Grading rubric → where the evidence is

| Rubric area | Weight | Main evidence |
|---|---|---|
| Idea, problem formulation, agentic justification | 20% | `01`, `02` §3, `04` §7, report; measured agent vs baseline |
| Agent performance / evaluation | 20% | `08`, `eval/results/`, held-out and simulation results, model comparison |
| AgentOps and observability | 15% | Langfuse, `agent_runs`, admin dashboard, exported traces |
| Reliability, QA, security | 15% | Failure Matrix, threat model, `tests/` categories, CI |
| Software engineering | 10% | Repo structure, CI quality gates, PR reviews |
| Poster and live demo | 10% | Demo script with failure and attack scenarios |
| Documentation and reproducibility | 10% | README, docs 00–12, one-command setup, reproduce-the-results commands |
| Bonus | +10% | §5 |

## 8. Open items affecting compliance

| ID | Item | Why it matters |
|---|---|---|
| Q-1 | ~~Public or private GitHub repo?~~ **Resolved 2026-10-13: public** (enables free CodeQL, secret scanning, SonarCloud, Codecov) | ✅ |
| Q-2 | Who pays for the real LLM (O2) | Needed for evaluation runs and the demo |
| Q-3 | ~~Approval proof and pharmacist interviews (review #2 D1, D2)~~ | **Dropped by the team (2026-10-18):** the proposal and poster phase is complete; the report cites the approved proposal. The simulation uses stated assumptions about pharmacy behavior, tested across a range of values. |
