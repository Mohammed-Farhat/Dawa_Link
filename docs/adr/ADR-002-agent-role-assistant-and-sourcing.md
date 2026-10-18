# ADR-002: The agent's role: interactive assistant + autonomous sourcing

**Status:** Accepted (2026-10-13, decision log §K AF-3) · **Amended** (2026-10-13, design review #2): requests are **urgent** (a 6-hour window, started 08:00–20:00) instead of having a need-by date; the evaluation adds a **no-AI scripted baseline**.
**Date:** 2026-10-13
**Deciders:** DawaLink team

## Context

DawaLink is graded as an **agentic systems** project. The requirements say a *"generic AI assistant, chatbot… without a clearly defined user problem and measurable value is not sufficient"*, and they ask us to justify *why agentic behavior provides value*.

Our first design had a **chat assistant** that finds options and proposes reservations. That's useful, but it's reactive: it only works while the client is chatting, mostly on one medicine at a time. Meanwhile, the real client problems take time and several steps:
- needing several medicines by a date;
- stock that isn't listed yet;
- pharmacies declining;
- deadlines approaching.

## Decision

**One agent, two modes, sharing the same tools, guardrails and memory model (ADR-001):**

1. **Assistant (interactive):** the chat. The agent understands the client, explains options and proposes reservations.
2. **Sourcing (autonomous):** the client submits a **sourcing request** (1–5 medicines needed now, district, budget). **The agent owns it for its 6-hour window**:
   - it plans (`plan_basket`);
   - it proposes;
   - it opens claims;
   - it asks pharmacies to release unlisted stock;
   - it waits for events and **re-plans** on declines, timeouts and partial confirmations;
   - it warns 1 hour before the window ends;
   - it escalates.

**Autonomy boundary (`04` R-RQ4):**
- **The agent acts alone on:** search, planning, claims, early-release asks, follow-ups, escalation.
- **A client tap is required for:** reserving, accepting offers, starting or cancelling a request, changing its constraints.
- **The agent never** ranks clients (ADR-003), creates orders, or changes prices or stock.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Chat assistant only | Simple | Reactive; weak agentic justification ("a chatbot over search") |
| **B. Assistant + autonomous sourcing (chosen)** | A clear goal; works on its own for the whole window; acts with several parties; plans and re-plans; measurable outcome (fulfilled within the window) | A request lifecycle to build and test |
| C. Two separate agents (client + pharmacy) | Role separation | Pharmacies answer with buttons, so there's no messy input for a second agent. "More agents ≠ better." |
| D. Fully autonomous (the agent reserves without taps) | Fastest | Breaks "human approval for consequential actions". Possible later as opt-in pre-authorization (add-on A9). |

## Consequences
- **Easier:**
  - a strong, measurable agentic justification: the agent vs search + [Notify me] **and vs a scripted policy with no AI** (same tools), on requests fulfilled within the window;
  - ablations (no early release, no planning, no re-planning).
- **Harder:**
  - new entities: requests, items, claims;
  - decision-event handling;
  - evaluation needs a time-based simulation.
- **Changed:** `01` v3.0 (C17, C18), `03` v2.0 (CS-15, CS-16, RF-1–RF-9), `04` v2.0 (SM-8, R-RQ, R-AG).
- **Revisit when:** clients want more autonomy → add-on A9 with explicit consent limits.
