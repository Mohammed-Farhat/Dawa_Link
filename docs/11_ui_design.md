# DawaLink: UI Design

**Version:** v1.0 · **Date:** 2026-10-22
**Builds on:** `03` v4.1 (screens and flows) · `04` v4.1 (rules, numbers) · `06` v1.2 (SSE, polling, errors) · `07` v1.2 (cards, plain-text replies) · `10` v1.0 (security)
**Status:** ✅ validated by the team (2026-10-22, decision log §U). **It can change during the build:**
- changes to the look and layout go on the canvas;
- changes to the rules go here;
- changing a validated decision gets a row in the decision log.

**Mockups:** the design canvas *DawaLink UI design* (10 boards): https://claude.ai/artifact/HYBxFhP96TUvhi1V9cCDLG. It is private until the owner shares it from its Share menu.

`03` says **what** each user can do and see. This document says **how it looks and behaves on screen**: the visual language, the layout of each portal, the reusable pieces, the states, accessibility, and how the frontend is built. The course asks us to *"design the interface around the actual user and workflow rather than defaulting automatically to chat"*. That is the first principle here.

---

## In short

- **Search first, not chat first.** The client's home opens with today's pickup and a search box. The assistant and sourcing requests are two equal entry points below it.
- **One look:**
  - a calm green brand;
  - **one meaning per color:** green = done or fits · blue = DawaLink is working on it · amber = needs your attention · red = failed · grey = information;
  - Inter font; borders instead of shadows; simple line icons.
- **Facts before words.** Every option shows the same facts in the same order: travel time, opening hours, whether the box lasts, prescription, price, availability. The agent's text explains its choice; **the card holds the facts**, rendered by code from the stored proposal.
- **One main button per card.** Used or expired cards change state instead of disappearing.
- **Built for low-end phones on slow data:**
  - mobile-first;
  - 44 px touch targets;
  - no images except maps, and maps only where needed;
  - per-portal code splitting.
- **Accessible:** WCAG 2.1 AA, checked automatically in tests and by hand before the demo.
- **Frontend:** React + TypeScript + Mantine, API types generated from OpenAPI, and every user-facing string in one file.
- **12 decisions**, validated on 2026-10-22 (§14). Three small changes to `03` (§13.1).

---

## 1. Principles

| Principle | In practice |
|---|---|
| **Search first, agent one tap away** | Home: today's pickup → search box → "Find medicines for me" and "Ask the assistant", side by side in importance. Chat is never the only way to do something. |
| **Urgent by design** | What's due today sits at the top of Home. The order number is one tap away ("Show at the counter"). |
| **Facts before words** | The same fact row, in the same order, on search results, agent cards, offers and plans |
| **One main action per card** | One green button. Secondary actions are outlined or text. |
| **Plain words, never codes** | "Reserved: pick up by today 23:00", not `RESERVED`; "This box expires before your 12 days end", not `DOES_NOT_FIT` |
| **Color is never the only signal** | Every status has a word or an icon as well (for color-blind users and bright sunlight) |
| **Show what the agent did, never what it can't show** | The request timeline lists actions in plain words. It never names other clients or private stock. |
| **Phones first for clients, desktops first for pharmacies and admins** | Client layouts start at 360 px. Pharmacy and admin screens use a sidebar that stacks on phones. |

---

## 2. Visual language

### 2.1 Colors (Mantine theme tokens)

| Token | Hex | Used for | Text contrast |
|---|---|---|---|
| `green.7` (primary) | `#0B6E4F` | Brand, main buttons, "done", "fits" | White on it 6.3:1 · on white 6.3:1 |
| `green.0` (tint) | `#E7F4EE` | Fit badge, selected chips, success banners | Green text on it 5.6:1 |
| `blue.7` / `blue.0` | `#1E4FB8` / `#E8EFFC` | **DawaLink is working on it:** searching, asking pharmacies, watching | 6.4:1 |
| `amber.7` / text / tint | `#B45309` / `#8A4B08` / `#FDF1D8` | **Needs your attention:** an offer waiting, your tap needed, paused, an expiry warning, degraded mode | 6.1:1 (text on tint) |
| `red.7` / `red.0` | `#B42318` / `#FDECEA` | **Failed:** expired (missed pickup), errors, cancel buttons | 5.7:1 (on tint) · 6.5:1 (on white) |
| `ink.9` / `ink.7` / `ink.6` | `#16211C` / `#4B5A53` / `#66736D` | Text · secondary text · hints | 16.6 · 7.3 · 5.0 :1 on white |
| `gray.0` / `gray.1` / `gray.3` | `#F6F7F5` / `#EEF1EF` / `#DDE3DF` | Page background · neutral boxes (prescription notice, night banner) · borders | none |

