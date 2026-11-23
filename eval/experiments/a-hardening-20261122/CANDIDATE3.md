# Candidate 3 development amendment

Candidate 2 pilot 20261122T140152_4554a4bf2d84 completed all five cases and is retained
as ancillary evidence. Assistant review found: U-0025 correct nearest-option reply
blocked after its Hayda pronoun lost a single preceding pharmacy; U-0091 valid
Ayyon strength question mis-scored; U-0150 ambiguous closing phrasing; U-1042 basket
total described with potentially per-item wording. No independent acceptance claimed.

Candidate 3 preserves decimal boundaries, associates explicit pronouns with a single
preceding pharmacy, handles explicit geographic comparison subsets and rejects equal
values claimed strictly cheaper/faster. Parser association failures remain unresolved
scorer failures requiring review; runtime blocks proven contradictions rather than
assuming an unparsed claim false. Tests include valid and deliberately false claims.
Language checking now detects high-confidence Arabizi replies to English clients as
well as the reverse. Scorer Ayyon accepts only actual strength-choice context.
Prompt v1.15 requires basket-total wording and exact numeric open-interval wording.
Accepted labels, backend authority, model, limits and acceptance targets unchanged.

476 focused tests passed plus an added integrated English repair test. Original full
backend and candidate2 integration results remain separate supporting checks.
Pin source and harness before paid work. Pilot the same five understanding cases,
R-0016 all contexts, M-0007 and M-0011 separately; review before full 352-case run.
Any subsequent repair requires a distinct candidate. No held-out content opened.
