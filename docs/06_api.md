# DawaLink: API Contracts

**Version:** v1.0 (validated by the team, API-D1–API-D14) · **Date:** 2026-10-18
**Builds on:** `04` v3.0 (rules; every guard below cites its rule) · `05` v2.0 (tables) · `03` v3.0 (screens) · `02` v2.0 (components)
**Status:** ✅ validated 2026-10-18 (decision log §O)

This document defines **every action** the website can ask the server to do, and **every interface between the main components** (the browser, the API, the agent, the worker and the database). For each endpoint it gives:
- who may call it;
- what goes in;
- what comes out;
- which errors are possible.

That is what the course asks for: *"interfaces between major components, including schemas, validation, authentication, and error behavior."* The exact OpenAPI file is **generated from the code** (§9); this document is the agreed contract that the code must match.

---

## In short

- **REST + JSON** under `/api/v1`, behind the same CloudFront URL as the website (no CORS).
- **One login cookie** (a server-side session). Every endpoint checks the **role**, the **account status** (verified, paused, approved…) and **ownership**. Someone else's object always looks like "not found".
- **One error format** with stable codes (`NOT_ENOUGH_STOCK`, `OUTSIDE_REQUEST_HOURS`, …). The frontend and the tests rely on the code, never on the message text.
- **Three kinds of buttons, three paths:**
  1. **search page** → `POST /reservations` (no agent involved, ever);
  2. **agent cards** → `POST /proposals/{id}/execute` (the card was created by a tool; the server re-checks everything);
  3. **system cards** (offers, status) → the object's own endpoint (`/offers/{id}/accept`).
- **The agent doesn't call this HTTP API.** Its tools call the same Python services in-process. The API is for humans' taps; the tools are for the agent's work (spec in `07`).
- **Chat:** a message returns a short **SSE stream** of progress, then the **complete, already-checked reply**. **Request threads and new cards:** the page **polls** for new messages every few seconds.
- **Every creating tap carries an `Idempotency-Key`**, so a double tap or a network retry never creates two things.

---

## 1. Conventions

| Topic | Convention |
|---|---|
| Base URL | `https://<cloudfront-domain>/api/v1`. Locally: `http://localhost:8000/api/v1`. |
| Format | JSON (UTF-8) in and out, except the upload (multipart), template and error downloads (CSV), and the chat stream (SSE). |
| Field names | `snake_case`. |
| IDs | UUIDs (strings). Human references: `ref` = `R-001042` (order, shown at the counter) and `Q-000045` (sourcing request). Searching a ref accepts it with or without the leading zeros (`R-1042`). |
| Time | ISO 8601 in **UTC** (`2026-10-20T19:00:00Z`). The frontend displays Beirut time. Responses that show time-based state include `server_now` (the **app clock**, so the demo clock works, `04` R-DEMO). Dates (`expiry_date`) are `YYYY-MM-DD`. |
| Money out | Integer **LBP** + `usd_approx` (computed on the server with the configured rate, `04` R-C3), for example `{"lbp": 716000, "usd_approx": 8.0}`. |
| Money in | `{"amount": 10, "currency": "USD"}` or `{"amount": 900000, "currency": "LBP"}`. The server converts to LBP; checks are always done in LBP. |
| Quantities | Integer units (`04` R-C4). The UI says "packs". |
| Pagination | Cursor-based: `?limit=20&cursor=<opaque>` → `{"items": [...], "next_cursor": "..." \| null}`. Default 20 (R-S1), maximum 50 (N-31). |
| Idempotency | Every endpoint that **creates** something requires the header `Idempotency-Key: <uuid>`. The frontend makes a new one per tap. Repeating the same key returns the **original result**. A group reserve stores one key per order (`<key>:<position>`, `05` §3.4). |
| Request ID | Every response has `X-Request-ID`. It also appears in error bodies and in all logs and traces for that request. |
| Caching | Every `/api` response has `Cache-Control: no-store`. |
| Size limits | JSON body ≤ 64 KB; upload ≤ 5 MB (`04` N-15). |
| Plain-language status | Objects with a `state` also carry `status_text` in plain words ("Reserved: pick up by Tue 21:00"), so the UI never shows raw states (`03` §1.1). |

---

## 2. Authentication and authorization

### 2.1 Session
- `POST /auth/login` creates a **server-side session** (`04` R-AU3, `05` `sessions`).
- The browser receives one cookie:

  `dl_session=<random token>; HttpOnly; Secure; SameSite=Strict; Path=/api; Max-Age=604800` (admins: 12 h).

  The server stores only the token's hash. JavaScript can't read the cookie, so an XSS bug can't steal it.
- **Logout, a password change or a suspension** revokes the session at once. The next request gets `401 UNAUTHENTICATED`.
- **CSRF protection:** the cookie is `SameSite=Strict`. In addition, every state-changing request (`POST`, `PATCH`, `DELETE`) must carry an `Origin` header equal to our own site; otherwise it gets `403 ORIGIN_REJECTED`.

### 2.2 The three checks on every endpoint
1. **Role:** `client`, `pharmacist` or `admin`. Wrong role → `403 FORBIDDEN`.
2. **Status gates:**
   - **Client** (`04` SM-2):

     | Status | Can |
     |---|---|
     | UNVERIFIED | Search only (`403 EMAIL_NOT_VERIFIED` elsewhere) |
     | PAUSED | Everything except reserving, accepting offers, and creating requests or watches (`403 CLIENT_PAUSED`, with `paused_until`) |
     | SUSPENDED | Can't log in (`403 ACCOUNT_SUSPENDED`) |
   - **Pharmacy** (`04` SM-1):

     | Status | Can |
     |---|---|
     | PENDING / REJECTED | Only see and edit its registration, and resubmit |
     | APPROVED | Everything |
     | SUSPENDED | Only see its reservations and mark them picked up or not available |

     Anything else → `403 PHARMACY_NOT_APPROVED`.
3. **Ownership:** a client sees only their own reservations, requests, watches, conversations and proposals. A pharmacy sees only its own reservations, inventory and asks. **Someone else's object returns `404 NOT_FOUND`**, never `403`, so IDs can't be probed for existence.

### 2.3 Privacy in responses
- A pharmacy **never** receives a client's name, email, phone, district or messages (`04` INV-9). It sees the order number, product, units, price, times and the "prescription needed" flag.
- A client **never** receives private inventory or which pharmacy holds it (`04` INV-8), except through an accepted early-release offer.
- Admins see contact details only through one audited endpoint (`GET /admin/clients/{id}/contact`, logged as `pii.view`).

---

## 3. Errors