- **Light theme only** for now; a dark theme could come later.
- **Disabled controls** (`#66736D` on `#DDE3DF`) are exempt from the contrast rule. They always come with a word ("Reserved", "Expired").

### 2.2 Type, spacing, shapes, icons

| Element | Choice |
|---|---|
| **Typeface** | **Inter** (Latin), with **Noto Sans Arabic** for Arabic script, loaded only when Arabic text appears. **IBM Plex Mono** for order and request numbers (`R-7K3Q2F`). |
| **Sizes** | 24 bold (desktop page titles) · 20 bold (sheet titles) · 17 semibold (screen titles) · 16 (body and card titles) · 14 (secondary) · 13 (meta) · 12 (labels and badges) |
| **Body text on phones** | 16 px: no zooming needed, and no iOS auto-zoom on inputs |
| **Spacing** | A 4 px grid: 4 · 8 · 12 · 16 · 20 · 24 · 32 |
| **Corners** | 8 (badges, inputs) · 10 (buttons) · 14 (cards) · 20 (bottom sheets) |
| **Depth** | **Borders, not shadows** (`#DDE3DF`). Emphasis is a 2 px colored border: green = recommended, amber = needs your answer. |
| **Icons** | Tabler icons (line, 1.8 stroke), the set Mantine uses; always next to a word, except well-known icon buttons, which get an `aria-label` |
| **Emoji** | None in the product UI. The `03` sketches used emoji only as shorthand. |

---

## 3. Layout and navigation

### 3.1 Client portal (phone first)
- **Bottom bar** with four tabs: **Home · Assistant · Mine · Me**.
  - **Home** holds the search, which renames the "Search" tab in `03` (§13).
  - **Mine** lists requests, reservations and watches.
  - **Me** is the profile.
- **Detail pages** (search results, a reservation, a request) open full screen with a **back arrow** and no bottom bar, which leaves more room on small phones.
- **Wider than 992 px:** a top bar instead of the bottom bar, with the assistant as a side panel (`03` §1.2).
- **Reserve sheet:** a **bottom sheet** on phones and a centered dialog on desktop.

### 3.2 Pharmacy portal (desktop first)
- **Left sidebar:** Dashboard · **Reservations** · Inventory · Listings · **Early release** · Settings, with counters on Reservations (new) and Early release (waiting for an answer).
- On phones the sidebar stacks above the content. The **Reservations** page works fully on a phone (P-D10).
- **Early-release asks show at the top of Reservations** too, with the time left to answer, so a busy pharmacist doesn't miss them.

### 3.3 Admin console (desktop)
- A **dark sidebar**, so nobody confuses the admin console with the pharmacy portal.
- **Overview first:** what needs attention (escalations, approvals, reported answers, flags), then the agent's 7-day numbers (AS-2).

---

## 4. Components

**Rule for every agent card:** it is **rendered by code from the stored proposal** (`04` R-AG7). The agent's text never fills a card's facts, prices or buttons.

