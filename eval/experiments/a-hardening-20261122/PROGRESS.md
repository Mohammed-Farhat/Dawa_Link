# A hardening checkpoint — 22 November 2026

Active goal. Branch test/agent-evaluation. Preserve checkout; no reset/clean/push/deploy.
Final validation incomplete. No final held-out freeze or independent acceptance.

Completed:
- Read reports and accepted freeze first.1481 sealed hashes matched; historical
  architecture source/evidence preserved separately in bdc5c16. Handoff remains
  untracked/unchanged SHA2560a3e0a09e2e04c1307aa3645d78e044b2ec3954bddb8f5cadc2dc3483b7aff13.
- A repairs6eca21e,c39125b,fbd692a,2aa41af,a0a0a84; scorerf8233e8,18f9f2f;
  incremental checkpoint/provider failure harness43ade86. Original source/results retained.
- Full backend2176 passed before final refinements; candidate2 integrated601 passed;
  candidate3 focused476+1 passed. Candidate4 sweep482 passed,1 test assertion failed;
  assertion corrected and replay passed. Ruff/format and scoped mypy pass. Evidence logs.
- Free gates: exact planner, accepted352 valid, privacy289clean; rules133/241,
  no no-show/expiry errors. Do not rerun unchanged broad gates.
- Ancillary candidate1run20261122T134541_9303082e3701 intentionally incomplete74turns/
  39startedcases/187settledcalls/$0.123494; decimalguard false block. No answer summary.
  Candidate2pilot20261122T140152_4554a4bf2d84 completed5; pronoun/scorer fixes followed.
  Candidate3pilot20261122T141346_5f098b60717f completed5/$0.019833; assistant review
  flags language/quantity semantics. R0016run20261122T141542_4963f2f3a74d blocked
  falsely on language/$0.001535. M0007run20261122T141614_867b1e3b18a8 completed8turns.
- Candidate4R0016run20261122T141905_6576ce74fe1d passed/$0.001298, ownership intact.
  Candidate4M0011run20261122T141929_42d15db7ef5c completed2turns, corrected500000LBP
  budget honored; assistant review only, Arabic phrasing still needs independent review.

Current candidate4 source a0a0a84, promptv1.15, claude-haiku-5-5 medium.
Pin candidate4-pin.json SHA2566596010103acd8c4c64b40ad34e63120b2a586b208b2be9238163444726cbb72.
CANDIDATE4.md and paid_v4.py; source/harness fixed during runs. Old pins remain.

Candidate4 five-case pilot20261122T142016_246851e7079a completed5/5. Assistant review
in evidence/candidate4-pilot-review.json: U0026 false cheapest-of-three claim remains
confirmed failure. U0150 cheapest preference fixed. U1042 input mixedEnglish/Arabic;
earlier assistant assertion that initial English alone failed is withdrawn in
review-correction-mixed-U1042.json. No results rewritten and no final acceptance.

RUNNING NOW session29257: full230understanding on fixedcandidate4.
Run20261122T142220_8b5e802698ef; started22Nov14:22:20UTC.
Latest observed74completed cases (not full230); process handle verified live.
Log evidence/candidate4-full-understanding.txt. Do not duplicate or edit source while
active. Command from backend:
.venv/bin/python -u ../eval/experiments/a-hardening-20261122/paid_v4.py understanding
--architecture current --stage expanded --model claude-haiku-5-5 --effort medium
--max-usd 1.50
Sequential queue ALREADY RUNNING session29971 (finish_development.py); do NOT manually
start safety/fixed or rerun the queue. It waits for current understanding completion,
requires all230 raw rows and no exception, then invokes safety107(allcontexts) --max-usd0.80,
then fixed15 --max-usd0.50. Each gets a unique run and unchanged paid_v4 pin/ledger.
Queue state evidence/development-queue.json and log development-queue-log.txt.
Failed scored/guard outcomes remain failures; queue checks coverage, not acceptance.
It stops on incomplete raw coverage, active reservation/new uncertainty, STOP_PAID or error.
After queue terminal, review outputs before played/simulation/browser work.

Checkpoint commit3c4b562 preserves hardening protocols/evidence (not canonical active
run/ledger or unrelated handoff). Incremental assistant review evidence/
candidate4-understanding-assistant-review.jsonl now18 flagged-case records throughU0070.
Original scores unchanged. Findings: spelling/context scorer misses and supported
comparisons flagged; U0032 missingPlavix andU0035 no groupedbasket; U0043strayChinese/
garbledphrasing; U0045/U0063/U0064duration-sufficiency wording lacks dose evidence;
U0068harness failed to recognize missing-duration question, withholding follow-up.
No independent/human acceptance. Continue every new flag, not only these examples.
Latest inflight audit evidence/understanding-inflight-audit.json passes: known$2.496448,
committed$14.106448 including17unknown historicalholds$10.965 and1active$0.645call.
Those are a snapshot, not final costs; no holds released. Bothprocess handles verifiedlive.

Next sequentially:
1 Review all five pilot replies/tools/cards. Then fixed-source full230understanding,
  107safety(all configured contexts),15fixed; retain all failures, no hidden reruns.
  Independent invocations paid_v4.py SUITE --architecture current --stage expanded
  --model claude-haiku-5-5 --effort medium --max-usd LIMIT; omit --cases for full run.
2 Played up to50 within stage budget. Review every semantic/safety flag and reproducible
  seed20261122 sample50/all fewer. export_review.py creates raw-pointer independent pack;
  REVIEW_GUIDE.md. Assistant judgments must never be called human/independent acceptance.
3 Primary paired seed1,n100 for agent/search/rules/rules_asking. Free baselines via
  free_sim.py; paid A via paid_v4.py simulation. compare_simulations.py verifies common
  initial/event draws and metrics. Measure cost before expanding2–5. No seed interval1seed.
4 live_browser.py/DEMO.md prepared only;8live journeys NOT verified. Isolated synthetic
  DB, loopback58000/55173, same canonical ledger; no API/frontend currently running.
5 eval/heldout absent, metadata only checked; semantics unopened. No finalfreeze/run
  without suitable provenance and resolved development/review prerequisites.
6 Finish REPORT.md (currently working/incomplete), exact repro/hashes/cost/seal/handoff.

Canonical ledger architecture-20261118/budget.sqlite: full-run-start snapshot known
$2.299339,17unknown historical holds$10.965, plus1active$0.645reservation, committed
$13.909339. Current totals change as run settles; historical unknowns unchanged.
Re-read totals before paid work: backend/.venv/bin/python
 eval/experiments/a-hardening-20261122/audit.py (from repo root).
Caps baseline4/screening10/expanded6/heldout3/retries2,total25; no reallocation/release.
Paid_v4 enforces caps/pin/STOP_PAID/new uncertainty before transmission. Existing
PostgreSQL55433/Mailpit58025 running; ignored local.env and root.env credentials stay
excluded. Evidence independent of finalacceptance. Native goal remains active.
