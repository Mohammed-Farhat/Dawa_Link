import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '../../../api/client'
import { AppRoutes } from '../../../app/App'
import { errorMessage, strings } from '../../../strings/en'
import {
  accessibilityProblems,
  CHAT_ID,
  CLIENT,
  CONFIG,
  DISTRICTS,
  loggedIn,
  page,
  pretendApi,
  refusal,
  renderApp,
  RESERVATION,
} from '../../../test/render'

const s = strings.search
const PRODUCT = RESERVATION.product
const LISTING_ID = '77777777-7777-4777-8777-777777777777'

const LISTING = {
  id: LISTING_ID,
  product: PRODUCT,
  pharmacy: RESERVATION.pharmacy,
  price: { lbp: 600_000, usd_approx: 6.7 },
  saving: { lbp: 400_000, usd_approx: 4.47 },
  discount_pct: 40,
  expiry_date: '2027-01-15',
  days_left: 60,
  available: 5,
  more_available: true,
  travel: { car_min: 4, walk_min: 21, km: 1.6, source: 'road' },
  fits: null as boolean | null,
  pickup_days_allowed: ['2026-11-16', '2026-11-17'],
  expiry_limits_pickup: false,
} satisfies Schemas['Listing']

function result(items: (typeof LISTING)[], more: object = {}) {
  return {
    product: PRODUCT,
    items,
    total_found: items.length,
    left_out_by_pickup_day: 0,
    no_match: null,
    next_cursor: null,
    location: { source: 'profile', label: 'Beirut' },
    upcoming_days: ['2026-11-16', '2026-11-17', '2026-11-18'],
    server_now: CONFIG.server_now,
    ...more,
  }
}

function searchApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/catalog/products': { items: [PRODUCT], did_you_mean: [] },
    'POST /api/v1/listings/search': result([LISTING]),
    [`POST /api/v1/listings/${LISTING_ID}/view`]: {
      listing: LISTING,
      week: [{ day: '2026-11-16', hours: '08:00-21:00' }],
      location: { source: 'profile', label: 'Beirut' },
      server_now: CONFIG.server_now,
    },
    ...more,
  })
}

describe('Searching without the assistant', () => {
  it('finds a medicine by its name and shows where it is discounted', async () => {
    const api = searchApi()
    const { container } = renderApp(<AppRoutes />, { path: '/search' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.label), 'augmentin')
    await user.click(await screen.findByRole('button', { name: /AUGMENTIN 1G/ }))

    const row = await screen.findByRole('link', { name: /Hamra Pharmacy/ })
    expect(row).toHaveAttribute('href', `/listings/${LISTING_ID}`)
    expect(row).toHaveTextContent('600,000 LBP')
    expect(row).toHaveTextContent('Save 400,000')
    expect(row).toHaveTextContent('21 min walk · 4 min by car')
    expect(row).toHaveTextContent('5+ left')
    expect(screen.getByText(s.prescription)).toBeInTheDocument()
    expect(api.sent('GET', '/api/v1/catalog/products')[0].path).toContain('q=augmentin')
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('sends the days of use and the pickup day the client chose', async () => {
    const api = searchApi()
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: s.days(12) }))
    await user.click(screen.getByRole('button', { name: strings.common.tomorrow }))

    await waitFor(() => {
      const last = api.sent('POST', '/api/v1/listings/search').at(-1)
      expect(last?.body).toMatchObject({ days_of_use: 12, pickup_day: '2026-11-17', location: null })
    })
  })

  it("keeps the client's place out of every address", async () => {
    const api = searchApi()
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: new RegExp(s.near) }))
    await user.selectOptions(await screen.findByLabelText(strings.chat.location.orDistrict), 'Matn')
    await user.click(screen.getByRole('button', { name: strings.chat.location.useDistrict }))

    await waitFor(() => {
      const last = api.sent('POST', '/api/v1/listings/search').at(-1)
      expect(last?.body).toMatchObject({ location: { district_id: 2 } })
    })
    // In the body of a request, never in an address a history or a log keeps.
    expect(api.calls.every((call) => !/lat=|lon=|district/.test(call.path.split('?')[1] ?? ''))).toBe(true)
  })

  it('says why nothing fits, and opens the chat with the medicine named', async () => {
    searchApi({
      'POST /api/v1/listings/search': result([], {
        no_match: { latest_expiry: '2026-11-28', latest_pickup_day: '2026-11-17' },
      }),
      'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
      [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([]),
    })
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: s.days(30) }))
    expect(await screen.findByText(s.tooEarly(30, '28 Nov 2026'))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: s.askToFind }))

    // The sentence is typed, not sent: the client presses send themselves (BLD-D30).
    expect(await screen.findByLabelText(strings.chat.messageLabel)).toHaveValue(
      s.askDraft('AUGMENTIN 1G'),
    )
  })

  it('carries the choices from the search to the offer the client opens', async () => {
    const api = searchApi()
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: s.days(12) }))
    await user.click(await screen.findByRole('button', { name: new RegExp(s.near) }))
    await user.selectOptions(await screen.findByLabelText(strings.chat.location.orDistrict), 'Matn')
    await user.click(screen.getByRole('button', { name: strings.chat.location.useDistrict }))
    await user.click(await screen.findByRole('link', { name: /Hamra Pharmacy/ }))

    await screen.findByRole('button', { name: strings.offer.reserve })
    // The offer is read for the same place and the same days: nothing is asked twice.
    expect(api.sent('POST', `/api/v1/listings/${LISTING_ID}/view`).at(-1)?.body).toEqual({
      location: { district_id: 2 },
      days_of_use: 12,
    })
  })

  it('offers close names when nothing is called that', async () => {
    searchApi({ 'GET /api/v1/catalog/products': { items: [], did_you_mean: ['AUGMENTIN 1G'] } })
    renderApp(<AppRoutes />, { path: '/search' })

    await userEvent.type(await screen.findByLabelText(s.label), 'ogmntn')

    expect(await screen.findByRole('button', { name: 'AUGMENTIN 1G' })).toBeInTheDocument()
    expect(screen.getByText(s.nothingNamed('ogmntn'))).toBeInTheDocument()
  })
})