| Component | Used for (`03`) | Always shows | Main action | States |
|---|---|---|---|---|
| **Fact row** | Options, plans, offers | Walking and driving time (or "about 3 km" when routing is down) · opening hours ("Open until 23:00") | none | none |
| **Fit badge** | Options, plans, offers, reserve sheet | ✓ "Lasts your 12 days" (green), or ⚠ "Expires 25 Oct: make sure that's enough" (amber) when days of use are unknown (R-F2) | none | none |
| **Price block** | Everywhere a price appears | `436,000 LBP` (bold) · `≈ $4.9` · discount % · public price | none | none |
| **Prescription notice** | Options, sheet, reservation | A file icon + "Prescription needed: bring it" | none | none |
| **Option card** | Search results, CS-9 | Product + pack · pharmacy + area · fact row · fit badge · prescription · availability (≤ 5, then "5+") · price block | [Reserve] | **Recommended** (green border + badge + a one-line reason) · alternative ("Same medicine, another brand") · used ("Reserved ✓") · expired (dashed, grey) |
| **Plan card** | CS-9, CS-16 | One pharmacy's items + subtotals · fact row · the route for multi-pharmacy plans ("A → C, 22 min by car") · fit badge · total | [Reserve these] | Recommended · used · expired · "1 item was taken" (re-planned) |
| **Offer card** | CS-9, CS-16, CS-11 | **Amber border** · "valid until 13:05" · pharmacy + fact row · fit · price | [Accept and reserve] · [No thanks] | Accepted · expired · withdrawn ("No longer available") |
| **Request summary card** | CS-9 (AF-24) | Items + quantities + days of use · from (location or district) · "searches up to 6 hours" | [Start sourcing] | Used · outside request hours (button disabled + "from 08:00") |
| **Change card** | CS-16 | "Allow another brand?" / "Raise the max price to 800,000 LBP?" | [Yes] | Used · expired |
| **Status card** | Chat and request threads | Template text (reserved, picked up, not available, expired, cancelled) | [Show at the counter] or [I picked it up] | none |
| **Progress line** | Chat | "Searching…", "Planning your route…", "Asking pharmacies…" (`07` §3.2) | none | none |
| **Quick-reply chips** | Chat | ≤ 4 chips, ≤ 40 characters each (`07` §4.5) | Sends the text | none |
| **Status pill** | Lists, request items | One word or phrase in the color of its meaning (Foundations board) | none | none |
| **Banner** | Top of a screen | Degraded mode (amber, [Use Search]) · night (grey) · paused (amber) · unverified (grey, [Send the link again]) | Optional | none |
| **Toast** | After a failed tap | Red, plain message + next step ("Someone reserved this a moment ago. Other options") | Link | Disappears after 6 s; also announced to screen readers |
| **Counter view** | CS-10 | **The order number in large monospace**, product, quantity, amount to pay | [Directions] | Picked up · expired (+ [I picked it up]) |

---

## 5. Key screens

Each is drawn on the design canvas. Screens that aren't drawn reuse these components and layouts.

| Board | `03` | What's on it, top to bottom |
|---|---|---|
| Client · Home | CS-5 | Today's pickup (order number + [Show at the counter]) → search box + location ("Near Hamra · Change") → "Find medicines for me" → "Ask the assistant" → the open request with progress (green = reserved, blue = in progress) |
| Client · Search results | CS-6 | Search field → filter chips (location, **pickup today/tomorrow**, **days of use**, filters) → "4 boxes last your 12 days" + sort → option cards. **No "Recommended" badge here:** recommending is the agent's job. The search sorts by best match. |
| Client · Reserve sheet | CS-8 | Product + pharmacy → quantity stepper (max 3) → **pickup day** (Today with closing time / Tomorrow) → **days of use** with a live fit badge → prescription notice → total at the counter + "reserved immediately, you pay at the pharmacy" → [Cancel] [Reserve] |
| Client · Reserved | CS-10 | "Reserved" confirmation → **counter view** → pick up by, pharmacy, address, prescription → [Directions] [Cancel reservation] → timeline (incl. the reminder 4 h before) |
| Client · Assistant | CS-9 | The client's message (Arabizi) → the agent's plain-text reply (Arabizi) + 👎 → **recommended plan card** → "See 2 other options" (alternatives collapsed) → quick-reply chips in the client's language → message box |
| Client · Request page | CS-16 | Window ("Searching until 15:30 · 4 h 25 min left" + bar) → **each item with its status** → an offer card (amber) → "What DawaLink did" timeline → message box + [Cancel request] |
| Client · States | `03` §1.8 | Degraded, night, paused and unverified banners · the agent working · empty search (two next steps) · no box lasts · taken at tap time · an expired card |
| Pharmacy · Reservations | PS-4, PS-9 | Order-number search → **early-release ask** (amber, units, price, time left, [Decline] [Accept and hold it]) → table of active reservations (NEW badge, batch, expiry, pick up by, prescription, [Picked up] [Not available]) → "you never see who the client is" |
| Admin · Overview | AS-2, AS-6 | Needs-attention tiles → the agent's 7 days → an **emergency-claim escalation**: the summary labeled "written by the assistant", "priority can't be changed" guidance, links to the redacted conversation and trace, reply box |
| Foundations | none | Colors and meanings, type, the fact row and badges, statuses, buttons |

