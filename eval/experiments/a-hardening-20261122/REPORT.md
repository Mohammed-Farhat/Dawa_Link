# A hardening and final-evaluation evidence

**Working report — final validation incomplete.** No independent acceptance, final
held-out evaluation or live-model browser verification has yet occurred.

A/current is retained because the sealed architecture screening assistant review
favored A (111/120) over B (91/120) and C (106/120), with execution coverage120/118/111.
These are original-source screening results, not measurements of repaired A. Full
original report: ../architecture-20261119/revised-20261120/REPORT.md. Architecture
implementation/evidence preserved separately in commitbdc5c16; all1481 sealed hashes
verified before edits. B/C remain reproducible and have not been further optimized.

Repairs add tool-grounded checks for absent cards/completed actions, same-product
comparisons and explicit cheapest preferences; language continuity, numeric hours and
basket-total prompt guidance. Scorer repairs cover displayed-card constraints, questions,
public prescription notices, false refusals, factual claims and language cues. Runtime
and scorer commits are separate. Backend stock/expiry/ownership/priority and approval
authority remain intact. Source/configuration pins preserve each distinct candidate.

Candidate1 incomplete ancillary run20261122T134541_9303082e3701 stopped on confirmed
false comparison guard (decimal splitting).74turns,39startedcases,187settledcalls,
$0.123494; no complete answer summary. Candidate2 five-case ancillary pilot
20261122T140152_4554a4bf2d84 exposed pronoun association/scorer weaknesses. Candidate3
five-case pilot20261122T141346_5f098b60717f completed without blocked turns but assistant
review found short-Arabizi language switches and quantity semantics concerns. R0016
candidate3pilot20261122T141542_4963f2f3a74d safely blocked but falsely classified Arabizi
as English. Candidate3 M0007pilot20261122T141614_867b1e3b18a8 completed. All original
outcomes retained; none replace the required full352-case measurement.

Candidate4 a0a0a84 fixes the false English classification and observed Arabizi absent
card wording. Pin candidate4-pin.json SHA256
6596010103acd8c4c64b40ad34e63120b2a586b208b2be9238163444726cbb72.
Runtime modelclaude-haiku-5-5, medium; promptv1.15. R0016pilot
20261122T141905_6576ce74fe1d completed, no state change or disclosure, $0.001298.
Original full backend2176 tests, candidate2 integrated601, candidate3 focused476 and
candidate4 focused regressions provide distinct supporting checks; see evidence logs.

Full development352, played conversations, primary paired simulation and live-model
browser results remain pending. Ambiguous comparisons are unresolved manual-review
flags; regex passes are not semantic acceptance. Assistant review files explicitly
set human_reviewed=false and independent=false. REVIEW_GUIDE.md defines the required
owner/teammate review; no independent findings have been accepted yet.

Held-out prerequisite: configured eval/heldout absent; metadata only checked, no
semantic contents opened. Suitable provenance plus resolved development regressions
and independent-review findings are required before final freeze/evaluation.

Canonical ledger ../architecture-20261118/budget.sqlite is append-only relative to
historical sealed records. Approved stage ceilings4/10/6/3/2 USD, total25. Historical
17unknown holds$10.965 remain unreleased. Current exact totals are in PROGRESS.md and
latest audit, not inferred from runner summary estimates. Do not reallocate stages.

Reproduce new runs from backend using paid_v4.py SUITE --architecture current
--stage expanded --model claude-haiku-5-5 --effort medium --max-usd LIMIT; full suites
understanding/safety/multiturn omit --cases. Use independent invocations for pilots.
Bootstrap verifies source/harness hashes, accepted freeze, canonical ledger and stops
before transmission after any new billing uncertainty. Existing local.env and root
.env are ignored prerequisites, never included in evidence. No reset/clean/push/deploy
or main merge. DEMO.md is a prepared script; it is not a completed verification record.
