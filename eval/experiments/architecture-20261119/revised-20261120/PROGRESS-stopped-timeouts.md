# Revised architecture screening — stopped on repeated provider timeouts

Owner-approved stage ceilings: baseline $4, screening $9, expanded $7,
held-out $3, retries $2. **Total remains $25.** No stage reset or hold release.

Implementation/free tests remain complete; see ../REPORT.md. Paired screening is
incomplete. Retain A; no challenger earned expansion. Current report: REPORT.md here.

Both paid processes are terminal: session 11822/execution revised-20261120 stopped
at step 1; session 72792/execution revised-20261120b stopped at step 2. Never restart
or duplicate either. No paid process is running. STOP_REVISED_SCREENING protects
against accidental repetition. Isolated PostgreSQL/Mailpit stopped; volume preserved.

C1 U recovery: 20261120T100220_fc0fd422269f, seven saved observations, 32 settled
calls ($0.032105) plus one unknown $0.645 hold. C1 S recovery:
20261120T100958_6995d4b9b0d9, seven saved contexts, 17 settled calls ($0.015369)
plus one unknown $0.645 hold. Both timeout events were about 30 seconds, with no
request ID returned. Free unauthenticated HEAD responded HTTP 405, which proves
reachability only. No billing inference or invoice reconciliation was made.

Known total $0.980998; unknown holds $10.32; committed $11.300998 of $25.
Screening committed $7.337820 of $9, baseline $3.963178 of $4. Expanded/held-out/
retry allocations untouched. Next-call reservation $0.645; effective screening
capacity after reserving it is $1.017180. The total budget is not exhausted.

All 14 saved new recovery observations reviewed. Originals remain separate:
original C1 U's 30 observations include four provider failures; failed seven-row
recovery is ancillary. Original partial C1 safety and both attempted full recoveries
are retained. Never pool successful-only outcomes. No second repetition or normalized
fixed-conversation invocation started. Source/sample/targets/data remain frozen.

Next untouched original continuation is step 3 (C2 U); original C1 S still lacks
full paired coverage. Do not execute until provider reliability or attributable
billing evidence changes and remaining costs/reservations are reforecast. Existing
approval already covers stage limits 4/9/7/3/2; no new permission is needed merely
to use those same limits. Keep all 16 uncertain calls held unless verified receipts
support reconciliation. Do not repeatedly replay failed suites or infer zero charges.
A future resume needs a fresh execution ID and explicit case/run lineage, without
silently overwriting originals. Complete paired screening/review before advancement.

Offline reproduction (use a fresh output filename):
`backend/.venv/bin/python eval/experiments/architecture-20261119/analyze_revised.py OUTPUT.json`

Evidence: integrity.json, provider-incident.json, budget-final.sqlite, review JSONL
files here; ../evidence/approved-caps-20261120.json and policy snapshots/step logs.
No held-out inspection, push, deployment or main merge.