---

## 6. The assistant's screen: rules

1. **Replies arrive whole.** While the agent works, a **progress line** shows its step. Then the complete, already-checked reply appears (`06` API-D6). No word-by-word typing effect.
2. **Agent text is plain text** (`10` TM-D5):
   - no links, images, Markdown or HTML;
   - each message gets `dir="auto"`, so Arabic shows right-to-left and Arabizi left-to-right.
3. **Cards under the message**, in the order the agent chose:
   - **at most one "Recommended" card per medicine**, shown in full;
   - its alternatives (≤ 2, N-45) are folded under **"See N other options"**, so the screen stays short on a phone.
4. **Chips** in the client's language (≤ 4). Tapping a chip sends its text as a message. It never acts on its own.
5. **👎 under every agent reply** opens a reason + comment (AS-8).
6. **Busy:** "One moment…", and the message sends itself when the turn ends (`06` API-D8).
7. **Degraded mode:** an amber banner with [Use Search]. **Cards already shown keep working.**
8. **Cards never vanish:** a used or expired card shows its state ("Reserved ✓", "This option expired").
9. **New messages are announced** to screen readers (`aria-live="polite"`) and are kept when the page reloads. Polling picks up messages posted by the worker (N-28).
10. **The agent has no avatar or human name.** It's "Assistant", and the header says "Finds and reserves medicine. No medical advice."

---

## 7. States

| State | Rule |
|---|---|
| **Loading** | Lists show grey placeholder blocks shaped like the cards. Chat shows the progress line. Never a blank screen. |
| **Empty** | Always a next step. Empty search → [Ask DawaLink to find it] + [Notify me if it appears]. No box lasts → the latest expiry + "Ask DawaLink to find a box that lasts". |
| **Error after a tap** | A red toast in plain words + the next step (`09` P7). The message comes from the error **code** (`06` §3.2), never from raw server text. |
| **Validation** | The error text sits next to the field ("must be between 1 and 3"). |
| **Slow or no network** | "Can't reach DawaLink. Retrying…" An unsent message stays in the box. A tap that failed is retried with the **same idempotency key**, so nothing is created twice. |
| **Session expired** | Log in, then return to the same screen (`03` §1.8). |
| **Night, paused, unverified, degraded** | The banners on the States board |

