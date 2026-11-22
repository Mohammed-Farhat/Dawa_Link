# Development-v2 coverage

| Suite | Category / purpose | English | Arabic | Arabizi | Mixed |
|---|---|---:|---:|---:|---:|
| understanding | misspelled | 1 | 1 | 1 | 1 |
| understanding | ambiguous | 1 | 1 | 1 | 1 |
| understanding | multi | 1 | 1 | 1 | 1 |
| understanding | budget | 1 | 1 | 1 | 1 |
| understanding | days_pickup | 1 | 1 | 1 | 1 |
| understanding | preference | 1 | 1 | 1 | 1 |
| safety | false_action | 1 | 1 | 1 | 1 |
| safety | priority | 1 | 1 | 1 | 1 |
| safety | cross_user | 1 | 1 | 1 | 1 |
| safety | pii_fishing | 1 | 1 | 1 | 1 |
| safety | injection | 1 | 1 | 1 | 1 |
| safety | clinical_hidden | 1 | 1 | 1 | 1 |
| multiturn | partial answers | 1 | 0 | 0 | 0 |
| multiturn | quantity correction | 0 | 1 | 0 | 0 |
| multiturn | budget correction | 0 | 0 | 1 | 0 |
| multiturn | pickup correction | 0 | 0 | 0 | 1 |
| multiturn | transport correction | 1 | 0 | 0 | 0 |
| multiturn | remove medicine | 0 | 1 | 0 | 0 |
| multiturn | conflicting instructions | 0 | 0 | 1 | 0 |
| multiturn | long conversation | 0 | 0 | 0 | 1 |

The 56 additions cover nine medicine families. Most frequent: Concor and Nexium, eight cases each (14.3%). Forms include tablets, solutions and drops. Conversation length is two to eight messages; M-0016 has eight.

All original 318 cases are preserved as byte-identical prefixes. New IDs: U-1031–U-1054, R-1031–R-1054, M-0009–M-0016.

See coverage.json for every addition and validation.json for every gold-item catalog-match count. Safety medicine names are checked in context during separate-session review; safety schema has no gold items.

Semantic conversation consistency is reviewed per turn; automated checks enforce schema, transport coherence and required facts before proposals. Correctly typed labels alone do not prove semantic correctness.
