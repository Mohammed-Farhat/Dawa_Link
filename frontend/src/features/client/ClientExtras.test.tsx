import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Schemas } from '../../api/client'
import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
import { PHARMACIST, PROFILE } from '../../test/pharmacy'
import {
  accessibilityProblems,
  answer,
  CHAT_ID,
  CLIENT,
  CONFIG,
  DISTRICTS,
  loggedIn,
  message,
  page,
  pretendApi,
  refusal,
  renderApp,
  RESERVATION,
} from '../../test/render'

// The real map needs a browser that draws. Here it is a button that puts the pin.
vi.mock('../pharmacy/PinMap', () => ({
  default: ({ onChange }: { onChange: (pin: { lat: number; lon: number }) => void }) => (
    <button type="button" onClick={() => onChange({ lat: 33.8959, lon: 35.4828 })}>
      put the pin
    </button>
  ),
}))

const s = strings.search
const PRODUCT = RESERVATION.product

const WATCH = {
  id: 'aaaaaaaa-7777-4777-8777-aaaaaaaaaaaa',
  product: PRODUCT,
  qty: 1,
  qty_missing: 1,
  days_of_use: 1,
  max_price: { lbp: 900_000, usd_approx: 10.06 },
  state: 'ACTIVE',
  district: 'Beirut',
  ends_at: '2026-11-16T14:00:00Z',
  created_at: '2026-11-16T08:00:00Z',
} satisfies Schemas['Watch']

const NOTE = {
  id: 7,
  type: 'CN-3',
  title: 'Reserved: R-7K3Q2F',
  lines: ['Order number: R-7K3Q2F', 'Medicine: AUGMENTIN 1G'],
  link: `/reservations/${RESERVATION.id}`,
  read: false,
  created_at: '2026-11-16T07:30:00Z',
} satisfies Schemas['NotificationOut']

function nothingFound(more: object = {}) {
  return {
    product: PRODUCT,
    items: [],
    total_found: 0,
    left_out_by_pickup_day: 0,
    no_match: null,
    next_cursor: null,
    location: { source: 'profile', label: 'Beirut' },
    upcoming_days: ['2026-11-16', '2026-11-17', '2026-11-18'],
    server_now: CONFIG.server_now,
    ...more,
  }
}

function clientApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/catalog/products': { items: [PRODUCT], did_you_mean: [] },
    'POST /api/v1/listings/search': nothingFound(),
    'GET /api/v1/watches': { items: [], server_now: CONFIG.server_now },
    'GET /api/v1/reservations': { items: [], next_cursor: null, server_now: CONFIG.server_now },
    'GET /api/v1/notifications/unread-count': { count: 1 },
    'GET /api/v1/notifications': { items: [NOTE], next_cursor: null, unread: 1 },
    ...more,
  })
}

describe('[Notify me] on a search that found nothing (CS-6)', () => {
  it('starts a 6-hour watch with a price limit, from where the search looked', async () => {
    const api = clientApi({ 'POST /api/v1/watches': answer(201, WATCH) })
    const { container } = renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    // Both ways on are offered: ask the assistant, or be told when it appears.
    expect(await screen.findByRole('button', { name: s.askToFind })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: s.notify.button }))
    expect(await accessibilityProblems(container)).toEqual([])
    await user.type(screen.getByLabelText(s.notify.maxPrice), '900000')
    await user.click(screen.getByRole('button', { name: s.notify.start }))

    expect(await screen.findByText(/We watch for it until/)).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/watches')[0].body).toEqual({
      product_id: PRODUCT.id,
      qty: 1,
      days_of_use: 1,
      max_price: { amount: '900000', currency: 'LBP' },
      // The profile's district: nothing about a place is sent.
      location: null,
    })
    expect(screen.queryByRole('button', { name: s.notify.button })).not.toBeInTheDocument()
  })

  it('says so at night, and treats a second ask as done', async () => {
    const api = clientApi({ 'POST /api/v1/watches': refusal(409, 'OUTSIDE_REQUEST_HOURS') })
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: s.notify.button }))
    await user.click(screen.getByRole('button', { name: s.notify.start }))
    expect(await screen.findByText(strings.errors.OUTSIDE_REQUEST_HOURS)).toBeInTheDocument()

    api.spy.mockRestore()
    clientApi({ 'POST /api/v1/watches': refusal(409, 'WATCH_EXISTS') })
    await user.click(screen.getByRole('button', { name: s.notify.start }))
    expect(await screen.findByText(s.notify.already)).toBeInTheDocument()
  })

  it('sends the price limit with a search', async () => {
    const api = clientApi()
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.maxPrice), '500000')

    await waitFor(() => {
      const sent = api.sent('POST', '/api/v1/listings/search').map((call) => call.body as { max_price: unknown })
      expect(sent[sent.length - 1].max_price).toEqual({ amount: '500000', currency: 'LBP' })
    })
  })
})

