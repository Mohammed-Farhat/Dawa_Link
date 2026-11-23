# Development architecture comparison — owner protocol, 2026-11-19

The user-provided architecture task supersedes the **stage ceilings and scope** of the
historical 2026-11-18 protocol; it does not rewrite historical reservations or results.
Reference: local `8e689a583b69a399598f557ac8a2310571c1dbb1`, containing fetched main `28cf4f1`.
The owner explicitly confirmed that teammate work is complete. Original source archive
and hashes are retained. Architecture A preserves original prompts/tools/guards/repair.

Dataset acceptance: explicit owner-approved, AI-assisted adjudication. Of the 144 queued
adjudications, nine are direct user decisions and 135 are AI decisions; only the nine are
marked human-reviewed. Other reviewed cases retain their draft labels. Twenty-two cases
are excluded, not deleted. Accepted suites have 230/107/15 cases, hash-frozen separately
from the draft and historical datasets. The existing actual-human acceptance path stays
the default in `development_review freeze`; the new path is named explicitly.
Author/reviewer/model overlap and scorer limitations remain sources of bias.

Contenders run independently:
- current: the reference tool workflow, unchanged prompts/guards and correction loop;
- staged: isolated read-only structured extraction; cumulative latest facts and removals;
  code detects missing logistics and routes to clarification, otherwise existing workflow
  resolves catalog products and runs all existing guarded tools;
- verified: current workflow plus an isolated read-only draft/cards/facts/tool-results review;
  one correction shares the original repair allowance, followed by original output checks.

Model `claude-haiku-5-5`, effort medium and 8000 maximum output tokens for every contender
and auxiliary stage. No new sampling settings. Played-client effort remains the original
low setting for every architecture, if that coverage is reached. All paid calls, including
extraction/review/correction/client/retries, pass through EvaluationModel and one ledger:
`../architecture-20261118/budget.sqlite`.

Ceilings in USD: baseline 6 (historical holds included), screening 6, expanded 8,
held-out 3 reserved and untouched, retry reserve 2 unborrowed, aggregate 25.
Retries retain their originating stage. Unknown charges keep the conservative $0.645
reservation; no estimated reconciliation. Reservations must fit both stage and total.

Targets and ranking are frozen in targets.json before comparative scores. Screening.json
pins 60 development IDs: 30 understanding (8/8/7/7 language counts), 20 safety (5 each),
10 conversations (3/3/2/2) covering eight difficult behavior families. A rejected
proportional sample is retained; it omitted mixed-language safety before any scoring.

Execution: pass free tests/gates; five understanding smoke cases per architecture, separate
from comparison, A in baseline and B/C in screening. Review completion, actual cost and
uncertain holds before scaling. Then identical screening cases twice, order A/B/C then
C/B/A. Every safety/semantic flag and architecture disagreement receives manual assistant
inspection, attributed as such. Execution failures and scorer errors are not safety passes.

Advance at most one challenger with no unresolved confirmed safety violations and better
quality, or equal observed quality at lower measured cost. Otherwise keep A and stop.
A final improvement claim requires fresh full-development understanding/safety/conversation
runs for A and that challenger. If affordable, prioritize paired simulation seeds 1–5,
100 requests each, then played clients, then inventory/pharmacy-response stress. Validate
identical initial demand/worlds/external events; action-dependent reactions may differ.
Review all flags plus 50 seeded conversations (or all if fewer); use seed-clustered paired
confidence intervals. Incomplete or uncertain differences are inconclusive.

Held-out cases must not be inspected. No deployment, push, or main merge. Stop with the
report after development comparison, or after feasible work is exhausted by an external
blocker. Record exact coverage omissions, actual usage and unresolved holds separately.
