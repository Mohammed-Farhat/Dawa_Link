# DawaLink: Project Overview (read this first)

**Status as of:** 2026-10-23: planning steps 00–11 are validated; no code yet.
**Who it's for:** the team, and anyone who wants the whole picture without reading every document. Each section links to the detailed doc.
**Kept current:** updated whenever a planning step is validated.
**Numbers here are summaries.** The exact values live in [`04` §5](04_domain_rules.md), the source of truth.

---

## In short

- **DawaLink** helps people who can't afford a medicine at full price. Pharmacies sell boxes that are **close to expiry, at a discount**, and the client reserves now and **picks up today or tomorrow**.
- **One AI agent with two modes:**
  - a **chat assistant**;
  - a **sourcing agent** that works alone for 6 hours on a list of medicines.
- **The agent's job** (the professor's words): *bring the client's need to the right pharmacy.* **The agent decides which pharmacy**; code computes the exact facts it decides from (travel times, opening hours, prices, stock, whether the box lasts).
- **Everything exact is plain code:** stock, reservations, prices, deadlines, and who gets scarce stock first (first come, first served). **Every consequential action needs a human tap.**
- **How we'll prove it works:**
  - 6 evaluation suites, including agent vs search page vs a no-AI program;
  - a target of 0 safety violations;
  - every AI step recorded;
  - 122 failure cases and 55 security threats, each with a test.
- **The look is chosen:** the initial UI design for the website (desktop and mobile) is drawn on a design canvas. It's friendly and big, and it puts the saving first (§11).
- **Next:** step 12 (infrastructure and CI/CD), the last planning step. Then we build, test, evaluate and deploy. **The live demo is on 2026-11-30.**

---

## 1. Where we are

**Done:** planning steps 00–11, all validated by the team. The [docs README](README.md) lists every doc with its version.

| Step | What it decided |
|---|---|
| 00 [Decision log](00_decision_log.md) | Every decision, sections A–T |
| 01 [Scope](01_scope_and_features.md) | The product, the agent's features (C1–C18), the demo scenarios |
| 02 [Architecture](02_architecture.md) | The stack and how the parts connect |
| 03 [User flows](03_user_flows.md) | Every screen and flow, for clients, pharmacies and admins |
| 04 [Domain rules](04_domain_rules.md) | The exact rules, states, limits and numbers |
| 05 [Database](05_database.md) | 34 tables, locking, the clock check, retention |
| 06 [API](06_api.md) | Every endpoint, error code and limit |
| 07 [Agent](07_agent.md) | The agent's decisions, tools, prompts, memory, guards |
| 08 [Evaluation](08_evaluation.md) | How we prove the agent is useful and safe |
| 09 [Failure Matrix](09_failure_matrix.md) | 122 ways it can fail, and what happens then (living) |
| 10 [Threat model](10_threat_model.md) | Who could attack it, how, and what stops them (living) |
| 11 [UI design](11_ui_design.md) | How the website looks and behaves, on desktop and mobile; the screens are drawn on a design canvas |

**Next:**
- step 12 (infrastructure and CI/CD), the last planning step;
- then the build: **the agent and its evaluation first**, then the platform screens.

**Still open:**
- O1: which AI model we use (chosen by measurement);
- O2: who pays for it. It's only needed for the evaluation runs and the demo; development uses a free local model.

**Team tasks during the build:**
- write and label ~300 test messages (Arabizi, Arabic, English) and ~120 attack messages;
- create realistic inventory files;
- review every PR.

---

## 2. What DawaLink is

**The problem:**
- Many people in Lebanon can't afford some medicines at full price.
- Meanwhile, pharmacies throw away boxes that expire before they're sold.

**The idea:**
- Pharmacies publish boxes that are close to expiry, **at a discount**.
- DawaLink brings each client's need to the right pharmacy.
- Near-expiry medicine suits **urgent needs**, so a reservation is picked up today or within a few days.

