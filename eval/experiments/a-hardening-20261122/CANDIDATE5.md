# Candidate 5 development amendment

Candidate4 results remain diagnostic evidence, including failures. Its understanding
rows 201–230 reused conversations; those 30 are excluded from primary single-case
validation. Its safety invocation exhausted 200 clients after 100 contexts; a distinct
continuation completed the unexecuted 24 contexts. Fixed conversations stopped after case13: 12 completed, case13 failed, and cases14–15
were unexecuted. No candidate4 results establish acceptance of candidate5.

Candidate5 fixes English order references falsely detected as Arabizi, recognizes
explicit English requests more reliably, rejects universal equal-price claims when
prices differ or returned options do not cover the claimed scope, and checks nearest
recommendations against feasible same-product travel times. High-confidence explicit
nearest/cheapest instructions come from client history, independently of model notes;
later corrections take precedence. A failed preference repair cannot redisplay the
rejected recommendation through fallback. Ambiguous preferences remain model handled.
Ownership, approval, stock authority, accepted labels and prompt v1.15 are unchanged.

Primary batches are pinned in candidate5-batches.json before outcomes: understanding
200+30 cases, safety 100+24 contexts across 89+18 cases, and 15 individually dispatched fixed conversations.
Each batch starts a fresh seeded world and stays within its 200-client capacity.
The bootstrap rejects oversized selections before sending calls. Fixed conversations
run separately because the original runner stops its suite after its first failed case. No client reuse,
hidden retries, best-of selection or pooling of candidates is allowed.

First inspect targeted development pilots R1022, U0145, U0146 and U1019 on this source.
Then execute every primary batch once, preserving execution failures. Review all safety
contexts and all semantic flags. The accepted freeze, model/settings, targets, ledger
and stage caps remain those in PROTOCOL.md. No held-out content has been opened.
This is a development pin, not the final held-out freeze or independent acceptance.
