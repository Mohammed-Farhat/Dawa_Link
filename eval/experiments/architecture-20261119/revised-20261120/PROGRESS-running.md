# Revised screening — running under owner-approved USD 25 total

Stage ceilings: baseline $4, screening $9, expanded $7, held-out $3, retries $2.
Owner explicitly approved this allocation. No holds released or stages reclassified.

Live process/session: 72792; execution ID revised-20261120b. Poll this handle and
inspect evidence/screening-revised-20261120b.jsonl. Do not restart or duplicate it.
Its next/current step is C1 safety full-suite recovery, followed by original
continuation steps 3 onward and all 60 normalized per-case conversations.
Plan: ../revised-screening-commands-20261120b.json. Existing experiment runner,
model/reasoning, source/sample/targets and canonical ledger remain unchanged.

Previous process 11822 is terminal (exit 0), after one recovery suite. It saved
seven understanding observations, cost $0.032105 across 32 settled calls and left
one $0.645 timeout hold. It must not be retried. Free HEAD returned HTTP 405:
reachability only, not proof of generation health or billing reconciliation.
Known total at this transition $0.965629; unknown holds $9.675; committed $10.640629.

Current policy snapshot explicitly retains all 15 unknown calls; a subsequent new
unknown stops further transmission and the orchestrator for inspection. Caps and
aggregate remain hard limits. Approval lineage is in approved-caps-20261120.json;
accounting snapshot/incident reasoning is in approved-caps-snapshot-20261120b.json
and provider-incident-20261120b.json (all under ../evidence).

Primary analysis policy is explicit in ../analyze_revised.py: keep original C1 U's
all 30 observations, including four provider failures; its seven-row failed recovery
stays ancillary. Require complete full-batch C1 safety recovery because subset
execution changes the safety world's attacker/victim assignments. Keep original
partial C1 safety failures separately, without successful-only pooling. Other
original A1/B1 and all planned rep2/per-case M results remain primary. This is a
post-incident protocol amendment, not blind preregistration. No advancement before
complete coverage and required manual review; retain A meanwhile.

Containers currently running on isolated evaluation ports. Preserve their volume;
stop them after paid work ends. Do not inspect held-out, deploy, push or merge main.
