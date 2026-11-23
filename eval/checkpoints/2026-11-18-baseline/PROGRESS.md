# Evaluation checkpoint — stopped after stage 1

Reference: 1e17db0ea522622caaf8da41d60df4ef152ccec3.
Branch: test/agent-evaluation. No commits/merges/push/deployment.
Existing untracked handoff preserved and checksum verified; never stage it.
All new work is under eval/checkpoints/2026-11-18-baseline/.
Read REPORT.md, CHECKS.md and evidence/ before resuming.

Completed: isolated PostgreSQL/Mailpit; fixed-clock synthetic seed (22 accounts);
input/package hashes; 1961 backend tests, 151 frontend tests; static checks/build;
planner 200/200; development dataset validation; saved-results privacy scan;
full free regression 133/241 units, zero no-shows/expiry-fit violations;
three paired ten-request free simulations; API/login/email capture runtime checks.

Audit: five reproduced scoring blind spots plus trace overwrite; shared spending,
partial-run accounting, provenance/template freshness and clustered CI need work.
Fixed policies produced unusable cards in smoke runs; investigate saved traces.
Eight high-severity npm audit findings saved; dependencies not upgraded.
Browser journeys blocked: browser access host unavailable; need scripted model fixture.

Paid calls: 0; spending $0/$25. spending.json is a record, NOT an enforcement guard.
No architecture changes or held-out inspection. Original app source unchanged.
API/frontend and isolated containers stopped; synthetic DB volume retained.

NEXT (only after user authorizes continuation): repair shared evaluation infrastructure
separately; rerun all contenders; restore browser access and execute full journeys.
Do not start paid baseline until hard aggregate/in-flight budget accounting exists.
Keep baseline agent unchanged. Do not overwrite evidence: use unique new run folders.
Ceilings: baseline $4, screening $6, expanded $10, heldout $3, retries $2.