### 3.1 One error format
```json
{
  "error": {
    "code": "NOT_ENOUGH_STOCK",
    "message": "Only 1 left now.",
    "details": {"available": 1},
    "request_id": "8f3c…"
  }
}
```
- `code` is stable and listed below. **Code and tests depend on `code` only.**
- `message` is plain English, safe to show to the user.
- Schema validation errors (`422 VALIDATION_ERROR`) list each field: `"details": {"fields": [{"field": "items[1].qty", "problem": "must be between 1 and 3"}]}`.
- A `500` never includes internal details (stack traces stay in the logs, found by `request_id`).

### 3.2 Error catalog

| Code | HTTP | When | Rule |
|---|---|---|---|
| **General** | | | |
| `VALIDATION_ERROR` | 422 | A field is missing, has the wrong type or is out of range | schemas |
| `UNAUTHENTICATED` | 401 | No session, or the session expired or was revoked | R-AU3 |
| `FORBIDDEN` | 403 | Wrong role | §2.2 |
| `ORIGIN_REJECTED` | 403 | A state-changing request from another site | §2.1 |
| `NOT_FOUND` | 404 | Doesn't exist, **or isn't yours** | §2.2 |
| `RATE_LIMITED` | 429 | Too many requests; `Retry-After` header set | §4 |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | A creating call without the header | §1 |
| `INTERNAL_ERROR` | 500 | Unexpected error (logged with `request_id`) | |
| `SERVICE_UNAVAILABLE` | 503 | Database unreachable | |
| **Accounts** | | | |
| `EMAIL_TAKEN` | 409 | Sign-up with a used email | SM-2 |
| `WEAK_PASSWORD` | 422 | < 10 characters or a common password | R-AU1 |
| `SIGNUP_LIMIT` | 429 | > 5 sign-ups from this network in 1 h | R-AU5 |
| `INVALID_CREDENTIALS` | 401 | Wrong email or password (one generic message) | R-AU2 |
| `ACCOUNT_LOCKED` | 429 | 5 failed logins → locked 15 min; `details.retry_after` | R-AU2 |
| `ACCOUNT_SUSPENDED` | 403 | Suspended account | SM-1, SM-2 |
| `TOKEN_INVALID` | 400 | Verification link invalid, used or expired | R-AU4 |
| `EMAIL_NOT_VERIFIED` | 403 | An action that needs a verified email | SM-2 |
| `CLIENT_PAUSED` | 403 | Reserving or creating while paused; `details.paused_until` | R-N1 |
| `PHARMACY_NOT_APPROVED` | 403 | A pharmacy action not allowed in its status | SM-1 |
| `LICENSE_TAKEN` / `PHONE_TAKEN` | 409 | Pharmacy registration duplicates | SM-1 |
| **Reservations and offers** | | | |
| `LISTING_NOT_AVAILABLE` | 409 | The listing is no longer visible (paused, expired, pharmacy suspended) | SM-3, O1 |
| `NOT_ENOUGH_STOCK` | 409 | Fewer units than asked; `details.available` (capped at 5) | O1 |
| `PRICE_CHANGED` | 409 | The price went **up** since it was shown; `details.new_price` (API-D4) | INV-5 |
| `LIMIT_OPEN_ORDERS` | 409 | Would exceed 5 open orders | R-L1 |
| `LIMIT_GROUP_UNITS` | 409 | Would exceed 3 units of the same medicine group | R-L2 |
| `GROUP_ITEM_FAILED` | 409 | One ticked item of a group failed; **nothing was reserved**; `details.failed_items[]` (each with its own code) | R-RQ6 |
| `RESERVATION_NOT_ACTIVE` | 409 | The reservation isn't RESERVED any more (already picked up, expired, cancelled) | SM-5 |
| `OFFER_NOT_OPEN` | 409 | The offer expired, was declined or was withdrawn; `details.reason` | O9–O11 |
| **Requests and watches** | | | |
| `OUTSIDE_REQUEST_HOURS` | 409 | Creating a request or watch outside request hours; `details.opens_at` | R-T3 |
| `LIMIT_OPEN_REQUESTS` | 409 | Already 2 open requests | R-RQ2 |
| `LIMIT_WATCHES` | 409 | Already 5 live watches | R-W2 |
| `WATCH_EXISTS` | 409 | Already watching this product; `details.watch_id` | R-W2 |
| `PRODUCT_NOT_ALLOWED` | 422 | A controlled product | R-C6 |
| `REQUEST_CLOSED` | 409 | Acting on a closed request | R-RQ9 |
| **Agent and conversations** | | | |
| `PROPOSAL_EXPIRED` | 409 | The card is too old; the agent can make a new one | API-D3 |
| `PROPOSAL_USED` | 409 | The card's button was already used | INV-21 |
| `SELECTION_INVALID` | 422 | Ticked items that aren't in the card | R-RQ6 |
| `CONVERSATION_BUSY` | 409 | The agent is already working on this conversation; `details.retry_after_ms` | R-AG2 |
| `ASSISTANT_UNAVAILABLE` | 503 | The LLM is down: degraded mode; `details.fallback = "search"` | C15 |
| `TOKEN_BUDGET_EXCEEDED` | 429 | The client's daily AI budget is used up; `details.until` | R-AS |
| `MESSAGE_TOO_LONG` | 422 | > 1,000 characters | R-AS |
| `ALREADY_REPORTED` | 409 | 👎 twice on the same reply | SM-10 |
| **Pharmacy** | | | |
| `PICKUP_DEADLINE_PASSED` | 409 | [Picked up] after the deadline (no late pickup) | O2 |
| `UNITS_INVALID` | 422 | [Not available] units outside 1…held units | O3 |
| `UPLOAD_FAILED` | 422 | Wrong file type, too many rows, missing template columns, formulas or macros; `details.reason` | SM-4 |
| `FILE_TOO_LARGE` | 413 | > 5 MB | N-15 |
| `UPLOAD_NOT_VALIDATED` | 409 | Applying an upload that was discarded or replaced | SM-4 |
| `ITEM_EXISTS` | 409 | Manual add of an existing (product, batch, expiry); `details.item_id` | R-U1 |
| `PRICE_ABOVE_PUBLIC` | 422 | Price override or early-release price above the public price | R-PR1, R-E6 |
| `ASK_NOT_OPEN` | 409 | Answering an ask that expired or was withdrawn | SM-6 |
| **Admin** | | | |
| `REASON_REQUIRED` | 422 | An admin action without a reason | SM-1, SM-2 |
| `DEMO_MODE_OFF` | 404 | The demo clock outside demo mode | R-DEMO |

---

## 4. Rate limits

| What | Limit | On excess |
|---|---|---|
| Failed logins | 5 in 15 min per account → locked 15 min | `ACCOUNT_LOCKED` (R-AU2) |
| Sign-ups | 5 per network address per hour | `SIGNUP_LIMIT` (R-AU5) |
| Resend verification email | 1 per minute | `RATE_LIMITED` |
| Chat messages | 20 per minute, 100 per day per client | `RATE_LIMITED` (R-AS) |
| Any other API call | 120 per minute per session (N-29) | `RATE_LIMITED` |
| Polling for new messages | Every 3 s while a chat or request page is open (N-28); fits inside the general limit | none |

