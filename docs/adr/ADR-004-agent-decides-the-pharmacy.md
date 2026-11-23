# ADR-004: The agent decides which pharmacy; code computes the route facts; location stays out of the LLM

**Status:** Accepted (2026-10-20, the professor's guidance, decision log §S) · **Amended** (2026-10-22, `10` TM-D3): "reliability" removed from the facts. Nothing measures it; the team assumes the stock on the app is real, and [Not available] handles the rare exception. · **Amended** (2026-11-23, decision log BLD-D53, BLD-D54): the agent **asks once**, before its first search, where the client wants the pharmacy (nearest, an area they name, or anywhere), for how many days and when, and then always searches; it **never asks whether the client has a car** (by car is assumed, and the walking time is shown too). **A place named as where to look is not where the client is:** only the pharmacies of the areas named are weighed, all together, and the travel times still count from where the client is.
**Date:** 2026-10-20
**Deciders:** DawaLink team, following the course professor's guidance

## Context

The professor described the agent's purpose as: *"we only help in bringing the client's need to the right pharmacy"*, and asked that **the agent decide which pharmacy** the client goes to, **based on the best route (location) and other properties**. He also asked that the **expiry match the client's period of use**: a client taking a medicine for 12 days must get a box that lasts 12 days; if none does, we say there's no match.

**The design until now:**
- **Location was district-only** (DR2-A9). With no coordinates, real routes weren't possible.
- **Plans were ranked by a fixed rule** (district → number of pharmacies → price), and the agent mostly picked among them by stated preference.
- **A fixed "17 days to expiry" minimum** hid short-dated boxes from everyone.

**The forces at play:**
- the professor's explicit direction;
- the agentic justification (the agent's judgment must matter);
- privacy (a client's location is personal data);
- the LLM's weakness at arithmetic and geography;
- cost and simplicity.

## Decision

1. **Code computes the facts:** for each candidate pharmacy, it computes
   - road travel time by car and on foot (OpenRouteService, cached, with a straight-line fallback);
   - for plans, the best visiting order;
   - opening hours compared with when the client can go;
   - price and stock;
   - **the expiry fit** (`expiry ≥ pickup day + days of use − 1`).
2. **The agent decides.** It weighs those facts together with what the client said ("no car", "I finish at 6", "cheapest", "in Saida or Beirut"). It **recommends one** pharmacy or plan with a one-sentence reason, and shows up to 2 alternatives. The client still taps to reserve. *Since 2026-11-23:* what the client hasn't said of where, how many days and when is asked once, in one message; an open answer is no preference, and the agent searches whatever comes back. It never asks car or on foot.
3. **Location stays out of the LLM.**
   - The client shares a location ("Use my location") or picks a district. It's stored rounded to ~100 m, outside the agent's case state, and purged with its conversation or request.
   - Pharmacies pin themselves on a map, and an admin checks the pin.
   - **The agent sees only "12 min on foot, Hamra".**
   - *Since 2026-11-23:* places the client names as where to look narrow the pharmacies searched; they are looked up by name in our own list, and the agent is given names, never a point (`04` R-S2).
4. **The expiry fit replaces the fixed minimum.**
   - Any unexpired box can be listed.
   - It's offered to a client only if it lasts their days of use (unknown → 1 day, with a clear expiry warning).

## Options considered

| Option | Assessment |
|---|---|
| A. A fixed weighted score in code picks the pharmacy | Deterministic and cheap, but blind to what the client says ("no car", "after 6"). It's exactly the "scripted policy" baseline (B1) we compare against. It would make the agent a workflow, against the professor's direction. |
| **B. Code computes the facts, the agent decides (chosen)** | The agent's judgment is used where it adds value: combining facts with the client's situation, then explaining. Correctness stays in code (no arithmetic or map reading by the LLM). It's measurable: E2 compares the agent's choices with an oracle that knows each client's real situation, and with B1. |
| C. Give the LLM the coordinates or a map and let it work out the routes | ❌ The location would go to an external AI provider (privacy). LLMs are unreliable at distances and routes. It's harder to test and more expensive. |
| D. Keep district-only location | Simple, but it can't give a "best route", which the professor explicitly asked for. |

## Consequences
- **Easier:**
  - a clear, defensible answer to "what does the agent decide?";
  - a new, strong evaluation metric (decision quality vs the client's real situation);
  - fewer boxes wasted (no fixed minimum), and the professor's example works.
- **Harder:**
  - a routing dependency (a free tier with limits; mitigated by the cache and the straight-line fallback);
  - location data to protect (rounded, purged, kept out of the LLM; to be covered in the threat model, `10`);
  - a map pin step at pharmacy registration.
- **Changed:** `01` v5.0, `02` v3.0, `03` v4.0, `04` v4.0 (R-S2, R-S3, R-F, R-RT, R-AG9), `05` v3.0, `06` v1.1, `07` v1.1, `08` v1.1, `09` v1.1.
- **Tests:**
  - the expiry fit at its boundaries;
  - no coordinates in any LLM trace (INV-24);
  - no reservation of a box that doesn't last (INV-25);
  - the routing fallback;
  - the agent's recommendation is one of the tool's valid options.
