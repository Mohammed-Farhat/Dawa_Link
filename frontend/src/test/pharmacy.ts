import type { Schemas } from '../api/client'
import { CLIENT, CONFIG, RESERVATION } from './render'

// What the pretend API answers with on the pharmacy's side. Invented, like every fixture.

const NOW = CONFIG.server_now
const money = (lbp: number) => ({ lbp, usd_approx: Math.round((lbp / 89500) * 100) / 100 })

export const PHARMACIST = {
  ...CLIENT,
  role: 'pharmacist',
  client: null,
  full_name: 'Hamra Pharmacy',
} satisfies Schemas['Me']

export const PROFILE = {
  id: RESERVATION.pharmacy.id,
  name: 'Hamra Pharmacy',
  status: 'APPROVED',
  status_reason: null,
  info_requested: false,
  email_verified: true,
  address: '12 Hamra Street',
  district: 'Beirut',
  district_id: 1,
  phone: '+9611000000',
  license_number: 'TEST-1',
  location: { lat: 33.8959, lon: 35.4828 },
  pickup_days: 1,
  hours: [
    { weekday: 0, open: '08:00', close: '13:00' },
    { weekday: 0, open: '16:00', close: '21:00' },
    { weekday: 1, open: '08:00', close: '24:00' },
  ],
  auto_list_days: 180,
  auto_list_choices: [0, 30, 60, 90, 180],
  week: [{ day: '2026-11-16', hours: '08:00-21:00' }],
  open_now: true,
  closes_at: '2026-11-16T19:00:00Z',
  server_now: NOW,
} satisfies Schemas['PharmacyProfile']

export const BOX = {
  id: '99999999-9999-4999-8999-999999999999',
  product: RESERVATION.product,
  batch: 'A123',
  expiry_date: '2026-12-06',
  days_left: 20,
  zone: 'NEAR_EXPIRY',
  qty_on_hand: 5,
  qty_reserved: 2,
  qty_available: 3,
  paused: false,
  listed_by_hand: false,
  held_back: false,
  visible: true,
  price: { effective: money(400_000), system: money(400_000), override: null, discount_pct: 60 },
  last_edited_at: NOW,
} satisfies Schemas['StockItem']

export const PRIVATE_BOX = {
  ...BOX,
  id: 'aaaaaaaa-9999-4999-8999-999999999999',
  batch: 'Z9',
  expiry_date: '2027-06-04',
  days_left: 200,
  zone: 'EARLY_RELEASE',
  qty_reserved: 0,
  qty_available: 5,
  visible: false,
  price: { effective: null, system: null, override: null, discount_pct: null },
} satisfies Schemas['StockItem']

export const UPLOAD = {
  id: 'bbbbbbbb-9999-4999-8999-999999999999',
  status: 'VALIDATED',
  file_name: 'stock.csv',
  rows_total: 3,
  rows_ok: 2,
  rows_error: 1,
  summary: { new: 2, changed: 0, zeroed: 1, reserved_kept: 1, left_alone: 0 },
  errors: [
    { row: 3, product: 'Panadoll', problem: 'no product with this name', did_you_mean: ['PANADOL'] },
  ],
  created_at: NOW,
} satisfies Schemas['StockUpload']

export const stockOf = (items: Schemas['StockItem'][]) =>
  ({ items, next_cursor: null, total: items.length, server_now: NOW }) satisfies Schemas['Stock']