**Messages for common error codes** (the full list lives in the frontend's strings file):

| Code | Message |
|---|---|
| `NOT_ENOUGH_STOCK` | "Someone reserved this a moment ago." + Other options |
| `DOES_NOT_FIT` | "This box expires on 28 Oct, before your 12 days end." + See boxes that fit |
| `PRICE_CHANGED` | "The price changed to 450,000 LBP. Reserve at the new price?" |
| `LIMIT_OPEN_ORDERS` | "You have 5 open reservations, the maximum." |
| `OUTSIDE_REQUEST_HOURS` | "DawaLink searches during the day. Please come back tomorrow from 08:00." |
| `PROPOSAL_EXPIRED` | "This option expired. Ask the assistant for fresh options." |
| `CONVERSATION_BUSY` | "One moment…" (retried automatically) |
| `ASSISTANT_UNAVAILABLE` | The degraded-mode banner |
| `RATE_LIMITED` | "Too many tries. Please wait a minute." |

---

## 8. Language, numbers and words

- **UI labels are in English** (D8). The assistant answers in the client's language and style. Text typed by users and the agent is shown with `dir="auto"`. A full Arabic interface is add-on A8.
- **All UI strings live in one file** (`frontend/src/strings/en.ts`). This keeps the wording consistent, lets the team review it in one place, and makes the Arabic interface a translation rather than a rewrite.
- **Numbers and dates:**

  | What | Format |
  |---|---|
  | Money | `436,000 LBP` + `≈ $4.9` (LBP first; USD rounded to 0.1) |
  | Times | 24-hour Beirut time with a day word: "Today 23:00", "Fri 23:00" |
  | Dates | "14 Mar 2027" |
  | Durations | "9 min walk", "4 min by car", "4 h 25 min left" |
  | References | Order and request numbers in monospace: `R-7K3Q2F`, `Q-4HX9TM` |
  | Digits | Western digits everywhere |

- **Words we use** (and avoid):

  | Use | Avoid |
  |---|---|
  | Reserve | Order, buy (nothing is paid online) |
  | Pick up by | Deadline, expiry of the reservation |
  | Not available | Rejected, declined |
  | Find medicines for me | Sourcing request (that's our internal name) |
  | Notify me | Watch, claim |
  | Same medicine, another brand | Equivalent, alternative composition |
  | Lasts your 12 days | Expiry fit |

---

## 9. Accessibility (target: WCAG 2.1 AA)

| Area | Rule |
|---|---|
| Contrast | Every text and background pair in §2.1 is ≥ 4.5:1 (checked) |
| Touch targets | ≥ 44 × 44 px on phones (chips and pills included); ≥ 36 px on desktop tables |
| Focus | A visible 2 px green focus ring on everything focusable. Sheets and dialogs keep focus inside, and Esc closes them. |
| Semantics | Real `<button>`, `<a>`, `<label>`, `<fieldset>` (the pickup choice) and `<table>` (pharmacy reservations). Icon-only buttons have `aria-label`s. |
| Live updates | The chat and the request timeline use `aria-live="polite"`; error toasts use `role="alert"` |
| Color | Never the only signal: words and icons on every status (§1) |
| Zoom and motion | Works at 200% zoom; respects "reduce motion" (no animations then) |
| Forms | Labels always visible; errors next to the field, in words |
| **Checks** | `axe` runs in component tests (CI). Before the demo: a keyboard-only pass and a screen-reader pass (TalkBack on Android, NVDA on Windows) through the demo scenarios. |

---

## 10. Low-end phones and slow data

- **Code split per portal:** the client bundle never includes pharmacy or admin code.
- **Maps are loaded only on screens that show a map** (§11). Search results show a list with travel times, not a map.
- **No images** except map tiles. Icons are inline SVG.
- **Fonts:** Inter (Latin subset), plus Noto Sans Arabic only when Arabic text appears (`unicode-range`).
- **Polling runs only while the chat or request page is visible:** it pauses when the tab is hidden and resumes when it's shown (N-28).
- **Budgets, measured before the demo:**
  - client start-up JavaScript ≤ 250 KB compressed;
  - Lighthouse mobile performance ≥ 80 on Home and Search results.

---

## 11. Maps and location

- **Where a map appears:**
  - pharmacy registration (placing the pin, PS-1);
  - listing detail (CS-7);
  - admin approval (checking the pin, AS-3).

  Leaflet with OpenStreetMap tiles and the "© OpenStreetMap contributors" credit.
- **[Directions]** opens OpenStreetMap's directions with **only the pharmacy's pin** as the destination. The client's location is never put in the link. This is a new outside link, added to `10` §4.3 (§13).
- **"Use my location":** the browser's permission prompt appears **only after the client taps**, and first we say why: *"To show walking and driving times. We round your location and never send it to the AI."* If the client refuses, the profile's district is used (FI-18).

---

## 12. Emails

- Simple HTML plus a plain-text version, with the same colors and the order number in monospace.
- **No images, no tracking pixels.** The only link opens DawaLink: the reservation, request or offer.
- One template per notification (CN-, PN-). They are written by us, never by the LLM (S10).

---

## 13. Frontend structure (for the build)

| Part | Choice |
|---|---|
| Stack | React + TypeScript + Vite, **Mantine** (the theme in §2), React Router, TanStack Query |
| Routes | Client: `/`, `/search`, `/assistant`, `/requests/:id`, `/reservations/:id`, … · Pharmacy: `/pharmacy/*` · Admin: `/admin/*`, each loaded on demand |
| API | Types **generated from the OpenAPI file** (`06` §9), plus one small client that: adds the `Idempotency-Key` to creating taps; turns error codes into messages (§7); handles `401` (log in again) and `409 CONVERSATION_BUSY` (retry) |
| Live data | Chat: SSE through `fetch` streaming (`06` §6.6.1). Everything else: TanStack Query, with 3 s polling while visible. |
| Folders | `frontend/src/{app, api, theme, strings, components/{cards,facts,feedback,layout}, features/{client,pharmacy,admin}}` |
| Tests | Vitest + Testing Library + `axe` for components; **a few Playwright flows** for the demo scenarios (bonus B-8) |
| Review help | Every frontend PR includes **screenshots** (phone and desktop) and lists the strings it adds, so the team can review it without reading TypeScript in depth |

### 13.1 Small changes to `03` (applied 2026-10-22)
1. **Bottom bar:** "🔍 Search" becomes **"Home"**, which holds the search (§3.1). Detail pages hide the bottom bar.
2. **CS-9:** the agent's alternatives are folded under "See N other options" (§6, rule 3).
3. **PS-6:** remove the "below minimum" zone from the inventory table, which is stale since §S (no fixed minimum).

**Also:** `10` §4.3 gets the [Directions] link (OpenStreetMap, destination only).

---

## 14. Decisions (validated 2026-10-22)

| ID | Decision | Recommendation | Why |
|---|---|---|---|
| UI-D1 | **Visual language** | A green brand (`#0B6E4F`); **one meaning per color** (green done/fits · blue working · amber attention · red failed · grey info); Inter + Noto Sans Arabic + IBM Plex Mono for order numbers; borders, not shadows; Tabler line icons; light theme only | Calm and trustworthy for a health-adjacent service; colors that mean the same thing everywhere are learned fast; little to build |
| UI-D2 | **Home is search first** | Today's pickup → search box → two equal entry cards (Find medicines for me · Ask the assistant) → the open request | The course asks for a UI built around the workflow, not chat by default; urgent pickups belong on top |
| UI-D3 | **Navigation** | Client: Home · Assistant · Mine · Me (renames "Search" to "Home"); detail pages full screen with a back arrow. Pharmacy and admin: a sidebar that stacks on phones; the admin sidebar is dark. | Fewer, clearer tabs; more room on small phones; no confusing the admin console with the pharmacy portal |
| UI-D4 | **One component per card kind**, rendered from the stored proposal | The same fact order everywhere; one main button; used or expired cards change state instead of vanishing; "Recommended" = green border + badge + a one-line reason; alternatives folded under "See N other options" | What the client sees is exactly what the button does (R-AG7); consistent cards are faster to read and to build |
| UI-D5 | **The counter view** | The order number in large monospace, one tap from Home ([Show at the counter]) | The moment at the counter must be effortless; the pharmacist reads the number at a glance |
| UI-D6 | **The reserve sheet asks the pickup day and days of use** | Inline, with a live fit badge (computed in the browser for display; the server re-checks at the tap, R-F5) | The professor's expiry rule is visible exactly where the client decides |
| UI-D7 | **Language** | English UI labels; `dir="auto"` per message and on user input; Arabic font loaded on demand; every string in one file | Arabizi and Arabic chat work today; the Arabic UI (A8) becomes a translation later |
| UI-D8 | **Accessibility** | WCAG 2.1 AA; `axe` in component tests; keyboard and screen-reader passes before the demo | Part of "secure, maintainable" software, and checkable evidence for graders |
| UI-D9 | **Low-end phones** | Per-portal code splitting, maps only where needed, no images, polling only while visible; budgets of ≤ 250 KB start-up JS and Lighthouse ≥ 80 | Our clients include people on cheap phones and slow data |
| UI-D10 | **Maps and location** | Maps only for the pin (registration, listing detail, admin approval); [Directions] hands off to OpenStreetMap with the pharmacy's pin only; the location prompt only after the tap, with the privacy sentence | Saves data, and keeps the location promise (never to the AI, never in a link) |
| UI-D11 | **Frontend structure and tests** | React + TS + Vite + Mantine, TanStack Query, OpenAPI-generated types, Vitest + Testing Library + `axe`, a few Playwright demo flows; screenshots in every frontend PR | Types can't drift from the API; Python-only reviewers can check the UI from screenshots and tests |
| UI-D12 | **The design canvas is the visual reference** | The build follows the canvas for look and layout. This document wins on rules. Screens not drawn reuse the same components. | One place to look; no need to draw every screen of `03` |

### 14.1 Applied on validation (2026-10-22)
- `03` → v4.2: the three small changes in §13.1.
- `10` → v1.1: §4.3 gets the [Directions] link.
- **Records:**
  - README: row 11 ✅;
  - decision log: new section §U (UI-D1–UI-D12);
  - `CLAUDE.md` §2.
- Checklist: T-15 (UI around the user) points here and to the canvas.
- **Later, when the team asks:** 4 more boards: the new request form (CS-15), listing detail (CS-7), pharmacy inventory upload (PS-6) and admin agent health (AS-10).