Agent-side limits (tool calls per turn, early-release asks) are enforced inside the services, not here (`04` R-AS, R-E3).

---

## 5. Shared schemas

Schemas are written as **Pydantic models**, the same way they'll appear in `backend/src/dawalink/api/schemas/`. `…` means "fields from the referenced model".

### 5.1 Common pieces
```python
class Money(BaseModel):          # output
    lbp: int                     # integer LBP
    usd_approx: float            # rounded to 0.5, computed server-side

class MoneyIn(BaseModel):        # input
    amount: Decimal = Field(gt=0)
    currency: Literal["LBP", "USD"]

class District(BaseModel):
    id: int
    name: str
    governorate: str

class ProductSummary(BaseModel):
    id: UUID
    name: str                    # MoPH name
    strength: str | None         # "1 g", "850 mg"
    form: str                    # "tablet", "syrup"
    pack: str | None             # "14 tablets"
    prescription_required: bool  # shows the notice (R-P1)
    public_price: Money

class PharmacyCard(BaseModel):   # what a client sees about a pharmacy
    id: UUID
    name: str
    district: District
    address: str
    phone: str
    open_now: bool
    closes_at: datetime | None   # today, if open
    pickup_days: int             # 1–3 (N-6)
```

### 5.2 Account
```python
class Me(BaseModel):
    id: UUID
    role: Literal["client", "pharmacist", "admin"]
    email: str
    full_name: str
    email_verified: bool
    client: "ClientState | None"
    pharmacy: "PharmacyState | None"

class ClientState(BaseModel):
    status: Literal["UNVERIFIED", "ACTIVE", "PAUSED", "SUSPENDED"]
    paused_until: datetime | None
    district: District
    alternatives_ok_default: bool
    missed_pickups_30d: int      # "Missed pickups: 0 of 2"

class PharmacyState(BaseModel):
    id: UUID
    name: str
    status: Literal["PENDING", "APPROVED", "REJECTED", "SUSPENDED"]
    status_reason: str | None
    info_requested: bool
```

### 5.3 Search and reservations
```python
class Listing(BaseModel):        # a visible inventory item (04 SM-3)
    id: UUID                     # the inventory item's id
    product: ProductSummary
    pharmacy: PharmacyCard
    area: Literal["same_district", "same_governorate", "other"]   # R-S2
    price: Money
    discount_pct: int
    expiry_date: date
    days_left: int               # from the app clock
    available: int               # capped at 5 (R-S5)
    more_available: bool         # True when more than 5
    is_alternative: bool         # same composition, other brand (R-S4)

class Reservation(BaseModel):    # an order (04 SM-5)
    id: UUID
    ref: str                     # "R-001042": shown at the counter
    state: Literal["RESERVED", "PICKED_UP", "NOT_AVAILABLE", "EXPIRED_NO_SHOW",
                   "CANCELLED_BY_CLIENT", "CANCELLED_BY_SYSTEM"]
    status_text: str             # "Reserved: pick up by Tue 21:00"
    product: ProductSummary
    pharmacy: PharmacyCard
    qty: int                     # units held now (or handed over, once picked up)
    qty_requested: int
    price_each: Money            # the snapshot; never changes (INV-5)
    total: Money
    deadline: datetime | None    # pick up by
    source: Literal["search", "assistant", "request", "watch", "early_release"]
    request_id: UUID | None
    created_at: datetime
    closed_at: datetime | None

class Offer(BaseModel):          # an order in state OFFERED (O7, O8)
    id: UUID
    kind: Literal["matching", "early_release"]
    product: ProductSummary
    pharmacy: PharmacyCard       # revealed only now (INV-8)
    qty: int
    price_each: Money
    expiry_date: date
    expires_at: datetime         # 2 h (N-12)
    claim_id: UUID
    request_id: UUID | None
```

### 5.4 Watches and sourcing requests
```python
class Watch(BaseModel):          # a claim of kind WATCH (04 SM-7)
    id: UUID
    product: ProductSummary
    include_alternatives: bool
    district: District
    max_price: Money | None
    qty: int
    qty_missing: int
    ends_at: datetime            # creation + 6 h (N-11)
    state: Literal["ACTIVE", "OFFER_PENDING", "FULFILLED", "EXPIRED", "CANCELLED"]
    status_text: str

class Waiting(BaseModel):        # what DawaLink is doing for a missing item
    watching_new_stock: bool
    asked_pharmacies: int        # "asked N" only (R-E8)
    answers_by: datetime | None
    open_offer_ids: list[UUID]

class RequestItem(BaseModel):
    id: UUID
    position: int
    product: ProductSummary
    qty: int
    qty_secured: int
    max_price: Money | None
    state: Literal["SEARCHING", "PROPOSED", "WAITING", "SECURED", "UNAVAILABLE", "CANCELLED"]
    status_text: str             # "1 of 2 reserved, looking for 1 more"
    reservations: list[ReservationRef]       # id + ref + pharmacy name
    waiting: Waiting | None

class SourcingRequest(BaseModel):            # 04 SM-8
    id: UUID
    ref: str                     # "Q-000077"
    state: Literal["OPEN", "CLOSED"]
    outcome: Literal["FULFILLED", "PARTIAL", "UNFULFILLED", "CANCELLED"] | None
    district: District
    alternatives_ok: bool
    ends_at: datetime
    items: list[RequestItem]
    conversation_id: UUID        # the request thread
    created_at: datetime
    closed_at: datetime | None
    server_now: datetime
```

