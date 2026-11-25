# Prioritized fix backlog

Audit only: none implemented. See [report](REPORT.md) for reproduction, actual/expected behavior, evidence, impact and complete acceptance criteria. Effort estimates exclude product decisions and review.

| Order / ID | Severity / priority | Category | Role / area | Effort | Likely component | Verification target |
|---|---|---|---|---|---|---|
| 1. F-01 | High / P1 | Functional | Pharmacy / all portal routes | medium | `PharmacyPortal.tsx` | Exhaust 503/network retries; named error/retry/logout; recovery loads portal on phone/desktop. |
| 2. F-02 | Medium / P1 | Functional | Client /me, watch and nested forms | medium | `components/layout.tsx; wide.ts` | Unsaved values/open state survive 991↔992 and 390↔1440 without server save; inspect assistant drafts. |
| 3. F-03 | Medium / P2 | Navigation | Client no-stock search | medium | `SearchPage.tsx` | Normal search → exact catalog variant → manual watch → My medicines → stop; no crafted URL/model. |
| 4. I-01 | Medium / P2 | Interaction | Pharmacy counter pickup | medium | `ReservationCard.tsx` | Deliberate confirmation or supported recovery prevents accidental final pickup; keyboard accessible. |
| 5. A-01 | Low / P2 | Accessibility semantics | Client search regions | small | `SearchPage.tsx` | Region names include distinguishing strength/form/pack and duplicate names resolve. |
| 6. I-02 | Low / P3 | Interaction / keyboard pattern | Client saved-place choice | small | `WhereYouLive.tsx` | Arrow keys move/select within radio group; sensible single Tab entry and visible focus. |
| 7. V-01 | Low / P3 | Optional visual hierarchy | Pharmacy phone inventory | small | `InventoryPage.tsx` | Stock search/list reached sooner on 390 px without hiding whole-stock warning or losing add-box access. |

**Release gates:** F-01 and F-02. F-03 and I-01 should be resolved/reviewed before describing manual no-stock fallback and counter handover as ready for general users. A-01 fits that batch; I-02 and V-01 can follow.

**Needs verification, not confirmed defects:** modal background/header semantics with real assistive technology; native mobile keyboard/Safari behavior; incomplete automated contrast/name rules. These are described separately in the report.
