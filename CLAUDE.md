# DawaLink: guide for Claude Code sessions

DawaLink connects clients who can't afford a medicine at full price with pharmacies selling **near-expiry stock at a discount**. The needs are **urgent**: the client reserves now and picks up within a day or so. At its center is **one agent with two modes**: a chat **assistant**, and an **autonomous sourcing agent** that owns a client's request for 1–5 medicines during a **6-hour search window**. **The agent's purpose (the professor's words): bring the client's need to the right pharmacy.** It **decides** which pharmacy or route, from facts computed by code.

You are the owner and long-term maintainer of this codebase, and its design is up to you.

**Who decides what** (agreed with Mohammed, 2026-11-12):
- **Claude decides, without asking first:**
  - how the code is written, structured, named and tested;
  - the database's technical design: tables, constraints, indexes, migrations, locking;
  - internal architecture, refactoring, and fixing anything that is wrong;
  - `.gitignore`, and the non-secret settings in the local `.env` (Mohammed, 2026-11-14: "you have full control on the codebase and the gitignore").

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

The status column in [docs/README.md](docs/README.md) is the source of truth for the plan, and [docs/build_plan.md](docs/build_plan.md) for the build: read it at the start of every session, and update it at the end of every build step. As of 2026-11-15:

- **Planning steps 00–12 are all validated** (decision log sections A–W). **Current versions:**
  - `01` v5.6 · `02` v3.6 · `03` v4.19 · `04` v5.13 · `05` v3.11 (the schema as built);
  - `06` v1.20 (§12: the API as built) · `07` v1.17 (§14: the agent as built; prompts v1.13) · `08` v1.10;
  - `09` v1.26 (living: every change updates it) · `10` v1.15 (threat model; living: a change that adds an attack surface updates it);
  - `12` v2.6 (infrastructure and deployment);
  - `11` v1.9 (UI design) + the **v2 design canvas**, the visual reference: https://claude.ai/artifact/1pEPY1g3zNtYZX3Sbzv3mx (the user's private artifact; read it with the Artifact tool). The v1 canvas is kept as history: https://claude.ai/artifact/HYBxFhP96TUvhi1V9cCDLG;
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
    - a later pickup day leaves fewer days before the box expires, and the agent passes the client's day to the tools;
    - the catalog is the Ministry's price list joined with its drug database pages; the Ministry's files stay outside git, in `backend/data/moph/` (BLD-D3, 2026-11-12).