### 5.5 Conversations, messages and cards
```python
class CardLine(BaseModel):
    label: str                   # "At the counter"
    value: str                   # "716,000 LBP (≈ $8)"

class SelectableItem(BaseModel): # a checkbox on a group sheet (R-RQ6)
    item_key: str
    label: str                   # "Concor 5mg × 2"
    price: Money
    checked: bool = True

class CardAction(BaseModel):
    label: str                   # "Reserve these"
    call: Literal["execute_proposal", "accept_offer", "decline_offer",
                  "open_reservation", "open_request", "open_search"]
    target_id: UUID | None       # proposal / offer / reservation / request id
    selectable_items: list[SelectableItem] | None

class Card(BaseModel):
    card_id: UUID
    origin: Literal["proposal", "system"]    # agent card (from a tool) or template card
    type: Literal["option", "plan", "request_summary", "constraint_change",
                  "remove_item", "cancel", "offer", "status", "progress"]
    title: str
    lines: list[CardLine]        # rendered by the server from stored data, never from LLM text
    prescription_notice: bool
    actions: list[CardAction]
    expires_at: datetime | None
    state: Literal["open", "used", "expired"]

class Message(BaseModel):
    seq: int
    author: Literal["client", "agent", "system", "admin"]
    kind: Literal["text", "card", "timeline"]
    text: str | None             # stored redacted (INV-10): a phone number shows as "[phone]"
    cards: list[Card]
    quick_replies: list[str]     # choice chips: tapping one just sends that text
    reportable: bool             # True for agent replies (👎)
    created_at: datetime

class MessagesPage(BaseModel):   # the polling response
    conversation_id: UUID
    kind: Literal["chat", "request"]
    request_id: UUID | None
    messages: list[Message]      # only messages after `after_seq`
    last_seq: int
    busy: bool                   # an agent turn is running (show "…")
    server_now: datetime
```
- **Internal `event` messages are never returned to clients.** These are the decision events the agent reads (`05` `chat_messages.kind='event'`). The client sees the matching status card or timeline line instead.
- **Cards come in two kinds (API-D3):**
  - **Agent cards** (`origin = "proposal"`) are created by a tool and stored in `proposals`. The LLM only chooses which ones to show. Their button calls `POST /proposals/{id}/execute`.
  - **System cards** (`origin = "system"`) are template cards, such as offers and status. Their button calls the object's own endpoint, such as `/offers/{id}/accept`.

  Either way, the text on the card is built by the server from stored data.
- **Quick replies (chips)** only send their text as a new message. **They never execute anything.**

---

## 6. Endpoints

**How to read the tables:**
- **Who** is the role and status needed (§2.2).
- 🔑 means the `Idempotency-Key` header is required.
- **Rule** points to `04`.

All paths are relative to `/api/v1`.

### 6.1 Public, configuration and accounts

| Method · Path | Who | Request → Response | Errors | Rule |
|---|---|---|---|---|
| `GET /health` | anyone | → `{status, db, version}` (used by the load balancer) | `SERVICE_UNAVAILABLE` | |
| `GET /config/public` | anyone | → `{request_hours: {start, end}, search_window_hours, offer_hours, lbp_per_usd, rate_date, discount_tiers, server_now, demo_mode}` | | §5 numbers |
| `GET /districts` | anyone | → `list[District]` | | R-S2 |
| `POST /auth/register/client` | anyone | `{email, password, full_name, phone?, district_id, accept_terms: true}` → **201** `Me` + session cookie; verification email sent | `EMAIL_TAKEN`, `WEAK_PASSWORD`, `SIGNUP_LIMIT`, `VALIDATION_ERROR` | SM-2, R-AU1, R-AU5 |
| `POST /auth/register/pharmacy` | anyone | `{email, password, pharmacy: {name, license_number, phone, address, district_id, pickup_days, hours: [{weekday, open, close}]}, accept_terms: true}` → **201** `Me` (pharmacy PENDING) + cookie | `EMAIL_TAKEN`, `LICENSE_TAKEN`, `PHONE_TAKEN`, `WEAK_PASSWORD` | SM-1 |
| `POST /auth/login` | anyone | `{email, password}` → `Me` + cookie | `INVALID_CREDENTIALS`, `ACCOUNT_LOCKED`, `ACCOUNT_SUSPENDED` | R-AU2, R-AU3 |
| `POST /auth/logout` | any | → **204**; session revoked | | R-AU3 |
| `GET /auth/me` | any | → `Me` | `UNAUTHENTICATED` | |
| `POST /auth/verify-email` | anyone | `{token}` → `Me` (client becomes ACTIVE) | `TOKEN_INVALID` | R-AU4 |
| `POST /auth/verify-email/resend` | client (UNVERIFIED) | → **202** | `RATE_LIMITED` | R-AU4 |
| `POST /auth/password` | any | `{current_password, new_password}` → **204**; other sessions revoked | `INVALID_CREDENTIALS`, `WEAK_PASSWORD` | R-AU1 |
| `GET /me/profile` · `PATCH /me/profile` | client | `{phone?, district_id?, alternatives_ok_default?}` → `Me` | `VALIDATION_ERROR` | CS-13 |

### 6.2 Catalog and search

| Method · Path | Who | Request → Response | Errors | Rule |
|---|---|---|---|---|
| `GET /catalog/products?q=&limit=` | logged in | → `{items: list[ProductSummary], did_you_mean: list[str]}` (fuzzy; brand or ingredient; **controlled products never returned**) | | R-C6, CS-6 |
| `GET /catalog/products/{id}` | logged in | → `ProductSummary` + `{ingredients: [{name, strength}], atc_code}` | `NOT_FOUND` | R-C2 |
| `GET /catalog/products/{id}/equivalents` | logged in | → `list[ProductSummary]` (same equivalence group only) | `NOT_FOUND` | R-C5 |
| `GET /listings?product_id=\|q=&district_id=&max_price=&currency=&include_alternatives=&sort=best\|cheapest\|latest_expiry&cursor=&limit=` | client (any status but SUSPENDED) | → `{items: list[Listing], next_cursor, server_now}`. `district_id` defaults to the profile; it sets the area order, not a filter. | `VALIDATION_ERROR` | R-S1–R-S5 |
| `GET /listings/{id}` | client | → `Listing` + `{pharmacy_hours: [...], other_offers_count}` | `NOT_FOUND` (also when it stopped being visible) | CS-7 |

### 6.3 Reservations and offers (client)

| Method · Path | Who | Request → Response | Errors | Rule |
|---|---|---|---|---|
| `POST /reservations` 🔑 | client ACTIVE | `{listing_id, qty, expected_price_lbp}` → **201** `Reservation` (`source = "search"`; **never wakes the agent**) | `LISTING_NOT_AVAILABLE`, `NOT_ENOUGH_STOCK`, `PRICE_CHANGED`, `LIMIT_OPEN_ORDERS`, `LIMIT_GROUP_UNITS`, `EMAIL_NOT_VERIFIED`, `CLIENT_PAUSED` | O1, R-AG5 |
| `GET /reservations?view=active\|history&cursor=` | client | → page of `Reservation` | | CS-10 |
| `GET /reservations/{id}` | client (own) | → `Reservation` + `timeline: list[{at, text}]` | `NOT_FOUND` | CS-10 |
| `POST /reservations/{id}/cancel` | client (own) | → `Reservation` (CANCELLED_BY_CLIENT; no penalty) | `RESERVATION_NOT_ACTIVE` | O5, R-N2 |
| `GET /offers?state=open` | client | → `list[Offer]` | | CN-9, CN-10 |
| `POST /offers/{id}/accept` 🔑 | client ACTIVE (own) | → **201** `Reservation`; the claim's other offers are withdrawn at once | `OFFER_NOT_OPEN`, `LIMIT_OPEN_ORDERS`, `LIMIT_GROUP_UNITS`, `CLIENT_PAUSED` | O9, R-W3 |
| `POST /offers/{id}/decline` | client (own) | → **204**; the unit goes to the next claim | `OFFER_NOT_OPEN` | O10 |

