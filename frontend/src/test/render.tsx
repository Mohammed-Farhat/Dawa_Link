import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import axe from 'axe-core'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { type Schemas, setToken } from '../api/client'
import { SessionProvider } from '../api/SessionProvider'
import { theme } from '../theme/theme'

/** Renders a screen inside the same providers the real app uses. */
export function renderApp(ui: ReactNode, { path = '/' }: { path?: string } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MantineProvider theme={theme} forceColorScheme="light">
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
        </SessionProvider>
      </QueryClientProvider>
    </MantineProvider>,
  )
}

/** The accessibility problems axe finds in a rendered screen (docs/11 §9). */
export async function accessibilityProblems(container: HTMLElement): Promise<string[]> {
  const results = await axe.run(container, {
    // jsdom doesn't lay out or paint, so color contrast can't be computed here.
    rules: { 'color-contrast': { enabled: false } },
  })
  return results.violations.map((violation) => `${violation.id}: ${violation.help}`)
}

/** Makes the next API calls answer with this JSON body. */
export function apiAnswers(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
}

export function apiIsUnreachable() {
  return vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
}

// --- A pretend API ------------------------------------------------------------------------

export type Call = { method: string; path: string; body: unknown; headers: Headers }
type Answer = unknown | ((call: Call) => unknown)

/** An answer with a status other than 200, or the API's error format. */
export function answer(status: number, body: unknown = null) {
  return { __status: status, body }
}

export function refusal(status: number, code: string, details: Record<string, unknown> = {}) {
  return answer(status, { error: { code, message: code, details, request_id: 'test' } })
}

/** A chat stream: the events, written as the API writes them (docs/06 §6.6.1). */
export function stream(...events: [name: string, data: unknown][]) {
  return {
    __stream: events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join(''),
  }
}

/**
 * A pretend API for one test: `{ 'GET /api/v1/auth/me': {...} }`.
 *
 * A path may end with `*` to answer every address that starts with it. An address no
 * route knows answers 404, and every call is kept in `calls`, so a test can check what
 * the website sent.
 */
