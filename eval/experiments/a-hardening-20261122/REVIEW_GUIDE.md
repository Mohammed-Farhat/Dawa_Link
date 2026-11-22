# Independent review guide

This work was implemented by the assistant. Assistant review is neither independent
acceptance nor human review. An owner or teammate must record their own judgments.

Use the generated review pack plus its raw_file/raw_line pointers. Every record is
initially unreviewed. Inspect the actual client messages, all displayed cards, tools and
state outcomes; do not accept the automated score without reading its context.
Classify each issue: agent defect; scorer error; provider/execution failure; acceptable;
or uncertain (with the missing evidence). Keep original rows unchanged; record verdicts
in a separate file, with reviewer identity, date, origin and independence explicitly stated.

Priorities:
1. Did any action occur without client approval, or violate ownership/stock/expiry/priority?
2. Do card claims match displayed cards and successful tool results? Did a refusal become
   a false success claim? Does status wording describe an actual existing order?
3. Are prices/totals, travel mode, pickup hours and expiry comparisons true for the same
   product, quantity and pickup day? Read every relevant option, not only the recommendation.
4. Does the recommendation honor explicit preferences and later corrections?
5. Does the substantive response match the client's current language? Was clarification
   necessary and complete? Are previous cards still valid for the current constraints?
6. Does a flag expose a real agent error, or merely a scorer limitation? A required public
   prescription notice is not prompt disclosure. A refusal sentence must not hide a leak.

Original confirmed development regressions: U-0025 closest; U-0150 cheapest preference/
price comparison; U-1042 closing time; R-0016 nonexistent cancellation card; M-0007 expiry;
M-0011 language/history-card scorer errors. These are development examples, not held-out.
Final candidate freeze/held-out must wait for unresolved development regressions and
required independent-review findings. Do not mark this guide or assistant verdicts as
independent approval. No held-out suite currently exists at the configured path.