- **The professor's guidance (2026-10-20) is applied** across 01–09 (decision log §S, [ADR-004](docs/adr/ADR-004-agent-decides-the-pharmacy.md)): the agent decides the pharmacy; real locations and road travel times; the expiry fit (days of use + pickup day); no fixed minimum before expiry.
- **Planning is finished, and the build started on 2026-11-10.** Order: build → test → evaluate → switch to Cognito → deploy → report and demo.
- **Built so far:** steps 1 to 5 of 12:
  - the code skeleton and the domain core (2026-11-10; `backend/src/dawalink/domain/`: the rules of `04` as plain, tested Python);
  - the database (2026-11-12): the tables (36 since 2026-11-18) and the first migration, four database logins, the catalog import (5,628 real medicines) and the demo seed. `05` §12 lists what changed while building;
  - the services (2026-11-12; `backend/src/dawalink/services/`): search, reserve and group reserve, the counter, watches and matching, offers, early release, sourcing requests, inventory and CSV uploads, the worker's clock-check tasks, email sending (caught locally by mailpit) and the daily purge. The second migration. Race tests with two real connections in `backend/tests/races/`.
  - the agent (2026-11-13; `backend/src/dawalink/agent/`): the turn graph, the 17 tools and `reply`, cards and what a tap does, the guards, the prompts, the models (scripted for tests, Claude, Ollama as a spare), worker turns, road times from OpenRouteService, tracing. The third migration. `07` §14 says what is where and what changed while building. Talk to it with `python -m dawalink.ops.chat`.
  - after step 5 (2026-11-14, decision log BLD-D12 to BLD-D14): the owner's answers to Q9 to Q12; **the 18th tool, `set_area`** ("I'm in Hamra": the name is looked up in our own list, `backend/data/areas.csv` → the `areas` table; exact names only; the agent gets names, never a point); the fourth migration; prompts v1.1; **Langfuse proven with real keys** (only our own steps are exported). `07` §14.6;
  - the place list from OpenStreetMap (2026-11-14, decision log BLD-D15): `backend/data/areas_osm.csv`, **generated** (never edit it by hand), adds 1,733 towns and villages to the hand-written `areas.csv`: 1,853 places; the hand-written centres are the map's own; prompts v1.2. A name that exists in several districts ("Hamra" in Beirut, "El Hamra" in Nabatieh) is asked about, never chosen (confirmed by the owner, Q14);
  - **another brand is shown, never reserved** (2026-11-14, decision log BLD-D17, `07` §14.7): the 19th tool, `show_other_brand`, makes a card with "ask the pharmacist first" and the pharmacy's phone (added on display; it never passes the model). `propose_reservation` refuses another brand unless the client asked for it in a message of their own; watches, waiting items, offers, early release and plans are for the medicine itself. The fifth migration; prompts v1.3. Found on the real runs and fixed (BLD-D18): the tool list sent to Claude never changes within a turn;
  - **a closed request opens again when one of its boxes is lost** (2026-11-15, decision log BLD-D21, `04` R-RQ12): a request closes as soon as everything is reserved; if a reservation is then marked not available, or cancelled by the system, before the request's 6 hours are over, the request is OPEN again and the agent re-plans. Never after the 6 hours, never a request the client cancelled, never a medicine the client gave up on. No schema change. The simulation's assumptions are approved (BLD-D22, `08` v1.5). Two planner fixes (BLD-D23): a plan never has a stop that buys nothing, and one function chooses the pharmacies a plan weighs (the 16 nearest by road, plus the cheapest for each medicine; with more than 16, the road times from the client to all of them are asked for first). The P-set is built: `uv run python -m dawalink.evals.plan_set` inside `backend/` must say "all exact" before a planner change is kept;
  - decided, not built yet (BLD-D16, 2026-11-14): **a client can pick their place on a map** ("Pick on the map"), for a computer or a client who won't share the device's location. The point is treated like a shared location. It is built with the website screens (step 8).

  The steps, their order and the log are in [docs/build_plan.md](docs/build_plan.md).