describe('Reserving from an offer', () => {
  it('reserves the pack with a key of its own and opens the ticket', async () => {
    const api = searchApi({
      'POST /api/v1/reservations': RESERVATION,
      [`GET /api/v1/reservations/${RESERVATION.id}`]: RESERVATION,
      'GET /api/v1/reservations': { items: [RESERVATION], next_cursor: null, server_now: CONFIG.server_now },
    })
    const { container } = renderApp(<AppRoutes />, { path: `/listings/${LISTING_ID}` })
    const user = userEvent.setup()

    expect(await screen.findByText(strings.offer.makeSure('15 Jan 2027'))).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(screen.getByRole('button', { name: strings.offer.reserve }))
    await user.click(await screen.findByRole('button', { name: strings.reserve.more }))
    await user.click(screen.getByRole('button', { name: strings.reserve.submit(2) }))

    expect(await screen.findByText('R-7K3Q2F')).toBeInTheDocument()
    const sent = api.sent('POST', '/api/v1/reservations')[0]
    expect(sent.body).toEqual({
      listing_id: LISTING_ID,
      qty: 2,
      expected_price_lbp: 600_000,
      pickup_day: '2026-11-16',
      days_of_use: 1,
    })
    expect(sent.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('says in plain words why a reservation was refused', async () => {
    searchApi({ 'POST /api/v1/reservations': refusal(409, 'NOT_ENOUGH_STOCK', { available: 0 }) })
    renderApp(<AppRoutes />, { path: `/listings/${LISTING_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: strings.offer.reserve }))
    await user.click(await screen.findByRole('button', { name: strings.reserve.submit(1) }))

    expect(await screen.findByRole('alert')).toHaveTextContent(errorMessage('NOT_ENOUGH_STOCK'))
  })

  it("won't reserve a box that can't last the client's days", async () => {
    searchApi({
      [`POST /api/v1/listings/${LISTING_ID}/view`]: {
        listing: { ...LISTING, fits: false, pickup_days_allowed: [] },
        week: [],
        location: { source: 'profile', label: 'Beirut' },
        server_now: CONFIG.server_now,
      },
    })
    renderApp(<AppRoutes />, { path: `/listings/${LISTING_ID}` })

    await userEvent.click(await screen.findByRole('button', { name: strings.offer.reserve }))

    expect(await screen.findByText(strings.reserve.noDay)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: strings.reserve.submit(1) })).toBeDisabled()
  })

  it('says so when the offer is gone', async () => {
    searchApi({ [`POST /api/v1/listings/${LISTING_ID}/view`]: refusal(404, 'NOT_FOUND') })

    renderApp(<AppRoutes />, { path: `/listings/${LISTING_ID}` })

    expect(await screen.findByText(strings.offer.gone)).toBeInTheDocument()
  })
})