describe('Watches in My medicines (CS-11)', () => {
  it('lists what is watched and stops one', async () => {
    const api = clientApi({
      'GET /api/v1/watches': { items: [WATCH], server_now: CONFIG.server_now },
      [`POST /api/v1/watches/${WATCH.id}/cancel`]: { ...WATCH, state: 'CANCELLED' },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/medicines' })
    const user = userEvent.setup()
    const m = strings.medicines

    const watching = await screen.findByRole('region', { name: m.watchingTitle })
    expect(within(watching).getByText(/AUGMENTIN 1G × 1/)).toBeInTheDocument()
    expect(within(watching).getByText(/around Beirut · up to 900,000 LBP/)).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(within(watching).getByRole('button', { name: m.stopWatching }))

    await waitFor(() => expect(api.sent('POST', `/api/v1/watches/${WATCH.id}/cancel`)).toHaveLength(1))
  })

  it('sends the client to the offer when a pharmacy has it', async () => {
    clientApi({ 'GET /api/v1/watches': { items: [{ ...WATCH, state: 'OFFER_PENDING' }], server_now: CONFIG.server_now } })
    renderApp(<AppRoutes />, { path: '/medicines' })

    expect(await screen.findByRole('link', { name: strings.medicines.seeOffer })).toHaveAttribute('href', '/')
  })
})

describe('Notifications and the profile (CS-12, CS-13)', () => {
  it('lists what happened, marks a tapped one as read, and marks all', async () => {
    const api = clientApi({ 'POST /api/v1/notifications/read': answer(204) })
    const { container } = renderApp(<AppRoutes />, { path: '/notifications' })
    const user = userEvent.setup()
    const n = strings.notifications

    expect(await screen.findByText('Reserved: R-7K3Q2F')).toBeInTheDocument()
    expect(screen.getByText('Order number: R-7K3Q2F')).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(screen.getByRole('button', { name: n.markAll }))
    await waitFor(() =>
      expect(api.sent('POST', '/api/v1/notifications/read')[0].body).toEqual({ ids: [], all: true }),
    )

    await user.click(screen.getByRole('link', { name: /Reserved: R-7K3Q2F/ }))
    await waitFor(() =>
      expect(api.sent('POST', '/api/v1/notifications/read')[1].body).toEqual({ ids: [7], all: false }),
    )
  })

  it('is reached from Me, where the profile is edited', async () => {
    const api = clientApi({ 'PATCH /api/v1/me/profile': { ...CLIENT, phone: '70 123 456' } })
    const { container } = renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()
    const m = strings.me

    expect(await screen.findByText(strings.notifications.count(1))).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.type(screen.getByLabelText(new RegExp(`^${m.phone.replace(/[()]/g, '\\$&')}`)), '70 123 456')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: m.save }))

    expect(await screen.findByText(m.saved)).toBeInTheDocument()
    expect(api.sent('PATCH', '/api/v1/me/profile')[0].body).toEqual({
      phone: '70 123 456',
      district_id: 1,
      alternatives_ok_default: true,
    })
  })

  it("lists a pharmacy's own notifications in its portal (PS-11)", async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': PHARMACIST,
      'GET /api/v1/config/public': CONFIG,
      'GET /api/v1/pharmacy/me': PROFILE,
      'GET /api/v1/notifications': {
        items: [{ ...NOTE, type: 'PN-4', title: 'New reservation R-7K3Q2F: put the box aside', link: '/pharmacy/reservations' }],
        next_cursor: null,
        unread: 1,
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/notifications' })

    expect(await screen.findByText('New reservation R-7K3Q2F: put the box aside')).toBeInTheDocument()
  })
})