**Price protection (API-D4):** the client sends the price it was shown (`expected_price_lbp`). If the price went **up** since then (a new day moved it to another discount tier, or the pharmacy changed its override) → `409 PRICE_CHANGED` with the new price, and nothing is reserved. If it went **down**, the reservation goes through at the lower price.

### 6.4 Watches ([Notify me])

| Method · Path | Who | Request → Response | Errors | Rule |
|---|---|---|---|---|
| `POST /watches` 🔑 | client ACTIVE | `{product_id, include_alternatives, qty, max_price?: MoneyIn, district_id?}` → **201** `Watch` (ends after the search window) | `OUTSIDE_REQUEST_HOURS`, `LIMIT_WATCHES`, `WATCH_EXISTS`, `PRODUCT_NOT_ALLOWED`, `CLIENT_PAUSED` | R-W1, R-W2, R-T3 |
| `GET /watches?state=live\|all` | client | → `list[Watch]` | | CS-11 |
| `POST /watches/{id}/cancel` | client (own) | → `Watch` (CANCELLED; its offers withdrawn) | `NOT_FOUND` | SM-7 |

Matching then runs **first come, first served** (R-PRI). The client is told by an offer card + email (CN-10), or by CN-11 when the window ends without stock.

### 6.5 Sourcing requests

| Method · Path | Who | Request → Response | Errors | Rule |
|---|---|---|---|---|
| `POST /requests` 🔑 | client ACTIVE | `{items: [{product_id, qty, max_price?: MoneyIn}] (1–5), district_id?, alternatives_ok}` → **201** `SourcingRequest`. The agent's first turn starts within seconds (the search runs immediately). | `OUTSIDE_REQUEST_HOURS`, `LIMIT_OPEN_REQUESTS`, `PRODUCT_NOT_ALLOWED`, `VALIDATION_ERROR` (0 or > 5 items, qty outside 1–3, the same product twice), `CLIENT_PAUSED` | R-RQ1, R-RQ2, R-T8 |
| `GET /requests?state=open\|closed&cursor=` | client | → page of `SourcingRequest` | | CS-5 |
| `GET /requests/{id}` | client (own) | → `SourcingRequest` | `NOT_FOUND` | CS-16 |
| `POST /requests/{id}/cancel` | client (own) | → `SourcingRequest` (CANCELLED; its claims, asks and offers withdrawn; existing reservations kept) | `REQUEST_CLOSED` | R-RQ9 |

The request form (CS-15), the agent's summary card ([Start sourcing], via `/proposals/{id}/execute`) and the search empty state (pre-filled form) all end in the same service. Changing constraints and removing an item are **agent cards** (§6.7).

### 6.6 Conversations and the agent

| Method · Path | Who | Request → Response | Errors | Rule |
|---|---|---|---|---|
| `GET /conversations/active-chat` | client ACTIVE or PAUSED | → `{conversation_id, kind: "chat"}` (created if none) | `EMAIL_NOT_VERIFIED` | D9 |
| `POST /conversations/new-chat` | client | → `{conversation_id}`; the old chat is archived (kept 30 days) | | D9, R-RET |
| `GET /conversations/{id}/messages?after_seq=&limit=` | client (own) | → `MessagesPage`. **The polling endpoint:** the page calls it every 3 s while open. | `NOT_FOUND` | API-D7 |
| `POST /conversations/{id}/messages` | client (own) | `{text (1–1,000), client_message_id: UUID}` → **chat:** an **SSE stream** (§6.6.1). **Request thread:** **202** `{message_seq}`; the worker runs the turn, and the page sees the reply by polling. | `CONVERSATION_BUSY`, `ASSISTANT_UNAVAILABLE`, `TOKEN_BUDGET_EXCEEDED`, `MESSAGE_TOO_LONG`, `RATE_LIMITED`, `REQUEST_CLOSED` | R-AG2, R-AS, C15 |
| `POST /conversations/{id}/messages/{seq}/report` | client (own) | `{reason, comment? (≤ 500)}` → **201** (only agent replies can be reported) | `ALREADY_REPORTED`, `NOT_FOUND` | SM-10 |

- `client_message_id` makes a retried send safe: the same ID is never processed twice.
- **Busy (R-AG2):** if the agent is already working on the conversation (for example, re-planning after a pharmacy event), the API answers `409 CONVERSATION_BUSY` with `retry_after_ms`. The UI shows "One moment…" and resends automatically (API-D8).

#### 6.6.1 The chat stream (SSE)
`Content-Type: text/event-stream`. Events, in order:
```
event: turn_started      data: {"turn_id": "…", "client_message_seq": 41}
event: progress          data: {"label": "Searching…"}             (0 or more)
event: progress          data: {"label": "Planning…"}
event: message           data: Message                              (the complete, checked reply)
event: turn_completed    data: {"agent_message_seq": 42, "outcome": "ok"}
: heartbeat                                                          (a comment line every 15 s)
event: error             data: {"error": {…}}                       (instead of message, on failure)
```
- **No word-by-word streaming (API-D6).** The reply is sent **once it has passed the output check**:
  - the clinical-advice check;
  - no PII;
  - only proposal IDs that this turn's tools created.

  If we streamed the words as they were generated, a sentence the check would block could already be on the client's screen. The "fast feeling" comes from the `progress` events.
- `outcome` ∈ {`ok`, `fallback`, `guardrail_blocked`, `budget_exceeded`, `error`} (the same values as `05` `agent_runs.outcome`).
- If the connection drops, nothing is lost. The reply is saved, and the next poll returns it.

### 6.7 Proposals: tapping an agent card