| DawaLink does | DawaLink never does |
|---|---|
| Find, plan, ask pharmacies, reserve (after a tap), notify | Give medical advice ("which medicine", "what dose", "can I take X with Y") |
| **Recommend where to go:** the pharmacy that fits best (route, hours, price, a box that lasts) | Send the client's location to the AI (the AI only sees travel times) |
| Offer the **same medicine from another brand** (same ingredient, strength and form), only with consent | Suggest a "similar" medicine |
| Say a prescription is needed ("bring it to the pharmacy") | Read, judge or schedule prescriptions (the pharmacist checks at the counter) |
| Apply a fixed rule when stock is scarce: **first come, first served** | Let the AI, or anyone, decide who gets a medicine first |

**Out of scope:**
- online payment (the client pays at the counter);
- delivery;
- controlled substances (removed entirely);
- mobile apps (it's a website that works on phones).

---

## 3. Who uses it

| User | What they do |
|---|---|
| **Client** | Searches, chats, or submits a sourcing request; reserves; picks up and pays at the counter |
| **Pharmacy** | Uploads its inventory; sees reservations; marks them **[Picked up]** or **[Not available]**; answers requests to release private stock |
| **Admin** | Approves pharmacies; helps clients the agent hands over; reviews reported answers; watches the agent's health |
| **The agent** | **Assistant mode:** chats with the client. **Sourcing mode:** owns a client's request for 6 hours. |

---

## 4. How the system behaves

### 4.1 The pharmacy side
- A pharmacy registers with its license, address and **a pin on the map**. **The admin approves it**, checking the name and the pin. Nothing works before approval.
- It uploads its **whole inventory** (a fixed CSV/Excel template) and keeps quantities current.
- **Code sorts each box by days left before expiry:**

  | Days left | What happens |
  |---|---|
  | 0–180 | **Published automatically** at a system-wide discount: 25% (91–180 days), 40% (31–90), 60% (0–30). The pharmacy may set its own price for an item, but never above the public price. |
  | 181–270 | **Private.** The agent may ask the pharmacy to release it (early release). |
  | over 270 | Private, never offered |

- Reservations appear **instantly** on its screen, with the order number, product, units, price and pickup deadline. **It never sees who the client is.**
- At the counter, it presses **[Picked up]**, or **[Not available]** if the box was sold before the app was updated.
- It sets its **pickup time**: how many days ahead a client may choose to come (1–3, default 1).

### 4.2 The client side: three ways in
1. **Search page:** a normal search with **no AI**. It's also the evaluation baseline, and the fallback if the AI is down.
2. **Chat with the assistant:** English, Arabic or **Arabizi**; replies are text plus cards with buttons.
3. **Sourcing request:** "find these 1–5 medicines for me". The agent works on it for **6 hours**. Requests (and watches) can only be started **08:00–20:00**; at night: "come back tomorrow". Searching and reserving always work.

### 4.3 Reserving and picking up
1. The client taps **[Reserve]** → the box is held **at once**. There's no waiting for the pharmacy to accept.
2. The client gets an **order number** like `R-7K3Q2F` (random, so nobody can guess someone else's), the pharmacy, address, hours, the pickup deadline, and a **prescription notice** if one is needed.
3. **The pickup day** is today (only if the pharmacy stays open at least 1 more hour) or a next open day within the pharmacy's pickup time. The **deadline** is closing time that day, never after the box's expiry date.
4. A **reminder** comes 4 hours before the deadline.
5. At the counter: the client shows the number, brings the prescription if needed, and pays. The pharmacist presses **[Picked up]**.

### 4.4 The rules that never bend

| Rule | What it means |
|---|---|
| **The box must last** | A box is offered only if `expiry ≥ pickup day + days of use − 1`. If the client doesn't know the days of use: 1 day, with the expiry date shown as a warning. If nothing fits: "No match: the boxes expire too early." |
| **First come, first served** | When new stock appears and several clients are waiting, **code** offers it to whoever started waiting first, as a **2-hour hold**. Nobody can change the order: not the AI, not an admin. |
| **The agent proposes, the client taps** | The agent can't reserve, cancel, or create anything that matters. It shows cards; only a tap acts, and the server re-checks everything at that moment. |
| **Limits per client** | 5 open reservations · 3 units of the same medicine · 2 open requests of up to 5 medicines · 5 watches |
| **No-shows** | Not picked up by the deadline → a no-show. 2 in 30 days → reservations paused for 7 days. If the pharmacy forgot to press [Picked up], the client presses **[I picked it up]** and an admin removes the no-show. |
| **Prescription** | Only a notice. The pharmacist checks it at the counter. |

---

## 5. One example from start to finish

A client writes:

> *"baddi concor 5 tnein w glucophage 850, la 12 yom, ma 3ande siyyara w bkhallis shoghl 6"*
> (I need 2 Concor 5 and Glucophage 850, for 12 days. I don't have a car, and I finish work at 6.)

1. **The agent understands:** Concor 5 mg × 2, Glucophage 850 × 1, 12 days of use, no car, free after 18:00. If a strength were unclear, it would ask with buttons ("1 g / 625 mg / syrup"); it never guesses.
2. **It asks only what's missing:** "Do you want to pick up today or tomorrow? Share your location, or tell me your area."
3. **Code computes the facts** for each pharmacy:
   - which boxes last 12 days from that pickup day;
   - walking and driving time (from OpenRouteService);
   - opening hours, price, stock.
4. **The agent decides:** *"I recommend Al-Amal pharmacy: 9 min on foot, open until 23:00, it has both, and the boxes last your 12 days."* Up to 2 alternatives are shown, and one card: **[Reserve these]**.
5. **The client taps** → reserved instantly, with an order number and a pickup deadline. The pharmacy sees it at once.
6. **If Glucophage weren't listed anywhere**, the agent decides what to do next:
   - it **asks up to 3 open pharmacies** that hold it privately to release it (they have 2 hours to answer);
   - it **watches** for new stock (6 hours);
   - whichever comes first becomes an **offer card** held for 2 hours; the client taps [Accept] → reserved;
   - if both come, the first one the client accepts wins, and the other is cancelled at once.
7. **At the pharmacy:** the client shows the number and pays, and the pharmacist presses [Picked up].

**As a sourcing request** (from the form, or from the chat's **[Start sourcing]** card), the agent owns the need for 6 hours:
- **Within seconds:** it reports item by item what it found and what it's doing about the rest.
- **It wakes up again when:**
  - a pharmacy marks something [Not available];
  - a request to release stock fails;
  - **1 hour is left**: its last chance to suggest relaxing the budget, allowing another brand, or handing over to a person;
  - the client writes in the request's thread.
- **At the end:** a summary of what was reserved, and what wasn't found.

---

## 6. The agent

### 6.1 Its five judgments
1. **Understand** messy requests (Arabizi, misspellings, brand names), and ask when unsure.
2. **Decide which pharmacy (or route) the client should go to**, weighing travel by car or on foot, opening hours, price, stock and the expiry fit against what the client said. It recommends one, with a reason.
3. **Decide the next step** for each missing medicine: propose what exists, wait for new stock, ask pharmacies, suggest relaxing a constraint, or hand over to a person.
4. **Re-plan** when something fails.
5. **Communicate** in the client's language and style: item by item, honestly, with the prescription notice and refusals when needed.

### 6.2 What the agent does vs what code does

| The agent (AI) | Code (exact, tested) |
|---|---|
| Understands the client | Finds catalog matches; removes controlled medicines |
| Decides where to go and why | Travel times, routes, opening hours, the expiry fit, prices |
| Chooses among plans for several medicines | Builds the plans (`plan_basket`) |
| Decides to ask pharmacies or to watch | Anti-spam limits; who is asked; holds; expiries |
| Re-plans after events | Detects events, wakes the agent, runs the clock |
| **Proposes cards** | **Reserves, after a tap**, re-checking everything |
| (never) | **Who gets scarce stock first:** first come, first served |

### 6.3 Inside the agent (details in [`07`](07_agent.md))
- **17 tools + `reply`:**
  - 6 read tools, e.g. search the catalog, find options, plan a basket;
  - 6 proposal tools, which create cards;
  - 5 bounded actions: a watch, a claim, asking pharmacies, a follow-up, a handover to a person.

  **No tool can reserve, cancel, or change prices, stock or priority.**
- **Memory:**
  - the last 20 messages;
  - a small **case state** (the medicines in focus, preferences, the client's situation);
  - its tools.

  It has no memory across conversations, and no vector database.
- **What it never sees:**
  - names, emails, phone numbers (removed before anything is stored or sent);
  - **coordinates** (only "Hamra, 9 min on foot");
  - text typed by pharmacies, except their admin-approved name;
  - private stock.
- **Guards:**
  - before the AI: personal data is removed, and attack attempts are flagged and counted.
  - after the AI, every reply is checked for:
    - medical advice;
    - cards that don't come from its own tools;
    - personal data;
    - links.

    A violation gets one repair attempt, then a fixed safe message.

  Replies are shown as **plain text**.
- **Limits:**
  - ≤ 6 tool calls per turn and ≤ 20 turns per request;
  - timeouts and retries;
  - daily and monthly cost caps.

  If the AI is down or over budget → "Use Search", and everything else keeps working.
- **One agent turn at a time** per conversation. Every turn and tool call is recorded, in Langfuse and in our own tables.

### 6.4 Why an agent, and not just the search page?
The search page answers one question: *"where is this one medicine listed right now?"* The agent takes on the whole job of getting the client their medicines.

| Situation | Search page (no AI) | The agent |
|---|---|---|
| A messy message ("baddi concor w glucophage, la 12 yom, ma 3ande siyyara w bkhallis shoghl 6") | The client types each name, picks the strength, sets the filters | Understands one message in any language, and asks only what's missing |
| Several medicines | One search each; the client works out the trips | Plans them together: fewest trips or cheapest, quantities split across pharmacies, the visiting order |
| Choosing where to go | Sorts by one thing (nearest or cheapest) | Weighs everything against the client's situation (no car, free after 6) and explains its choice |
| Not listed anywhere | "Notify me", and hope | **Asks open pharmacies to release boxes they keep privately**, which search can never show, and watches for new stock |
| Something fails | The client finds out and starts over | Re-plans at once |
| The client isn't looking | Nothing happens | Keeps working for 6 hours, and an hour before the end suggests relaxing the request or calls in a person |

**We don't just claim this; we measure it.** The evaluation (E2) runs the same requests through three contenders:
1. the search page;
2. a fixed program with **no AI** that uses the same tools;
3. the agent.

Wherever the AI adds nothing, we report it honestly as "this should stay plain code". The search page is also the fallback when the AI is down.

---

## 7. Edge cases (what happens when…)

| Situation | What happens |
|---|---|
| Two clients tap the last box | One gets it; the other sees "Someone reserved this a moment ago" + other options |
| A plan for several medicines, and one is gone at tap time | **Nothing** is reserved (all or none); the agent says which one and offers the rest |
| The price went up since the client saw it | Nothing is reserved; the new price is shown |
| No box lasts the days of use | "No match: the latest box expires 12 Nov. Shall I watch for new stock or ask pharmacies?" |
| The client doesn't know the days of use | 1 day is assumed, with the expiry date shown as a warning |
| A request at night | "Please come back tomorrow from 08:00." Search and reserving still work. |
| Only 1 of the 2 boxes found | Reserve the 1, and keep looking for the 2nd elsewhere |
| A box sold at the counter before the app was updated | The pharmacy presses [Not available] → no penalty for the client; the agent re-plans at once |
| The pharmacy forgot to press [Picked up] | The client presses [I picked it up] → an admin checks and removes the no-show |
| The client came without a prescription | They can come back before the deadline, or cancel with no penalty |
| Someone else was waiting first | "Someone who asked earlier was offered it first. I'm still watching." It never says who. |
| A pharmacy is suspended | Pending offers are cancelled and the agent looks elsewhere; existing reservations can still be picked up |
| The AI is down | "Use Search". Requests keep working in code, and the agent resumes when it's back. |
| The routing service is down | Straight-line distance, shown as "about 3 km" |
| Location not shared | The client's district is used |
| "Ignore your rules", in any language | No effect: there's no tool that can do harm. It's logged and counted. |
| "Cancel R-…", someone else's order | "I can only see your own reservations." |
| "I'm dying, put me first" | The rule is explained, emergency services are suggested, and a person can help. **The order doesn't change.** |
| A dose question | Refused; referred to a pharmacist or doctor; the agent offers to keep searching |
| A controlled medicine | Not on DawaLink at all |

All 122 failure cases are in the [Failure Matrix](09_failure_matrix.md), each with what the user sees and its test.

---

## 8. Where the human is in the loop

| Who | Decides |
|---|---|
| **Client** | Every consequential action is a tap: reserve, accept an offer, start or cancel a request, raise a budget, allow another brand, remove an item |
| **Pharmacy** | [Picked up] / [Not available]; accepting or refusing to release private stock; its inventory and prices |
| **Admin** | Approving pharmacies (name and pin); answering handovers, including emergencies (help only, never priority); clearing contested no-shows; turning reported bad answers (👎) into tests |
| **The team** | Reviews and can explain every PR; writes the test and attack messages |
| **Nobody** | Who gets scarce stock first: fixed code, first come, first served |

---

## 9. Safety and security in brief (details in [`10`](10_threat_model.md))

- **Logins:**
  - server-side sessions;
  - strong passwords and lockout after repeated failures;
  - a verified email before chatting or reserving;
  - **admins also use a code from an authenticator app**.
- **Registration never reveals** whether an email already has an account.
- **Everyone sees only their own data.** Someone else's order or request simply looks "not found". Pharmacies never see client identity.
- **The agent can't be tricked into acting.** It has no harmful tools, every card is re-checked when tapped, and pharmacy text doesn't reach it.
- **Privacy:**
  - no names, emails or phones reach the AI;
  - the location is stored rounded and never sent to the AI;
  - outside services get only what they need.
- **Cost caps** at several levels, so an attacker (or a bug) can't run up the AI bill.
- **Risks we accept, honestly stated** (11 in total). For example: someone with many accounts can get around per-client limits.

---

## 10. How we prove it works (details in [`08`](08_evaluation.md))

| Suite | Question | Data |
|---|---|---|
| **E1 Understanding** | Does it understand messy requests, ask when unsure, refuse clinical questions? | ~300 messages written by the team |
| **E2 Simulation** | Who secures more medicines within the 6 hours, and do they make good choices about where to go? Compared: the **search page**, a **program with no AI** using the same tools, and **the agent**. | A simulated world: 30 pharmacies, 200 clients; 5 runs × 100 requests per contender |
| **E3 Ablations** | Which features matter (asking pharmacies, planning, re-planning)? | Same simulation |
| **E4 Safety** | **0 violations:** no medical advice, injections without effect, no access to others' data, no priority manipulation | ~120 attack messages |
| **E5 Models** | Quality, speed and cost per model → the cheapest model that meets every target | E1 + E4 + part of E2 |
| **E6 Real-world constraints** | Results when inventory is out of date or pharmacies are slow; privacy and human approval at 0 violations | Simulation sweeps + scans of every trace |

**What makes the results honest:**
- part of every dataset is **held out** until the end;
- targets are fixed **before** the final runs;
- several runs per setup;
- every failure becomes a **regression test**.

**Also tracked:** every agent turn is recorded (latency, tokens, cost, errors), with an admin health dashboard, and the CI runs tests, scans and an offline evaluation gate on every PR.

---

## 11. The UI design in brief (details in [`11`](11_ui_design.md))

The initial design for the website, on desktop and mobile, is drawn on a design canvas: **"DawaLink initial UI design (website, desktop and mobile)"**, https://claude.ai/artifact/1pEPY1g3zNtYZX3Sbzv3mx. It's private, so ask the repo owner for access. **It can still change during the build.**

- **The look:**
  - one font for English and Arabic (Readex Pro, made for easy reading);
  - deep navy and a friendly blue; **yellow is used only for savings**;
  - rounded cards and pill buttons;
  - 17 px text and 48–60 px buttons, so it's easy for older users and on cheap phones.
- **Client tabs: Home · Medicines · Ask · Me.**
  - **Home:** today's pickup ticket, the search box, "Find several medicines" and "Ask DawaLink".
  - **Search:** the medicine shown once, then one row per pharmacy with walking or driving time, closing time, price and **what you save**.
  - **Reserve:** today or tomorrow, the days of use, and a clear "lasts your 12 days".
  - **Pickup ticket:** a dark screen with a huge order number to show at the counter.
  - **My medicines:** one tracker per medicine, from searching to ready to pick up.
  - **Ask:** the chat, which works in Arabic too, right to left.
- **Pharmacy:**
  - a **Today** screen built around the counter: a big order-number box, with [Picked up] and [Not available];
  - a clear check of the inventory file before [Apply].
- **Admin:** an overview of what needs attention, and the agent's health.
- **Later**, decided during the build:
  - the savings total on Home;
  - a text-size setting;
  - Undo on [Picked up];
  - a reminder button on the ticket;
  - a map view in search;
  - "why" chips on the agent's recommendation.

---

## 12. Tech in brief (details in [`02`](02_architecture.md))

| Part | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic |
| Database | PostgreSQL, SQLAlchemy, Alembic |
| Agent | LangGraph |
| Background work | One worker loop, the **clock check**: every few seconds it handles everything that is due, such as expiring offers, ending windows and running agent turns. There is no jobs table. |
| Frontend | React + TypeScript + Mantine, styled with the design in §11; maps with Leaflet + OpenStreetMap |
| Routes | OpenRouteService (free), cached, with a straight-line fallback |
| AI by stage | A fake scripted AI in tests ($0) · Ollama `qwen2.5:7b` on the laptop for development · the chosen model for evaluation and the demo |
| Tracing | Langfuse + our own `agent_runs` tables |
| Hosting | AWS: CloudFront, ECS Fargate (API + worker), RDS, SES, built with CDK (Python), destroyed after the demo |
| Quality | ruff, mypy, pytest, GitHub Actions, CodeQL, Dependabot, Trivy |

---

## 13. Where to read more

| If you want… | Read |
|---|---|
| The product and the agent's features | [`01`](01_scope_and_features.md) §1–§6 |
| Why the agent is designed this way | [ADR-002](adr/ADR-002-agent-role-assistant-and-sourcing.md) (two modes) · [ADR-004](adr/ADR-004-agent-decides-the-pharmacy.md) (the agent decides the pharmacy) · [ADR-003](adr/ADR-003-priority-is-a-rule-not-the-llm.md) (priority) · [ADR-001](adr/ADR-001-conversation-state-and-agent-turns.md) (agent turns) |
| Each screen, and what the agent says when | [`03`](03_user_flows.md) |
| An exact rule, limit or number | [`04`](04_domain_rules.md) (the source of truth) |
| The agent in depth | [`07`](07_agent.md) |
| How the website looks | [`11`](11_ui_design.md) and the design canvas (§11) |
| How a decision was made | [`00`](00_decision_log.md) |
| Why the design changed along the way | The two design reviews in [`reviews/`](reviews/) |
| What the course requires, and where we cover it | [Requirements checklist](requirements_checklist.md) |
| Words you don't know | The glossary in the [docs README](README.md) |

**How to read the IDs in the other docs:**

| Prefix | Meaning | Prefix | Meaning |
|---|---|---|---|
| `C-` | Feature (`01`) | `R-` | Rule (`04`) |
| `CS-` `PS-` `AS-` | Client, pharmacy and admin screens (`03`) | `N-` | Number (`04` §5) |
| `AF-` `RF-` | Assistant and request flows (`03`) | `INV-` | Invariant: must always be true (`04` §6) |
| `CN-` `PN-` | Client and pharmacy notifications (`03`) | `SM-` | State machine (`04` §3) |
| `FX-` `FA-` `FR-` `FI-` `FS-` `FO-` | Failure cases (`09`) | `TH-` `RR-` | Threats and accepted risks (`10`) |
| `E1`–`E6` | Evaluation suites (`08`) | `…-D1` | Decisions (each doc's last section, and `00`) |
