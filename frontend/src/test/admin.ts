import type { Schemas } from '../api/client'
import { CLIENT } from './render'

// What the pretend API answers with on the admin's side. Invented, like every fixture.

export const ADMIN = {
  ...CLIENT,
  role: 'admin',
  client: null,
  full_name: 'An Admin',
} satisfies Schemas['Me']

export const OVERVIEW = {
  pharmacies_waiting: 1,
  pins_to_check: 0,
  escalations_open: 2,
  emergency_claims: 1,
  reports_new: 0,
  flags_open: 0,
  flags_high: 0,
  contests_waiting: 0,
  demo_mode: true,
} satisfies Schemas['AdminOverview']

export const PHARMACY_ID = 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa'

export const WAITING_ROW = {
  id: PHARMACY_ID,
  name: 'Hamra Pharmacy',
  status: 'PENDING',
  info_requested: false,
  pin_to_check: false,
  district: 'Beirut',
  license_number: 'PH1234',
  created_at: '2026-11-16T07:00:00Z',
  approved_at: null,
} satisfies Schemas['AdminPharmacyRow']

export const WAITING = {
  ...WAITING_ROW,
  status_reason: null,
  email: 'owner@hamra.example.com',
  phone: '+9611234567',
  address: '12 Hamra Street',
  district_id: 1,
  location: { lat: 33.8959, lon: 35.4828 },
  pin_checked: false,
  pickup_days: 1,
  hours: [
    { weekday: 0, open: '08:00', close: '13:00' },
    { weekday: 0, open: '16:00', close: '21:00' },
  ],
  version: 'version-1',
  same_address: [],
  phone_changed_at: null,
  moved_at: null,
  live_listings: 0,
  last_inventory_update: null,
  handed_over_30d: 0,
  not_available_30d: 0,
} satisfies Schemas['AdminPharmacy']

export const ESCALATION_ID = 'bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb'

export const ESCALATION = {
  id: ESCALATION_ID,
  client_id: CLIENT.id,
  reason: 'emergency_claim',
  state: 'OPEN',
  summary: 'Client says the need is urgent; Glucophage 850 still missing.',
  request_ref: 'Q-6BN2RA',
  notes: [],
  created_at: '2026-11-16T07:40:00Z',
  resolved_at: null,
  resolution_note: null,
  reasons: ['emergency_claim'],
  last_summary: 'Client says the need is urgent; Glucophage 850 still missing.',
  last_asked_at: '2026-11-16T07:40:00Z',
  last_replied_at: null,
  new_ask_since_reply: false,
  client_wrote_at: null,
  hold_ends_at: null,
} satisfies Schemas['EscalationRow']

export const ESCALATION_DETAIL = {
  escalation: ESCALATION,
  thread: [
    {
      seq: 1,
      author: 'client',
      text: 'I need it today, call me on [phone].',
      cards: [],
      created_at: '2026-11-16T07:38:00Z',
      starts_another_chat: false,
    },
    {
      seq: 2,
      author: 'agent',
      text: 'I asked a person from DawaLink to help you.',
      cards: ['reserve'],
      created_at: '2026-11-16T07:39:00Z',
      starts_another_chat: false,
    },
  ],
  contested: [],
} satisfies Schemas['EscalationDetail']

export const REPORT_ID = 'cccccccc-3333-4333-8333-cccccccccccc'

export const REPORT = {
  id: REPORT_ID,
  state: 'NEW',
  reason: 'unsafe',
  comment: 'It told me how much to take.',
  category: null,
  in_regression: false,
  reply: 'Take two tablets a day.',
  asked: 'How much Panadol can I take?',
  created_at: '2026-11-16T07:50:00Z',
} satisfies Schemas['AnswerReportRow']

export const AUDIT_EVENT = {
  id: 42,
  occurred_at: '2026-11-16T07:55:00Z',
  actor_type: 'ADMIN',
  actor_id: ADMIN.id,
  entity_type: 'pharmacy',
  entity_id: PHARMACY_ID,
  action: 'pharmacy.approve',
  known_action: 'pharmacy.approve',
  who: { kind: 'admin', name: 'Rania Admin', id: null },
  subject: { kind: 'pharmacy', id: PHARMACY_ID },
  changed: [],
  state_from: 'PENDING',
  state_to: 'APPROVED',
  counts: {},
  code: null,
  reason: null,
} satisfies Schemas['AuditRow']

export const CLIENT_ROW = {
  id: CLIENT.id,
  status: 'PAUSED',
  paused_until: '2026-11-20T08:00:00Z',
  district: 'Beirut',
  open_orders: 1,
  picked_up: 3,
  no_shows: 2,
  open_requests: 1,
  contested: 1,
  flags_open: 0,
} satisfies Schemas['AdminClientRow']

