# ADR-001: Conversation state and how agent turns run

**Status:** Accepted (2026-10-13, design review #1 DR-1) · **Amended** (2026-10-13, design review #2): a turn **lease** instead of an advisory lock; decision events run through the **clock check** (no jobs table). See "Amendment" at the end.
**Date:** 2026-10-13
**Deciders:** DawaLink team (Mohammed Farhat, Mohamad Natafgi, Anthony John Kanaan)

## Context

The assistant (C6) runs a **turn** in two situations:
- the **client sends a message** (API; the reply streams over SSE);
- a **system event** happens (worker): a pharmacy confirms or declines, an order times out, a watch hits, an early-release request ends.

The current design (`02` §3) uses LangGraph **with its Postgres checkpointer** as conversation memory. We also need our own `chat_messages` table, because:
- the UI shows the conversation;
- retention is 30 days (R-AS4);
- "delete my account" erases chats (SM-2);
- admins read escalated or reported conversations (A-D4).

Two problems follow:
1. **The conversation exists twice.** Retention and deletion must purge both copies; missing one is a privacy bug. The two copies can also disagree.
2. **Two writers.** An API turn and a worker turn can run on the same conversation at the same moment, which risks interleaved replies and lost state.

The forces at play:
- privacy (deletion, retention);
- correctness under concurrency;
- LLM cost per event;
- simplicity for a three-person team that must explain the code.

## Decision

1. **Our database is the single source of truth for conversations.** Tables `conversations` and `chat_messages` (PII-redacted), plus a small **case state** per conversation: products in focus, constraints, options shown, pending proposals.
2. **LangGraph runs stateless per turn**, with **no checkpointer**. Each turn:
   - loads the last *N* messages and the case state;
   - runs the graph (guard_input → assistant ⇄ tools → guard_output);
   - saves the new messages and the updated case state **in one transaction**.
3. **Agent turns are serialized per conversation** *(amended)*: a turn takes a **lease** on the conversation row (`turn_lease_until`):
   - an API turn takes the lease; a chat message that finds it taken shows "one moment…" and retries;
   - a decision event is written as a system message, and the conversation is marked `pending_turn_at`. The worker's clock check runs the turn when the lease is free.
4. **Events are split by whether they need a decision:**

| Event | Handling | LLM call? |
|---|---|---|
| Reserved, picked up, expired, cancelled; watch hit; early-release offer | **Template status or offer card** appended to the chat (plus the notification) | **No** |
| A reservation marked not available by the pharmacy; early-release request unfulfilled; request window check | **Agent turn** to re-plan and propose next options | Yes |

## Options considered

### Option A: LangGraph checkpointer as memory (current design)

| Dimension | Assessment |
|---|---|
| Complexity | Medium. Two conversation stores, plus checkpoint schema migrations owned by a library. |
| Cost | Every event resumes the graph, which means an LLM call per event. |
| Privacy | Deletion and retention must also purge the checkpoint tables. |
| Team familiarity | Low. Checkpoint internals are hard to inspect and explain. |

**Pros:** built-in persistence, including mid-turn recovery; less code for loading history.
**Cons:** duplicated data; concurrency still needs a lock; harder to test and explain; more LLM calls.

### Option B: our tables as the source of truth, LangGraph stateless (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low. One store; the graph is a pure function of (history, case state, input). |
| Cost | LLM only for events that need a decision. |
| Privacy | One place to delete and purge. |
| Team familiarity | High. Plain SQL tables the team can read. |

**Pros:** single source of truth; trivially testable with the fake LLM; cheaper; memory scope, lifetime and retrieval are explicit (requirement T-3).
**Cons:** we write the small load and save step ourselves. A crash mid-turn loses that turn: the client sees "[Retry]", and an event turn is retried by the job system. Tools that write (watch, early release, escalation) need idempotency keys.

### Option C: no LangGraph (plain SDK tool loop)

| Dimension | Assessment |
|---|---|
| Complexity | Low. |
| Team familiarity | Medium. |

**Pros:** the fewest dependencies.
**Cons:** we lose the explicit graph (guard nodes, fallback edge), which helps explain and trace the design. The team already chose LangGraph (T3).

## Trade-off analysis

Option B keeps what LangGraph is good at in our case (an explicit, traceable graph with guard steps) and drops what it's not needed for. Persistence across hours of waiting is already handled by our state machines and job table, and our turns are short (≤ 6 tool calls). We accept writing about 50 lines of load and save code, plus idempotency keys on three tools. In return we get one place for privacy operations, deterministic tests, fewer LLM calls, and no concurrency surprises.

## Consequences

- **Easier:** deleting and purging conversations; testing turns; explaining memory in the report; controlling LLM cost.
- **Harder:** a mid-turn crash can't resume from the middle (it retries the whole turn instead).
- **Changes needed:**
  - `02` §1 (Agent row) and §3.3 (memory): "no checkpointer; our tables".
  - `04` §3 (events that call the LLM).
  - `05`: add the `conversations` (with case state) and `chat_messages` tables; remove the LangGraph checkpoint tables.
  - `07`: specify the turn loader and saver, the lock, and tool idempotency.
- **Revisit when:** turns become long-running (many tool calls or long waits inside one turn). Then checkpointing becomes worth its cost.

## Action items
1. [x] Team approves this ADR (design review DR-1).
2. [x] Update `02` and `04` as listed above.
3. [ ] Design the tables in `05`.
4. [ ] Specify the loader, saver, lock and idempotency in `07`; add tests for concurrent turns.

## Amendment (2026-10-13, design review #2)

The decision stands: **our tables are the source of truth, and LangGraph is stateless per turn.** Two mechanisms changed:

| Was | Now | Why |
|---|---|---|
| A Postgres **session advisory lock** held for the whole turn | A **lease** on the conversation row (`turn_lease_until`, renewed during a long turn) | No database connection is held while the LLM thinks; a crashed turn's lease simply expires; easier to test |
| Events re-queued through a **jobs table** with retries | Events stored as **system messages** + `pending_turn_at` on the conversation; the worker's **clock check** runs pending turns and retries failures (1 m, 5 m, 15 m, then escalate) | There's no jobs table any more (`04` R-T10). Events also become visible in the conversation history the next turn reads. |

Also new: **cards come only from tools** (proposals stored server-side; `04` R-AG7), and **text typed by pharmacies never reaches the LLM** (`04` R-AG8).