export function pretendApi(routes: Record<string, Answer>) {
  const calls: Call[] = []
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const request = input instanceof Request ? input : new Request(String(input), init)
    const url = new URL(request.url)
    const text = request.method === 'GET' ? '' : await request.clone().text()
    // A file is sent as a form, not as JSON: its text is kept as it is.
    const isJson = (request.headers.get('Content-Type') ?? '').includes('json')
    const call: Call = {
      method: request.method,
      path: url.pathname + url.search,
      body: text ? (isJson ? JSON.parse(text) : text) : null,
      headers: request.headers,
    }
    calls.push(call)
    const exact = `${call.method} ${url.pathname}`
    const key =
      exact in routes
        ? exact
        : Object.keys(routes).find((route) => route.endsWith('*') && exact.startsWith(route.slice(0, -1)))
    if (key === undefined) {
      return new Response(JSON.stringify(refusal(404, 'NOT_FOUND').body), { status: 404 })
    }
    const route = routes[key]
    const found = (typeof route === 'function' ? route(call) : route) as
      | { __status?: number; body?: unknown; __stream?: string }
      | undefined
    if (found && typeof found === 'object' && '__stream' in found) {
      return new Response(found.__stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }
    if (found && typeof found === 'object' && '__status' in found) {
      const status = found.__status ?? 200
      return new Response(status === 204 ? null : JSON.stringify(found.body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify(found), { headers: { 'Content-Type': 'application/json' } })
  })
  return { calls, spy, sent: (method: string, path: string) => calls.filter((c) => c.method === method && c.path.startsWith(path)) }
}

/** As if someone had logged in before the test started. */
export function loggedIn() {
  setToken('a-test-token')
}

// --- Things the pretend API answers with --------------------------------------------------

export const CLIENT = {
  id: '11111111-1111-4111-8111-111111111111',
  role: 'client',
  email: 'nour@example.com',
  full_name: 'Nour Khoury',
  email_verified: true,
  client: {
    status: 'ACTIVE',
    paused_until: null,
    district: { id: 1, name: 'Beirut', governorate: 'Beirut', lat: 33.8938, lon: 35.5018 },
    alternatives_ok_default: false,
    missed_pickups_30d: 0,
    missed_pickups_before_pause: 2,
  },
  pharmacy: null,
} satisfies Schemas['Me']

export const CONFIG = {
  request_hours_start: '08:00',
  request_hours_end: '20:00',
  search_window_hours: 6,
  offer_hours: 2,
  lbp_per_usd: 89500,
  rate_date: '2026-11-01',
  poll_every_s: 3,
  max_message_chars: 1000,
  discount_tiers: [
    { min_days: 0, max_days: 30, discount_pct: 60 },
    { min_days: 31, max_days: 90, discount_pct: 40 },
    { min_days: 91, max_days: 180, discount_pct: 25 },
  ],
  server_now: '2026-11-16T08:00:00Z',
  demo_mode: true,
  assistant_available: true,
} satisfies Schemas['PublicConfig']

export const DISTRICTS = [
  { id: 1, name: 'Beirut', governorate: 'Beirut', lat: 33.8938, lon: 35.5018 },
  { id: 2, name: 'Matn', governorate: 'Mount Lebanon', lat: 33.89, lon: 35.63 },
] satisfies Schemas['District'][]

const money = (lbp: number) => ({ lbp, usd_approx: Math.round((lbp / 89500) * 100) / 100 })

export const RESERVATION = {
  id: '22222222-2222-4222-8222-222222222222',
  ref: 'R-7K3Q2F',
  state: 'RESERVED',
  status_text: 'Reserved: pick up by today 21:00',
  product: {
    id: '33333333-3333-4333-8333-333333333333',
    name: 'AUGMENTIN 1G',
    strength: '1 g',
    form: 'tablet',
    pack: '14 tablets',
    prescription_required: true,
    public_price: money(1_000_000),
  },
  pharmacy: {
    id: '44444444-4444-4444-8444-444444444444',
    name: 'Hamra Pharmacy',
    district: 'Beirut',
    governorate: 'Beirut',
    address: '12 Hamra Street',
    phone: '+961 1 000 000',
    open_now: true,
    closes_at: '2026-11-16T19:00:00Z',
    pickup_days: 1,
    pin: { lat: 33.897, lon: 35.484 },
  },
  qty: 1,
  qty_requested: 1,
  price_each: money(600_000),
  total: money(600_000),
  saving: money(400_000),
  pickup_day: '2026-11-16',
  deadline: '2026-11-16T19:00:00Z',
  expiry_date: '2027-01-15',
  source: 'assistant',
  request_id: null,
  created_at: '2026-11-16T08:00:00Z',
  closed_at: null,
  contestable: false,
  server_now: '2026-11-16T08:00:00Z',
} satisfies Schemas['Reservation']

export const CHAT_ID = '55555555-5555-4555-8555-555555555555'
export const CARD_ID = '66666666-6666-4666-8666-666666666666'

export const RESERVE_CARD = {
  card_id: CARD_ID,
  origin: 'proposal',
  type: 'reserve',
  title: 'AUGMENTIN 1G at Hamra Pharmacy',
  lines: [
    { label: 'Pharmacy', value: 'Hamra Pharmacy, Beirut' },
    { label: 'At the counter', value: '600,000 LBP (about $6.70)' },
  ],
  prescription_notice: true,
  recommended: true,
  state: 'open',
  expires_at: '2026-11-16T10:00:00Z',
  action_label: 'Reserve',
  selectable_items: [],
  call_number: null,
  data: {},
} satisfies Schemas['Card']

export function message(seq: number, author: string, text: string | null, more: object = {}) {
  return {
    seq,
    author,
    kind: text === null ? 'card' : 'text',
    text,
    cards: [],
    quick_replies: [],
    reportable: author === 'agent',
    created_at: '2026-11-16T08:00:00Z',
    ...more,
  }
}

export function page(messages: ReturnType<typeof message>[], more: object = {}) {
  return {
    conversation_id: CHAT_ID,
    kind: 'chat',
    request_id: null,
    messages,
    last_seq: messages.length ? messages[messages.length - 1].seq : 0,
    busy: false,
    location: { source: 'profile', label: 'Beirut' },
    server_now: '2026-11-16T08:00:00Z',
    ...more,
  }
}