| Method · Path | Who | Request → Response | Errors | Rule |
|---|---|---|---|---|
| `POST /proposals/{id}/execute` 🔑 | client ACTIVE (own proposal) | `{selected_item_keys?: list[str]}` (only for `reserve_group`: a subset of the card's items) → **200/201** `ExecuteResult` | `PROPOSAL_EXPIRED`, `PROPOSAL_USED`, `SELECTION_INVALID`, `NOT_FOUND`, plus the errors of the underlying action (below) | R-AG7, INV-21 |

```python
class ExecuteResult(BaseModel):
    proposal_id: UUID
    kind: Literal["reserve", "reserve_group", "accept_offer", "cancel",
                  "request_summary", "constraint_change", "remove_item"]
    reservations: list[Reservation] = []
    request: SourcingRequest | None = None
    message: str                 # "Reserved ✅ R-001042: show this number at the counter"
```

**What each kind does**, re-validated as if new:

| Kind | Effect | Extra errors | Rule |
|---|---|---|---|
| `reserve` | Reserves one listing | as `POST /reservations` (incl. `PRICE_CHANGED`) | O1 |
| `reserve_group` | Reserves the ticked items at one pharmacy, **all or none** | `GROUP_ITEM_FAILED`, `LIMIT_*`, `PRICE_CHANGED` | R-RQ6 |
| `accept_offer` | Accepts an open offer the agent re-showed | as `/offers/{id}/accept` | O9 |
| `cancel` | Cancels a reservation | `RESERVATION_NOT_ACTIVE` | O5 |
| `request_summary` | Creates the sourcing request ([Start sourcing]) | as `POST /requests` | R-RQ1 |
| `constraint_change` | Allows alternatives, or raises a max price, on an open request | `REQUEST_CLOSED` | R-RQ4 |
| `remove_item` | Cancels one item of an open request | `REQUEST_CLOSED` | R-RQ4 |

- **When a group fails:** nothing is reserved. The response lists the failed item(s) with reasons. **The server also gives the agent a turn**: it writes an `event` message and sets `pending_turn_at`. The agent then says which item failed, offers a new card with the rest, and keeps sourcing the failed one (R-RQ6).
- **Unticked items** go back to the agent the same way.
- **Proposals expire** 2 h after creation (N-30), and each can be used once.

### 6.8 Notifications

| Method · Path | Who | Request → Response | Rule |
|---|---|---|---|
| `GET /notifications?cursor=` | any | → page of `{id, type (CN-x / PN-x), title, body, link, read, created_at}` | R-NT |
| `GET /notifications/unread-count` | any | → `{count}` (polled with the page) | |
| `POST /notifications/read` | any | `{ids: list[int]} \| {all: true}` → **204** | |

### 6.9 Pharmacy

| Method · Path | Who | Request → Response | Errors | Rule |
|---|---|---|---|---|
| `GET /pharmacy/me` | pharmacist (any status) | → `{…PharmacyState, license_number, phone, address, district, pickup_days, hours}` | | SM-1 |
| `PATCH /pharmacy/me/registration` | PENDING / REJECTED | `{name?, license_number?, phone?, address?, district_id?, hours?, pickup_days?}` → profile | `LICENSE_TAKEN`, `PHONE_TAKEN` | PS-2 |
| `POST /pharmacy/me/resubmit` | REJECTED | → profile (PENDING) | | SM-1 |
| `PATCH /pharmacy/me` | APPROVED | `{phone?, hours?, pickup_days? (1–3)}` → profile (existing deadlines unchanged) | `VALIDATION_ERROR` | R-T5, N-6 |
| `GET /pharmacy/dashboard` | APPROVED / SUSPENDED | → `{new_reservations, due_today, open_asks, live_listings, units_reserved, last_inventory_update, stale}` | | PS-3 |
| `GET /pharmacy/reservations?view=active\|history&q=R-1042&cursor=` | APPROVED / SUSPENDED | → page of `{id, ref, product, batch, expiry_date, qty, price_each, total, deadline, prescription_required, state, status_text, is_new, created_at}`. **No client identity** (INV-9). `is_new` = reserved in the last 24 h and still RESERVED. | | PS-4 |
| `POST /pharmacy/reservations/{id}/picked-up` | APPROVED / SUSPENDED (own) | → reservation (PICKED_UP) | `RESERVATION_NOT_ACTIVE` ("already picked up"), `PICKUP_DEADLINE_PASSED` | O2, INV-7 |
| `POST /pharmacy/reservations/{id}/not-available` | APPROVED / SUSPENDED (own) | `{units}` → reservation (still RESERVED with fewer units, or NOT_AVAILABLE) | `UNITS_INVALID`, `RESERVATION_NOT_ACTIVE` | O3 |
| `GET /pharmacy/inventory/template` | APPROVED | → `text/csv` with the template columns | | SM-4 |
| `POST /pharmacy/inventory/uploads` 🔑 | APPROVED | multipart `file` (CSV/XLSX) → **201** `{id, status: "VALIDATED", rows_total, rows_ok, rows_error, summary: {new, changed, zeroed, reserved_kept}, errors: list[{row, column, problem, did_you_mean}]}` (first 500) | `UPLOAD_FAILED`, `FILE_TOO_LARGE` | SM-4, R-U5, R-C9 |
| `GET /pharmacy/inventory/uploads/{id}/errors.csv` | APPROVED (own) | → all row errors as CSV | `NOT_FOUND` | PS-6 |
| `POST /pharmacy/inventory/uploads/{id}/apply` | APPROVED (own) | → `{applied: summary, warnings}`; matching runs | `UPLOAD_NOT_VALIDATED` | SM-4, R-U1–R-U4 |
| `POST /pharmacy/inventory/uploads/{id}/discard` | APPROVED (own) | → **204** | `UPLOAD_NOT_VALIDATED` | SM-4 |
| `GET /pharmacy/inventory?q=&zone=&cursor=` | APPROVED | → page of `{id, product, batch, expiry_date, days_left, zone, qty_on_hand, qty_reserved, qty_available, listing_control, price: {effective, system, override}}` | | PS-6 |
| `POST /pharmacy/inventory/items` 🔑 | APPROVED | `{product_id, batch, expiry_date, qty}` → **201** item; matching runs | `ITEM_EXISTS`, `PRODUCT_NOT_ALLOWED` | PS-6 |
| `PATCH /pharmacy/inventory/items/{id}` | APPROVED (own) | `{qty_on_hand}` (quick edit after a shop sale) → item + `warnings: [{code: "RESERVED_PROTECTED", kept}]` if set below reserved | `VALIDATION_ERROR` | R-U3 |
| `GET /pharmacy/listings?cursor=` | APPROVED | → live items (NEAR_EXPIRY) with price and discount | | PS-7 |
| `PATCH /pharmacy/listings/{id}` | APPROVED (own) | `{price_override_lbp?: int \| null, paused?: bool}` → listing; resuming or lowering the price runs matching | `PRICE_ABOVE_PUBLIC` | R-PR1, R-PRI1 |
| `GET /pharmacy/early-release-asks?view=open\|history` | APPROVED | → `list[{id, product, qty_needed, private_item: {batch, expiry_date, qty_available}, public_price, suggested_price, respond_by, state}]`. The "need" is described without any client identity. | | PS-9, R-E8 |
| `POST /pharmacy/early-release-asks/{id}/accept` | APPROVED (own) | `{qty, price_lbp}` → `{state: "ACCEPTED"}`, **or** `{state: "WITHDRAWN", message: "Thank you, this need was just met"}` if the need was covered meanwhile (nothing locked) | `ASK_NOT_OPEN`, `PRICE_ABOVE_PUBLIC`, `UNITS_INVALID` | R-E6, O8 |
| `POST /pharmacy/early-release-asks/{id}/decline` | APPROVED (own) | `{reason: "not_available" \| "keeping_for_customers" \| "other"}` → **204**. **A code only, no free text** (R-AG8). | `ASK_NOT_OPEN` | R-E6 |

### 6.10 Admin

| Method · Path | Request → Response | Errors | Rule |
|---|---|---|---|
| `GET /admin/overview` | → counts needing attention + 7-day agent and marketplace metrics | | AS-2 |
| `GET /admin/pharmacies?status=&q=&cursor=` · `GET /admin/pharmacies/{id}` | → list / detail with automatic checks (duplicate license, phone, email, address) | | AS-3, AS-4 |
| `POST /admin/pharmacies/{id}/approve` · `/reject {reason}` · `/request-info {message}` · `/suspend {reason}` · `/reinstate {reason}` | → pharmacy | `REASON_REQUIRED` | SM-1 |
| `PATCH /admin/pharmacies/{id}` | `{name?, license_number?, address?, district_id?}` → pharmacy (audited) | `LICENSE_TAKEN` | SM-1 |
| `GET /admin/clients?q=&status=&cursor=` | → list **without contact details** (status, district, reservations, no-shows, open requests) | | AS-5 |
| `GET /admin/clients/{id}/contact` | → `{full_name, email, phone}`; **logged as `pii.view`** | | A-D3 |
| `POST /admin/clients/{id}/lift-pause` · `/suspend` · `/reinstate` | `{reason}` → client state; suspending revokes sessions | `REASON_REQUIRED` | SM-2 |
| `GET /admin/escalations?state=` · `GET /admin/escalations/{id}` | → list / detail (summary, appended notes, request ref, **redacted** conversation, trace link) | | AS-6 |
| `POST /admin/escalations/{id}/take` · `/reply {text ≤ 500}` · `/resolve {note}` | → escalation; the reply becomes an `admin` message + CN-14. **No priority endpoint exists** (R-PRI4). | `VALIDATION_ERROR` | SM-9 |
| `GET /admin/abuse-flags?state=` · `POST /admin/abuse-flags/{id}/dismiss\|warn\|suspend {reason}` | → flag | `REASON_REQUIRED` | SM-11 |
| `GET /admin/answer-reports?state=` · `GET /admin/answer-reports/{id}` | → report with the redacted snapshot and trace link | | AS-8 |
| `POST /admin/answer-reports/{id}/dismiss` · `/confirm {category, add_to_regression}` | → report | | SM-10 |
| `GET /admin/answer-reports/export` | → JSON regression cases (redacted) for `tests/regression/` | | A-D6 |
| `GET /admin/catalog/products?q=` · `GET /admin/catalog/imports` | → read-only catalog with flags, groups and source | | AS-9 |
| `GET /admin/health` | → agent metrics (turns, latency p50/p95, errors, fallbacks, tokens, cost, fulfilled within window, re-plans, early-release success, guardrail triggers, model, prompt version) + system metrics (clock-check delay, pending turns, email failures, [Not available] rate) | | AS-10, C14 |
| `GET /admin/audit?entity_type=&entity_id=&actor=&from=&to=&cursor=` | → audit events (IDs and states only) | | AS-11 |
| `GET /admin/demo-clock` · `POST /admin/demo-clock/advance {seconds}` · `POST /admin/demo-clock/reset` | → `{now, offset_seconds}` (audited) | `DEMO_MODE_OFF` | R-DEMO |

Every admin endpoint requires role `admin`, and every state change records an audit event with the admin's ID and reason.

---

## 7. Worked examples

### 7.1 Search → reserve → pickup
```http
POST /api/v1/reservations
Idempotency-Key: 5b1e…
{"listing_id": "a3f…", "qty": 1, "expected_price_lbp": 716000}

201 Created
{"id": "e91…", "ref": "R-001042", "state": "RESERVED",
 "status_text": "Reserved: pick up by Tue 21:00",
 "qty": 1, "price_each": {"lbp": 716000, "usd_approx": 8.0},
 "deadline": "2026-10-20T19:00:00Z", "source": "search", …}
```
At the counter, the pharmacist searches `R-1042` and calls `POST /pharmacy/reservations/e91…/picked-up`.

### 7.2 Two clients tap the last box at the same moment
Both send `POST /reservations` for the same listing. The database lock lets one through (`05` §6):
- Client 1 → `201 Reserved`.
- Client 2 → `409 {"error": {"code": "NOT_ENOUGH_STOCK", "message": "Someone reserved this a moment ago.", "details": {"available": 0}}}`.

### 7.3 A plan card fails at tap time
```http
POST /api/v1/proposals/7c2…/execute
Idempotency-Key: 0d9…
{"selected_item_keys": ["concor", "aspirin"]}

409 Conflict
{"error": {"code": "GROUP_ITEM_FAILED",
  "message": "Aspirin was just taken at Pharmacy A, so nothing was reserved yet.",
  "details": {"failed_items": [{"item_key": "aspirin", "code": "NOT_ENOUGH_STOCK"}]}}}
```
The server also queues an agent turn. A few seconds later, the next poll returns a new plan card: "Reserve Concor ×2 alone?".

### 7.4 A chat message
```http
POST /api/v1/conversations/c41…/messages
{"text": "baddi augmentin 1g, ma fiye edfa3 aktar men 10$", "client_message_id": "9aa…"}

event: turn_started   data: {"turn_id": "t-88", "client_message_seq": 12}
event: progress       data: {"label": "Searching…"}
event: message        data: {"seq": 13, "author": "agent", "kind": "card",
                             "text": "La2ayt 2 options taht l 10$:", "cards": [{"card_id": "p-1", "origin": "proposal", "type": "option", …}], …}
event: turn_completed data: {"agent_message_seq": 13, "outcome": "ok"}
```

### 7.5 The pharmacy marks a request's reservation "not available"
`POST /pharmacy/reservations/{id}/not-available {"units": 1}` triggers this, in one transaction:
1. stock is corrected;
2. the request item gets 1 unit back;
3. an `event` message is written to the request thread, and `pending_turn_at` is set.

Within seconds, the clock check runs the agent turn. The client's request page, which is polling, then shows the new plan or "asking pharmacies".

---

## 8. Interfaces between components (besides HTTP)

| Interface | Between | Contract |
|---|---|---|
| **Services** | API routers **and** agent tools → `services/` | The same Python functions do reservations, requests, watches and matching for both. Tools never call HTTP. That's why a tap and a tool can't disagree. |
| **Proposals** | agent tools → `proposals` table → API → browser | One stored row per agent card. Its `payload` per kind:<br>• `reserve`: `{listing_id, qty, price_lbp_shown}`<br>• `reserve_group`: `{pharmacy_id, items: [{item_key, listing_id, qty, price_lbp_shown, request_item_id?}]}`<br>• `accept_offer`: `{offer_id}`<br>• `cancel`: `{order_id}`<br>• `request_summary`: `{items, district_id, alternatives_ok, max_prices}`<br>• `constraint_change`: `{request_id, alternatives_ok? \| item_max_prices?}`<br>• `remove_item`: `{request_id, request_item_id}`<br>The card's text is rendered from this payload. |
| **Deadlines on rows** | services (writer) → worker clock check (reader) | `orders.offer_expires_at` / `deadline`, `sourcing_requests.ends_at` / `window_checked_at`, `claims.ends_at`, `early_release_asks.respond_by`, `email_outbox.next_attempt_at` (`04` R-T10, `05` §3.8) |
| **Decision events** | services → agent | A `chat_messages` row with `kind = "event"`, a JSON body `{type, ids…}` (types: `not_available`, `system_cancelled`, `early_release_unfulfilled`, `window_check`, `group_item_failed`, `items_unticked`, `request_submitted`), and `conversations.pending_turn_at = now` (`04` R-AG4) |
| **Turn lease** | API and worker | `conversations.turn_lease_until` / `turn_owner` (`05` §6). The API answers `CONVERSATION_BUSY` while it's held. |
| **Email** | services → `email_outbox` → worker → SES | `{template: "CN-3" \| …, user_id, params}`. The address is resolved at send time; params hold display values and IDs only. |
| **Clock** | everything | `clock.now()` (UTC, + the demo offset in demo mode) and `clock.today()` (Beirut date). Never `datetime.now()` in domain code (`04` R-T11). |
| **Agent ↔ LLM; tool schemas; guards; traces** | agent | Defined in `07` |

---

## 9. OpenAPI, versioning and contract tests

- **Generated, not hand-written:**
  - FastAPI builds the OpenAPI spec from the Pydantic schemas;
  - CI exports it to `docs/openapi.json` (deliverable D-6), and the frontend's TypeScript types are generated from it;
  - a PR whose code doesn't match the committed spec fails CI.
- **Interactive docs** (`/api/v1/docs`) are enabled **only in development**. The JSON spec is always available at `/api/v1/openapi.json`.
- **Versioning:** `/api/v1` until a breaking change. Additive changes (new optional fields, new endpoints) keep `v1`.
- **Contract tests** (`tests/api/`, checklist T-13 and bonus B-8):
  1. **Every endpoint has at least three tests:** a valid call, an invalid payload (→ `422`), and an unauthorized call (wrong role, another user's object → `403`/`404`). This is Definition of Done item #2.
  2. **Every error code** in §3.2 has a test that triggers it.
  3. **Schemathesis** runs in CI against the OpenAPI spec. It generates many random valid and invalid requests and checks that the API never returns a `500` and always matches its own schema.

---

## 10. Traceability

| Requirement | Where it's met here |
|---|---|
| Schemas | §5 (Pydantic), generated OpenAPI (§9) |
| Validation | Pydantic on every input; `422 VALIDATION_ERROR` with field details (§3.1) |
| Authentication | Server-side sessions, `SameSite=Strict` + `Origin` check (§2.1) |
| Authorization and least privilege | Role, status and ownership on every endpoint; `404` for others' objects (§2.2); no priority endpoint at all |
| Error behavior | One format, a stable code catalog mapped to the rules (§3) |
| Human approval for consequential actions | Every reservation, acceptance, request and change is a client call; the agent has no HTTP access, and its cards are re-validated (§6.7) |
| Rate limits | §4 |
| Interfaces between components | §8 |

---

## 11. Decisions

| ID | Decision | Validated | Why |
|---|---|---|---|
| API-D1 | **REST + JSON under `/api/v1`**; agent tools call the services in-process, not HTTP | ✅ 2026-10-18 | Simple, standard, and the agent and taps share one code path |
| API-D2 | **One error format with stable codes; someone else's object returns `404`** | ✅ 2026-10-18 | The frontend and tests rely on codes; IDs can't be probed |
| API-D3 | **Three button paths:** search → `/reservations`; agent cards → `/proposals/{id}/execute`; system cards → the object's endpoint. Proposals expire after 2 h and are single-use. | ✅ 2026-10-18 | What you see is what you get, and search never involves the agent (clean baseline) |
| API-D4 | **Price protection:** the tap sends the price shown; if it went up → `PRICE_CHANGED`, nothing reserved | ✅ 2026-10-18 | Prices can change at midnight (tiers) or by override; the client never pays more than what was shown |
| API-D5 | **`Idempotency-Key` on every creating tap**; a group stores one key per order (`<key>:<position>`) | ✅ 2026-10-18 | Double taps and retries never create duplicates. *(Aligns the wording in `05` §3.4: the client sends one header, and the server derives the per-order keys.)* |
| API-D6 | **Chat replies arrive whole, after the output check** (progress events while working; no word-by-word streaming) | ✅ 2026-10-18 | Otherwise a blocked sentence could already be on screen |
| API-D7 | **Polling every 3 s** for new messages and cards while a chat or request page is open | ✅ 2026-10-18 | Simple and reliable; works for worker turns and system cards |
| API-D8 | **Busy conversation → `409 CONVERSATION_BUSY`**, and the UI retries automatically | ✅ 2026-10-18 | One turn at a time (R-AG2) without the user noticing |
| API-D9 | **Availability is capped at 5** in responses (+ a "more" flag) | ✅ 2026-10-18 | R-S5, and exact stock levels can't be scraped |
| API-D10 | **Money:** integer LBP + `usd_approx` out; LBP or USD in, converted on the server | ✅ 2026-10-18 | One conversion rule (R-C3) |
| API-D11 | **Internal `event` messages are never shown to clients**; pharmacies' decline reasons are **codes only** | ✅ 2026-10-18 | Clean UI; no pharmacy text can reach the agent (R-AG8) |
| API-D12 | **CSRF:** `SameSite=Strict` cookie + `Origin` check on every state-changing request | ✅ 2026-10-18 | Two simple layers |
| API-D13 | **OpenAPI generated and exported to `docs/openapi.json` in CI**; interactive docs only in development; contract tests (3 per endpoint + every error code + Schemathesis) | ✅ 2026-10-18 | Deliverable D-6, T-13, bonus B-8 |
| API-D14 | **New numbers** to add to `04` §5: polling 3 s · API rate limit 120 per minute per session · proposal validity 2 h · max page size 50 | ✅ 2026-10-18 | Numbers live only in `04` §5 |

**Applied on validation (2026-10-18):**
- the API-D14 numbers are in `04` §5 (N-28–N-31);
- `02` §5 and `05` §3.4 / §3.6 are aligned;
- API-D1–API-D14 are recorded in the decision log (§O).