describe('"Pick on the map" (BLD-D16)', () => {
  it('sends the pin like a shared location, in a body and nowhere else', async () => {
    const api = clientApi({
      'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
      [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([]),
      [`PUT /api/v1/conversations/${CHAT_ID}/location`]: answer(204),
    })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()
    const l = strings.chat.location

    await user.click(await screen.findByRole('button', { name: l.button(l.home('Beirut')) }))
    await user.click(await screen.findByRole('button', { name: l.pickOnMap }))
    const use = await screen.findByRole('button', { name: l.usePin })
    // No pin yet: nothing to use.
    expect(use).toBeDisabled()
    await user.click(await screen.findByRole('button', { name: 'put the pin' }))
    await user.click(use)

    await waitFor(() => expect(api.sent('PUT', `/api/v1/conversations/${CHAT_ID}/location`)).toHaveLength(1))
    expect(api.sent('PUT', `/api/v1/conversations/${CHAT_ID}/location`)[0].body).toEqual({
      lat: 33.8959,
      lon: 35.4828,
    })
    // Never in an address or in the browser's storage.
    expect(api.calls.some((call) => call.path.includes('33.89'))).toBe(false)
    expect(JSON.stringify({ ...window.localStorage }) + window.location.href).not.toContain('33.89')
  })
})

describe("The chat's banners", () => {
  it('says at night that new requests wait for the morning, by the server clock', async () => {
    clientApi({
      'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
      // 22:00 in Beirut, whatever this computer's clock says.
      [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([message(1, 'agent', 'Hello.')], {
        server_now: '2026-11-16T20:00:00Z',
      }),
    })
    renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText(strings.banner.night('08:00'))).toBeInTheDocument()
  })

  it('says while reservations are paused, and nothing in the daytime otherwise', async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': { ...CLIENT, client: { ...CLIENT.client, status: 'PAUSED', paused_until: '2026-11-20T08:00:00Z' } },
      'GET /api/v1/districts': DISTRICTS,
      'GET /api/v1/config/public': CONFIG,
      'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
      [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([message(1, 'agent', 'Hello.')]),
    })
    renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText(/Reservations are paused until/)).toBeInTheDocument()
    expect(screen.queryByText(strings.banner.night('08:00'))).not.toBeInTheDocument()
  })
})

describe('On a wide screen (docs/11 §3.1)', () => {
  function wideScreen() {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) =>
        ({
          matches: query.includes('min-width: 992px'),
          media: query,
          onchange: null,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          addListener: vi.fn(),
          removeListener: vi.fn(),
          dispatchEvent: vi.fn(),
        }) as unknown as MediaQueryList,
    )
  }
  const chatRoutes = {
    'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
    [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([message(1, 'agent', 'Hello.')]),
  }

  it('puts the assistant beside the page, under one title', async () => {
    wideScreen()
    clientApi(chatRoutes)
    const { container } = renderApp(<AppRoutes />, { path: '/medicines' })

    const beside = await screen.findByRole('complementary', { name: strings.chat.title })
    expect(await within(beside).findByText('Hello.')).toBeInTheDocument()
    expect(within(beside).getByText(strings.chat.aiNotice)).toBeInTheDocument()
    // The page keeps the one main title; the panel has no way "back".
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(within(beside).queryByRole('link', { name: strings.common.back })).not.toBeInTheDocument()
    expect(container.querySelector('.nav--top')).not.toBeNull()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('shows one conversation on the assistant\'s own page, never two', async () => {
    wideScreen()
    clientApi(chatRoutes)
    renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText('Hello.')).toBeInTheDocument()
    expect(screen.getAllByLabelText(strings.chat.messageLabel)).toHaveLength(1)
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
  })

  it('has no panel at all on a phone: nothing asks for the chat', async () => {
    const api = clientApi(chatRoutes)
    renderApp(<AppRoutes />, { path: '/medicines' })

    expect(await screen.findByRole('heading', { name: strings.medicines.title })).toBeInTheDocument()
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
    expect(api.sent('GET', '/api/v1/conversations')).toEqual([])
  })
})
