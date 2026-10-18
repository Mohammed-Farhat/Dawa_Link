# ADR-003: Who gets scarce stock first is a fixed rule, never the LLM

**Status:** Accepted (2026-10-13, R-D21) · **Amended** (2026-10-13, design review #2): the rule is now **first come, first served**, and **nobody can override it**.
**Date:** 2026-10-13
**Deciders:** DawaLink team

## Context

When new stock appears and several clients are waiting for it (watches and waiting request items), someone has to get it first. It's tempting to let the agent "decide who needs it most". The team asked whether the agent should decide priority.

**Amendment context (design review #2):** the team then decided that DawaLink serves **urgent needs only**. A request or watch searches for 6 hours and can only be started during the day, and pickup is within 1–3 days. Every need on the platform is "now", so the need-by date that ranked clients no longer exists. The team also decided that **admins can't set priority**.

## Decision

**Priority is computed by code with a fixed, transparent rule** (`04` R-PRI):
- **first come, first served:** the claim that started waiting first (`created_at`, then `id`) gets the offer;
- claims whose client is paused or at a limit are skipped, and the next one gets it.

**Nobody can change the order:** not the agent, not an admin. When a client claims an emergency, the agent:
- explains the rule;
- for a medical emergency, tells the client to contact a doctor or emergency services;
- offers human help (`emergency_claim` escalation). The human can reply and help, but can't change the order.

## Options considered

| Option | Assessment |
|---|---|
| A. The LLM judges who needs it most | ❌ **Unfair and inconsistent** (the same case can get different answers). **Manipulable:** "I'm dying, put me first" works like a prompt injection that decides who gets medicine. **It's clinical triage**, which our proposal promised never to do ("no clinical triage is done by the AI"). Not auditable. |
| **B. First come, first served (chosen in the amendment)** | Simple, deterministic and testable (INV-17), and impossible to manipulate. It ignores differences in urgency, but on DawaLink **every need is urgent by design** (a 6-hour window), so there's little left to rank. Real medical emergencies belong with doctors and emergency services, not with a marketplace. |
| C. Fixed rule (need-by date) + an admin override *(the original choice)* | Deterministic, with a human for exceptions. **Superseded:** there's no need-by date any more, and an admin deciding who gets medicine is still triage, done by someone without clinical information. |

## Consequences
- **Easier:**
  - fairness can be tested in one line (`ORDER BY created_at, id`);
  - a red-team case ("put me first") gives a clear pass/fail;
  - no override columns, screens or audit paths to build;
  - a strong point for the report and demo ("we deliberately kept this out of the AI's hands, and out of anyone's").
- **Harder:** a truly urgent case gets no special treatment from the platform. We say so honestly, and point to emergency services.
- **Tests:**
  - allocation is deterministic;
  - no agent tool and no admin endpoint can change priority;
  - the safety set includes priority-manipulation prompts.