export const CONTESTED_ID = 'dddddddd-4444-4444-8444-dddddddddddd'

const RESERVED_LINE = {
  ref: 'R-2WAITS',
  product: 'CONCOR 5MG',
  pharmacy: 'Hamra Pharmacy',
  state: 'RESERVED',
  units: 1,
  created_at: '2026-11-16T07:10:00Z',
  deadline: '2026-11-16T18:00:00Z',
  closed_at: null,
  counts_as_no_show: false,
} satisfies Schemas['ClientReservation']

export const CLIENT_DETAIL = {
  client: CLIENT_ROW,
  reservations: [
    RESERVED_LINE,
    {
      ...RESERVED_LINE,
      ref: 'R-3TAKEN',
      product: 'PANADOL 500MG',
      state: 'PICKED_UP',
      units: 2,
      deadline: '2026-11-14T18:00:00Z',
      closed_at: '2026-11-14T10:00:00Z',
    },
    {
      ...RESERVED_LINE,
      ref: 'R-7K3Q2F',
      product: 'AUGMENTIN 1G',
      state: 'EXPIRED_NO_SHOW',
      deadline: '2026-11-15T19:00:00Z',
      closed_at: '2026-11-15T19:00:00Z',
      counts_as_no_show: true,
    },
  ],
  requests: [
    {
      ref: 'Q-6BN2RA',
      state: 'OPEN',
      outcome: null,
      medicines: 2,
      secured: 1,
      created_at: '2026-11-16T07:00:00Z',
      ends_at: '2026-11-16T13:00:00Z',
    },
  ],
  flags: [],
  contested: [
    {
      id: CONTESTED_ID,
      ref: 'R-7K3Q2F',
      product: 'AUGMENTIN 1G',
      pharmacy: 'Hamra Pharmacy',
      expired_at: '2026-11-15T19:00:00Z',
      contested_at: '2026-11-16T07:00:00Z',
      counts_as_no_show: true,
    },
  ],
} satisfies Schemas['AdminClient']

export const FLAG = {
  id: 'eeeeeeee-5555-4555-8555-eeeeeeeeeeee',
  subject_type: 'client',
  subject_id: CLIENT.id,
  rule: 'guardrail_repeat',
  severity: 'high',
  evidence: { triggers_24h: 3, run_id: 'run-1' },
  state: 'OPEN',
  action: null,
  created_at: '2026-11-16T07:00:00Z',
} satisfies Schemas['AbuseFlagRow']

export const CATALOG_ROW = {
  id: 'ffffffff-6666-4666-8666-ffffffffffff',
  code: 7500,
  name: 'LOCKEDOL 10MG',
  strength: '10mg',
  form: 'Tablet',
  pack: '30',
  manufacturer: 'Invented Labs',
  public_price_lbp: 450_000,
  prescription_required: true,
  controlled: true,
  same_medicine: 3,
} satisfies Schemas['CatalogProduct']

export const HEALTH = {
  days: 7,
  agent: {
    turns: 2310,
    latency_p50_ms: 2100,
    latency_p95_ms: 4200,
    errors: 18,
    error_rate: 0.008,
    fallbacks: 4,
    guardrail_blocked: 1,
    guardrail_triggers: 12,
    tokens_in: 900000,
    tokens_out: 60000,
    cost_usd: 3.1,
    tool_calls: 5200,
    tool_errors: 31,
    model: 'claude-haiku-5-5',
    prompt_version: 'v1.13',
    month_spend_usd: 12.4,
    month_budget_usd: 20,
    day_spend_usd: 0.35,
    day_budget_usd: 2,
    day_share_percent: 10,
    messages_per_day_per_client: 100,
    tokens_per_day_per_client: 3_000_000,
    clients_at_token_limit_today: 2,
    clients_at_message_limit_today: 1,
  },
  requests: {
    closed: 64,
    by_outcome: { FULFILLED: 45 },
    fulfilled_share: 0.71,
    replans: 80,
    replans_per_request: 1.6,
    early_release_asked: 21,
    early_release_accepted: 9,
    escalations_by_reason: { emergency_claim: 2 },
    cost_per_fulfilled_usd: 0.07,
  },
  marketplace: {
    reservations: 142,
    picked_up: 83,
    not_available: 4,
    no_shows: 6,
    picked_up_share: 0.83,
    not_available_share: 0.04,
    no_show_share: 0.06,
    units_saved: 131,
  },
  system: {
    clock_check_late_s: 0,
    turns_waiting: 0,
    oldest_turn_waiting_s: 0,
    turns_stuck: 0,
    emails_failed: 0,
    emails_dead_last_hour: 0,
  },
  alerts: [],
} satisfies Schemas['AdminHealth']