- **In progress: step 6, the simulator and the evaluation** (started 2026-11-14; its slices E0 to E13 and their status are in [docs/build_plan.md](docs/build_plan.md) §3: read them first). Everything runs without a paid model first. **Step 6 is committed (2026-11-15) as "tools built, development results".** ⚠️ **Since 2026-11-16 the owner's rule is: build the rest through to the end** ("you can start with part 7 and complete everything we have left in the project"). **He commits once, when step 7 is completely finished** (the evening of 2026-11-16: "After finishing continue working, I will commit once when step 7 is completely finished"; he had committed slices 7a to 7e one by one). Claude builds slice after slice without stopping for a commit, keeps a copy of the uncommitted work after each slice (`Documents/Dawa_Link_backups/`), and at the end of step 7 runs every check and the scan for secrets, then gives him the commands. Slices 7a to 7g and hardening no longer wait for a "start"; **what the product does is still asked first**, AWS and Cognito stay the owner's, and the agent's final evaluation (a new model, new cases, an architecture change) is done with him afterwards. Keep [docs/build_plan.md](docs/build_plan.md) current after every slice. **State on 2026-11-15:** the development datasets are complete (180 messages, 70 attacks, 50 plan baskets); the three contenders, the two suites' runners and scorers, the statistics, the report (`python -m dawalink.evals.report`), the sweeps, the ablations and the free checks before a commit (`python -m dawalink.evals.before_commit`) are built; prompts are at v1.13 (the agent asks first, waits, and asks again for what an answer left out, BLD-D28, BLD-D29; a name in Arabic script is read sound by sound; several missing medicines get the [Start sourcing] card, never several watches); a second no-AI policy asks the same fixed question (`rules_asking`); suites E1 and E4 play the client's answer as a second turn; **a seventh suite, E7, has a second model play the client** (`python -m dawalink.evals.run_conversations`, the owner's Q34); every paid run is saved under `eval/results/`, and all of them are development results. **The owner agreed on the order from here** ([docs/build_plan.md](docs/build_plan.md) §2, "The order from here"): close step 6 as "tools built, development results"; then the website with its API, one side at a time, the client's chat first; then hardening; then the final evaluation on the finished agent with the held-out data; Cognito and AWS last; the report and the demo. **Decided the same evening (BLD-D30):** no cart on the search page; **no request form: a sourcing request starts only in the chat**, from the agent's [Start sourcing] card; a simulated client answers a question within 1 to 3 minutes. **Nothing waits for the owner** except his read of the second batch of cases. **Done on 2026-11-16: slice 7a** (logins, and the client's chat with the agent in the browser: sign up, the confirmation email, the chat with its cards, the pickup ticket; decision log BLD-D31, `06` §12). **Done the same day: slice 7b** (search and reserve without the agent: the search page, a pharmacy's offer, the reserve sheet; search is a `POST` so that the client's location is never in an address). **And slice 7c** (the pharmacy's counter: its Today screen with the order-number box, [Picked up] and [Not available], early-release asks; its portal is a separate part of the website, loaded only for a pharmacist). **And slice 7d** (sourcing requests in the browser: the request's page with its tracker and thread, offers with [Accept and reserve], the demo clock's endpoints for an admin). **And slice 7e** (the rest of the pharmacy's side: registration with a map pin, the inventory and its stock files, listings with the pharmacy's own price, settings; decision log BLD-D32). **Stock files are CSV only** (the owner, Q40). Slices 7a to 7e are committed and pushed; **what follows is uncommitted until step 7 is finished.** **The owner's answers of 2026-11-16 (BLD-D33):** an approved pharmacy changes its own phone, address and pin (Q42, Q45); dates in a stock file stay as built (Q43); a stock file has an optional `code` column (Q44); a reply from DawaLink's team reaches the client as typed, a phone number included (Q46). **And the first half of slice 7f** (BLD-D34): the admins' login with a code (`/admin/login`; an admin is made with `python -m dawalink.ops.create_admin`), approvals and corrections of pharmacies, escalations with replies signed "DawaLink team", the thumbs-down and its review, the audit log, the demo clock's screen. **And its second half on 2026-11-17** (BLD-D35): suspending and reinstating a pharmacy or a client, clients as an ID and counts with an audited contact view, the no-show contest ([I picked it up]), abuse flags, the read-only catalog, one Health page with the alerts. **The admin's side is complete. And slice 7g** (BLD-D36): [Notify me] and watches, notifications for clients and pharmacies, the profile, "Pick on the map", the price limit on search, and on a computer a top bar with the assistant beside the page. **Step 7 is built: the whole API (`06` §6) and the whole website** (finished 2026-11-17; the owner commits it as one commit, and hardening after it as its own). **Step 9, hardening, is done** (2026-11-17; decision log BLD-D37 to BLD-D39; its log and what it leaves are in the build plan §3): the API's contract is walked and fuzzed (`tests/api/test_contract.py`, `test_fuzz.py`), three server errors and two account-discovery leaks are fixed, the worker checks the books once a day, the saved results are scanned for personal data, the website is served compressed (Lighthouse on a simulated phone, measured on 2026-11-17 before the public pages were rebuilt: 95, accessibility 100; to measure again before the demo), and every row of the Failure Matrix has a mark (153 tested, 2 with a stated gap, both for the final evaluation, 6 by hand). **Left for a person:** a screen-reader pass before the demo (`11` §9). **The owner answered Q48 to Q52 on 2026-11-17** (BLD-D38): 30 failed logins from one network address in 15 minutes stop logins from it (N-52; only failed tries count); a pharmacy registration whose email is never confirmed is deleted by the daily clean-up when its link has expired; the agent answers in the client's own language (FM-D6 amended); no GPS accuracy rule; [Warn] on a flag is "Note a warning" and sends nothing. **Hardening is committed and pushed** (2026-11-18, one commit). **The owner is trying the website and reports what he finds, one side at a time** (the client's first, 2026-11-18): each round is fixed, tested, written into the build plan (§3, "After step 9") and committed by him. **Round 1 is built** (decision log BLD-D40, his answers Q53 to Q56): a real desktop layout for the client's portal (top bar, pages in columns, the assistant in a panel that closes); search shows every in-stock medicine for a typed name at once, a misspelled name included and said to be the closest; the assistant's page lists the earlier chats (read, never written in); a password needs 10 characters with a capital, a small letter, a number and a symbol; the profile holds the name in parts, a date of birth, a home town and a place saved on a map (the sixth migration). **Then a break test of the client's side** (BLD-D41; build plan §3): 188 hostile requests through the API and every page in the browser at a computer's and a phone's size. It found and fixed: after [Log out] the previous person's pages stayed on the screen (`09` FS-34); the box to write in was shown under an earlier chat (`09` FI-30); smaller things on the search, the phone layout and names for screen readers. **Round 2 is built** (decision log BLD-D42, his answers Q57 to Q60), after he tried the client's side on his own: no assistant beside the page ("Ask DawaLink" opens its own page; the side panel of round 1 is gone); Home shows what needs the client now and has no search box; the phone's menu is Home · Search · Medicines · Ask · Me; search looks only among what is in stock, from the first letter, with the client's last searches (kept in the account 30 days, the 36th table) and filters for the order, the price and "open now"; the days of use and the pickup day are asked in the reserve sheet; where a client lives is a place on a map (with [Use my location]) or an area, never both, on the sign-up form and in the profile; a pickup reminder every 12 hours and 2 hours before the deadline, never in the first hour (N-8; the seventh migration). **The pharmacy's and the admin's sides are next for him to try.** **Next: the final evaluation (6b), with the owner:** the held-out data (the emergency cases need the label `points_to_emergency_help`), the final runs with the two new checks, the model choice (O1), FA-25 and FA-42. Then Cognito and AWS, which are his. The privacy note on the sign-up form is kept (Q39). Left for the final evaluation: the final runs, the other sweeps, the model comparison, the held-out data.
- **Open items:**
  - O1: which Claude model (chosen by measurement; the provider is settled: Anthropic's Claude API);
  - O7: the no-prescription list stays empty for now (the owner's choice), so every product shows the prescription notice. A short true list may be added before the demo;
  - with registration (step 7): the check of a pharmacy's phone number (`10` TH-59);
  - routing: OpenRouteService first; the owner may switch to Google Maps later (BLD-D9: Google's terms restrict storing travel times, to settle before switching);
  - **the Claude credit:** $100 until 2026-12-09, which is after the demo. One budget for development (the app's budget setting is $20, BLD-D13), the evaluation and the demo. Development turns on Haiku are approved (cents each). **Since 2026-11-15 a paid evaluation run needs no estimate or ok first** (the owner, after checking the console against the app's count: "no need to send me the cost estimate first"). Every run still gets a hard `--max-usd` limit, and its cost is reported afterwards; a run that would cost tens of dollars is announced before it starts. Spent so far: about $15 by the runs' own counts at the end of 2026-11-15 (the pilot cost $0.079, three runs of suite E1 $0.21; a full simulated day of 100 requests on Haiku is about $0.80);
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
   - Never commit, push or publish without the user's explicit permission.
   - **`main` is protected on GitHub** (the owner, 2026-11-18): the ruleset `protect-main` asks for a pull request approved by the code owner (`.github/CODEOWNERS`: the owner), and forbids force pushes and deleting the branch. Only a repository admin bypasses it, so the owner still pushes straight to `main` as before (GitHub then prints "Bypassed rule violations", which is expected). It is a lock for everyone else, not a review process for us: how changes are checked is unchanged (INF-D14).
   - `.gitignore` is Claude's to change since 2026-11-14. Claude says what changed. Before removing a line, Claude checks that it can't put a secret, a personal file or the Ministry's files into the public repo.
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
- **The agent decides where the client goes** (ADR-004): code computes the travel times, routes and expiry fit; the agent weighs them with what the client said and recommends one pharmacy with a reason. **Coordinates never reach the LLM** (04 INV-24): location is stored rounded, outside `case_state`. A client may name their area in chat instead of sharing a location: `set_area` looks the name up in **our own list** (exact names only, never a guess), and the agent is told the area's name only (R-S2, BLD-D14). The list is our hand-written areas plus the towns and villages of OpenStreetMap (BLD-D15); a name in several districts is asked about.
- **After approval, a pharmacy changes its hours, its pickup time, its password, its phone number, its address and its pin** (the owner, 2026-11-16, Q42 and Q45). A new number is checked like the first. A new address or pin counts at once and holds nothing up: the road times to the old pin are dropped, and the admins get a "pin to check". **Its name and its licence are changed only by an admin, with a reason:** the name is what the agent shows to clients (`10` TM-D2, TH-59). **An approval is of what the admin saw** (`CHANGED_SINCE` otherwise), and only a registration whose email is confirmed is in the queue. **Everything a pharmacy types has a plain shape** (`domain/pharmacy_details.py`), and a batch number never reaches the LLM.
- **A stock file is a CSV, read as a spreadsheet writes it.** A date in it that can be read two ways is read only when the file itself shows the order, never guessed; a `code` (the Ministry's number) only chooses among the medicines the row's name already matches, never replaces the name; a box that only a code can name is changed by a row that names it, never by its absence (BLD-D32, BLD-D33).
- **Suspending a client ends their requests and watches first, then their reservations** (`services/admin_clients.py`): the other order would reopen a request (R-RQ12) and start an agent turn for someone who is gone. **An admin sees a client as an ID, a status and counts;** the name, email and phone are one audited view, 30 an hour.
- **An admin's console changes no stock, no price and no priority,** and a test on the API's own description says so. **A reply from DawaLink's team is the one message stored as typed** (the owner, Q46: a person may have to give a phone number). So whatever reads a stored message for the model, a trace or an export cleans a team reply first (`agent/context.py`, `services/answer_reports.py`): INV-10 holds at the reader. An admin's reply starts no agent turn. **An admin reads a chat only through an escalation or a reported answer.** The audit log names the fields that changed, never their values.
- **A client's home is one definition** (`services/clients.py`, `home`): the place saved in the profile, else the home town's centre, else the home district's. The search page, the agent's tools and a request all start from it when nothing is shared. **The saved place is sent back only by its own endpoint, to its owner;** the model is told a town's or a district's name, never the place (INV-24). **The date of birth is read by no rule** and is removed from what its owner types before the model sees it (INV-10). **A client's name is written by one function** (`clients.set_name`): its parts on the profile, and the same name in one line on the user.
- **Search by name is the search page's own function** (`catalog.find_by_name`, `POST /listings/search-by-name`); the agent's `search_catalog` keeps `search_products`, whose answers the evaluation is measured on. A misspelled name is shown as the closest one **and said to be**; each medicine stands under its own name, strength and form. **It looks only among the medicines in stock** (BLD-D42): a medicine nobody stocks is in no list of the search page; [Notify me] is on a medicine's own empty page and with the assistant. **The search page asks no days of use and no pickup day:** the reserve sheet does, where the fit is checked.
- **A client's last searches are their own** (`services/search_history.py`): returned only by `/me/searches` to their owner, read by no agent tool, no pharmacy and no admin endpoint, never in a trace or an export; **only a medicine's name is kept** (a plain shape, and the catalog must know a medicine by it: never a phone number, a sentence or a controlled medicine's name); 20 at most, 30 days at most (`04` N-53, `10` RR-22).
- **A client gives a place or an area, never a guess:** a client who gave only a place on the map has no district, and code never derives one from the point (`clients.home`; the model is then told that a saved place is used, and no name). The lists of towns show Latin-letter names only.
- **A pickup reminder's moments are one function** (`domain/reminders.py`, N-8): counted from the reservation, the next one stored on the order. The clock check reminds only a reservation still RESERVED; never send one at the moment of reserving.
- **An earlier chat is read, never written in** (the API refuses it, and its cards can't be tapped): the agent's memory is the chat the client writes in now.
- **Whoever is logged in changes in one place** (`api/SessionProvider.tsx`, `becomes`): a log out, a session that ended, a new login. The session's own entry is set first, then every list the page keeps is dropped: they carry no name, so the next person would see the last one's. Emptying everything first leaves the previous person on the screen. **`[hidden]` always hides** (`global.css`): never rely on the attribute without that rule.
- **On a computer the client's portal is a desktop layout** (`components/layout.tsx`: `Shell`, `Screen`): a page is a `Screen`, never a bare `main`, so it gets the top bar on a computer and the menu on a phone. Nothing heavy goes into the top bar: the start-up script has a budget (`11` §10). **The assistant is a page of its own, never beside another page** (the owner, 2026-11-18, BLD-D42): "Ask DawaLink" is a link to it. Don't bring the side panel back.
- **A client's location is never in an address** (a URL): it travels in a request's body, and the website keeps it in memory only (slice 7b, `06` §12). A pin put with "Pick on the map" is the same thing, and so is the place given at sign-up. A pharmacy's own pin is public, like its address.
- **The agent asks before it searches, and waits for the answer** (the owner, 2026-11-15, BLD-D28, replacing BLD-D27's "next to the options"): car or on foot, the day, the days of use, and the location when none is known at all. One message with everything missing; no search and no card until the client has answered. **An answer that leaves something out is asked about again** (the owner, BLD-D29): the agent searches when it knows everything, never on a guess; "any day" or "I don't know" is an answer. **A profile's home district is a known location:** no question, the client says if they want another area.
- **A box is offered only if it lasts the client's days of use** from the chosen pickup day (04 R-F1, INV-25); unknown days → 1 day + an expiry warning. **One set of pickup days everywhere** (search, the reserve sheet, the agent's tools): a date among today and the pharmacy's next open days, 3 at most. A later day leaves fewer days before expiry, and the agent never works out a date itself (04 R-F3, R-F6, N-49).
- **Urgent needs:** requests and watches search for 6 hours and can only be started during request hours. Reservations are **instant** (no pharmacy confirmation); the pharmacy marks [Picked up] or [Not available]; the pickup time is set per pharmacy. A prescription is a **notice** only (04 §1, SM-5, R-P1).
- **A sourcing request starts only in the chat** (the owner, 2026-11-15, BLD-D30): the client's tap on the agent's [Start sourcing] card. There is no request form and no `POST /requests`; the search page has no cart, and reserves one medicine at a time.
- **Our tables are the source of truth** ([ADR-001](docs/adr/ADR-001-conversation-state-and-agent-turns.md)):
  - LangGraph is stateless per turn;
  - one agent turn runs at a time per conversation (a lease on the conversation row);
  - informational events post template cards with no LLM call; decision events run an agent turn.
- **A closed request opens again only by R-RQ12:** a reserved box lost at the pharmacy (not available, or a system cancel) before the request's `ends_at`. Never by the client, the agent or an admin.
- **Within one agent turn, nothing already sent to the model is changed:** the same tools on every call, and notes are only added at the end. Claude rejects its own earlier reasoning otherwise (BLD-D18).
- **What protects a login is counted in real time** (`tx.real_now`), never on the demo clock: sessions, lockouts, confirmation links, sign-up limits (BLD-D31). **One module knows how a login works** (`services/auth.py`); nothing else hashes a password or reads a token.
- **Time is injected:** `today` and `now` always come from the app's clock (the simulated and demo clocks). Never `CURRENT_DATE`/`now()` for business logic in SQL, or `date.today()` in domain code. `created_at` may be real time (it only orders "who came first") ([04](docs/04_domain_rules.md) R-T11, [05](docs/05_database.md) DB-D6).
- **No jobs table:** one **clock check** loop acts on deadlines stored on the rows (04 R-T10).
- **Derived values are never stored.** The expiry zone and the discount price are computed live.
- **Money** is stored as LBP integers and shown as LBP + ≈USD. **Quantities** are counted in units.
- **Numbers** (windows, limits, timers) live only in [04 §5](docs/04_domain_rules.md). Reference them by ID; don't repeat them. In code they live only in `backend/src/dawalink/domain/numbers.py`.
- **Safety:**
  - no medical advice;
  - **same name, same medicine** (the owner, 2026-11-15, Q38): a box that carries the name the client wrote, with the same ingredient, strength and form, is what they asked for, whoever makes it and whatever its box size; another brand is a box with another name;
  - **another brand is only ever shown** (same composition only, and only with the client's consent): with "ask the pharmacist first" and the pharmacy's phone. It is never reserved, planned or waited for automatically; the client asks for it themselves, and nobody checks the call: the pharmacist decides at the counter. Search shows only what was searched (04 R-C10, R-S4, INV-26);
  - controlled substances are excluded entirely;
  - a prescription notice by default (the pharmacist checks at the counter);
  - the chat and the request thread always show the AI notice (`11` §6).
- **Observability:** every agent turn and tool call is recorded, in Langfuse plus our own `agent_runs` / `agent_tool_calls` tables.
- **Security:** follow the [threat model](docs/10_threat_model.md). A change that adds an attack surface (an endpoint, tool, input, third party or role) updates it. Order and request numbers are random (`R-7K3Q2F`). Registration never reveals whether an email has an account. Admins log in with TOTP. The login token travels in the `Authorization` header. **A login or a sign-up never tells a known email from an unknown one:** not by its answer, its lock or its limit (`10` TH-3). **Failed logins are also counted per network address** (N-52), never the ones that work. **The clean-up's database login may delete an unconfirmed pharmacy registration and reads only the columns that find one** (`db/roles.py`): never widen it to a whole table of `users` or `pharmacies`. **Every number the API takes has an upper bound, and a zero byte is refused at the edge** (`api/schemas/common.py`, `api/middleware.py`). **An error of the database or of a schema is logged by its kind and place, never with its message** (`observability/logging.py`): the message repeats the values. **The saved evaluation results are public:** `python -m dawalink.evals.scan_results` must find nothing personal in them (it is one of the free checks before a commit).

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
  - a scripted model in tests (no test can reach a paid service);
  - Claude Haiku 5.5 for development (decision log BLD-D11). Ollama `qwen2.5:7b` is a free spare for when there is no network: it is too small to judge the agent;
  - a Claude model through Anthropic's API, chosen by measurement, for evaluation and the demo, paid by API credits from Mohammed's Max plan ($100 per billing cycle, no rollover).
- **Commands** (the full list is in the root [README.md](README.md)):
  - everything: `docker compose up --build` (website http://localhost:5173, API http://localhost:8000);
  - backend, inside `backend/`: `uv run --env-file ../.env pytest` · `uv run ruff check .` · `uv run ruff format .` · `uv run mypy`;
  - the random requests against the API alone: `uv run --env-file ../.env pytest -m fuzz` (they also run with every test run); never pass `-p no:logging`, many tests read the log;
  - the database, inside `backend/`: `uv run --env-file ../.env python -m dawalink.ops.prepare_db` (logins, migrations, privileges, reference data, catalog, demo data);
  - the catalog, inside `backend/`: `uv run python -m dawalink.ops.fetch_moph --date <list date>`, then `uv run python -m dawalink.ops.build_catalog`;
  - the places from OpenStreetMap, inside `backend/` (only to refresh them): `uv run python -m dawalink.ops.fetch_osm_places`, then `uv run python -m dawalink.ops.build_areas`;
  - the agent, inside `backend/`: `uv run --env-file ../.env python -m dawalink.ops.chat "baddi panadol"` writes as a demo client (`--new`, `--no-location`, `--tap 1`, `--work`, `--request`, `--steps`, `--at 2026-11-16T10:00`). It uses the model named by `LLM_PROVIDER` and `LLM_MODEL`, so with `anthropic` it spends credit;
  - after a schema change: `uv run --env-file ../.env alembic revision --autogenerate -m "..."` with `DATABASE_URL` set to the migrator address, then add functions and triggers by hand and run the tests;
  - after an API change: `uv run python -m dawalink.ops.export_openapi ../docs/openapi.json`, then `npm run gen:api` inside `frontend/`;
  - an admin, inside `backend/`: `uv run --env-file ../.env python -m dawalink.ops.create_admin --email you@example.org --name "Your Name"` (asks for a password; shows the authenticator key once). The admins log in at `/admin/login`;
  - website, inside `frontend/`: `npm test` · `npm run lint` · `npm run typecheck` · `npm run build`.

## 7. Environment notes

- **Machine:** Windows 11. PowerShell is the main shell; Git Bash is also available.
- **Local LLM:** Ollama on an RTX 3070 Laptop (8 GB VRAM, 16 GB RAM). A spare only; its context is set to 12,288 tokens, which still fits the card.
- **The owner's local admin:** made on 2026-11-16 with the command; its login (email, password, authenticator key) is in `.env.admin` at the repo root, which git ignores (`.env.*`). Never print it or copy it into a tracked file. The admin of the real deployment is made on AWS with the same command.
- **Trying the website:** the local stack is `docker compose up --build -d` (the API and the worker), and the website's own dev server through `.claude/launch.json` (`npm --prefix frontend run dev`, port 5173; stop the `web` container first, it holds the same port). The dev server talks to the API at `http://localhost:8000` by default (`frontend/src/api/address.ts`; `VITE_API_URL` overrides it). The demo accounts (`client01@demo.dawalink.test`…) log in with `DEMO_ACCOUNTS_PASSWORD` of `.env`; confirmation emails are at http://localhost:8025. The API needs `APP_SECRET_KEY`.
- **The website through nginx** (its real content policy): stop the dev server, then `docker compose up -d --force-recreate --no-deps web`. Without `--force-recreate` the container may start with no port when the dev server held 5173 a moment before. Use `127.0.0.1` or the Browser pane to reach it; stop it again before starting the dev server.
- **Paid keys:** `.env` holds `ANTHROPIC_API_KEY`, `ORS_API_KEY` and the two Langfuse keys. Never print them, and never run a paid model without the user's ok. `LLM_PROVIDER` defaults to `none`.
- **Shell heredocs damage backslashes** (`\b` becomes a backspace character). Write any script or regular expression with the Write tool, never inside a heredoc.
- **Local ports:** the project's PostgreSQL container is at `127.0.0.1:5433` (a Windows PostgreSQL service holds 5432). Use `127.0.0.1`, not `localhost`, for the database: `localhost` tries IPv6 first here and waits for seconds.
- **Docker Desktop** may be off after a restart: start it before `docker compose` or the tests.
- **Emails** sent by the local stack are caught by mailpit: http://localhost:8025.
- **Database logins:** `.env` holds four addresses (master, migrator, app, retention). The tests need all four, and prepare their own `dawalink_test` database.
- **The Ministry's files** are in `backend/data/moph/` (ignored by git). Never commit them, and never paste rows from them into tracked files; tests use invented products.
- **OpenStreetMap's raw answer** goes to `backend/data/osm/` (ignored by git) when `fetch_osm_places` runs. It is not needed to run anything: only the generated `backend/data/areas_osm.csv` is committed, with the map's credit. Tests use invented places and the hand-written areas only.
- **Slow downloads:** `npm install` and Docker pulls can take many minutes on this connection; run them in the background.
- **Console encoding:** the console uses cp1252, so printing emoji from Python fails. Set `PYTHONIOENCODING=utf-8` or avoid printing them.
- **Helper scripts:** write multi-line Python helpers to a file and run them. Don't inline them in shell heredocs.
- **Doc conventions:**
  - status icons: ✅ validated · 🟡 draft or living · ⏳ not started;
  - each doc opens with an "In short" section;
  - new step docs are named `NN_topic.md` and added to the README table.
