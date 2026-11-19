import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '../../../api/client'
import { AppRoutes } from '../../../app/App'
import { tidy } from './choices'
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

/** What a typed name finds: a medicine in stock, with its boxes. */
function byName(more: object = {}) {
  return {
    groups: [{ product: PRODUCT, by_ingredient: false, items: [LISTING], total_found: 4, no_match: null }],
    closest: false,
    did_you_mean: [],
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
    'POST /api/v1/listings/search-by-name': byName(),
    'GET /api/v1/me/searches': { items: [] },
    'POST /api/v1/me/searches': (call: { body: unknown }) => ({ items: [(call.body as { q: string }).q] }),
    'DELETE /api/v1/me/searches': { items: [] },
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

    // Typing is enough: the boxes in stock show at once, under the medicine's own name.
    await user.type(await screen.findByLabelText(s.label), 'augmentin')

    const group = await screen.findByRole('region', { name: PRODUCT.name })
    const row = within(group).getByRole('link', { name: /Hamra Pharmacy/ })
    expect(row).toHaveAttribute('href', `/listings/${LISTING_ID}`)
    expect(row).toHaveTextContent('600,000 LBP')
    expect(row).toHaveTextContent('Save 400,000')
    expect(row).toHaveTextContent('21 min walk · 4 min by car')
    expect(row).toHaveTextContent('5+ left')
    expect(within(group).getByText(s.prescription)).toBeInTheDocument()
    // The name travels in a body, like the place: never in an address.
    expect(api.sent('POST', '/api/v1/listings/search-by-name').at(-1)?.body).toMatchObject({
      q: 'augmentin',
      location: null,
    })
    expect(await accessibilityProblems(container)).toEqual([])

    // One medicine's own page lists every pharmacy that has it.
    await user.click(within(group).getByRole('button', { name: s.seeAll(4) }))
    expect(await screen.findByRole('heading', { level: 1, name: PRODUCT.name })).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/listings/search').at(-1)?.body).toMatchObject({ product_id: PRODUCT.id })
  })

  it('searches what is in stock from the first letter typed', async () => {
    const api = searchApi()
    renderApp(<AppRoutes />, { path: '/search' })

    await userEvent.type(await screen.findByLabelText(s.label), 'a')

    expect(await screen.findByRole('region', { name: PRODUCT.name })).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/listings/search-by-name').at(-1)?.body).toMatchObject({ q: 'a' })
  })

  it("shows the client's last searches while nothing is typed, and clears them", async () => {
    const api = searchApi({ 'GET /api/v1/me/searches': { items: ['augmentin', 'concor 5'] } })
    renderApp(<AppRoutes />, { path: '/search' })
    const user = userEvent.setup()

    const last = await screen.findByRole('region', { name: s.lastSearches })
    await user.click(within(last).getByRole('button', { name: 'concor 5' }))
    expect(screen.getByLabelText(s.label)).toHaveValue('concor 5')

    await user.clear(screen.getByLabelText(s.label))
    await user.click(await screen.findByRole('button', { name: s.clearSearches }))
    await waitFor(() => expect(api.sent('DELETE', '/api/v1/me/searches')).toHaveLength(1))
    expect(screen.queryByRole('region', { name: s.lastSearches })).not.toBeInTheDocument()
  })

  it('keeps a name in the last searches when it led to an offer, not for every letter', async () => {
    const api = searchApi()
    renderApp(<AppRoutes />, { path: '/search' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.label), 'augmentin')
    await screen.findByRole('region', { name: PRODUCT.name })
    expect(api.sent('POST', '/api/v1/me/searches')).toEqual([])

    await user.click(screen.getByRole('link', { name: /Hamra Pharmacy/ }))
    await waitFor(() =>
      expect(api.sent('POST', '/api/v1/me/searches').map((call) => call.body)).toEqual([{ q: 'augmentin' }]),
    )
  })

  it('shows the results first on a phone, with the filters folded behind one button', async () => {
    searchApi()
    renderApp(<AppRoutes />, { path: '/search' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.label), 'augmentin')
    await screen.findByRole('region', { name: PRODUCT.name })

    const fold = screen.getByRole('button', { name: new RegExp(s.filters) })
    expect(fold).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText(s.maxPrice)).not.toBeInTheDocument()
    await user.click(fold)
    expect(screen.getByLabelText(s.maxPrice)).toBeInTheDocument()
    // The days of use and the pickup day are asked when a box is reserved, not here.
    expect(screen.queryByRole('button', { name: s.days(12) })).not.toBeInTheDocument()
  })

  it('keeps the typed name while an offer is opened, and comes back to its results', async () => {
    searchApi()
    renderApp(<AppRoutes />, { path: '/search' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.label), 'augmentin')
    await user.click(await screen.findByRole('link', { name: /Hamra Pharmacy/ }))
    await screen.findByRole('button', { name: strings.offer.reserve })
    await user.click(screen.getByRole('link', { name: strings.common.back }))

    expect(await screen.findByLabelText(s.label)).toHaveValue('augmentin')
    expect(await screen.findByRole('region', { name: PRODUCT.name })).toBeInTheDocument()
  })

  it('says when a name is only the closest one, and offers the others', async () => {
    searchApi({
      'POST /api/v1/listings/search-by-name': byName({ closest: true, did_you_mean: ['AUGMEX'] }),
    })
    renderApp(<AppRoutes />, { path: '/search' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.label), 'ogmentn')

    expect(await screen.findByText(s.closest('ogmentn'))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'AUGMEX' }))
    expect(screen.getByLabelText(s.label)).toHaveValue('AUGMEX')
  })

  it('sends the filters the client chose: a price limit, open now, the order', async () => {
    const api = searchApi()
    renderApp(<AppRoutes />, { path: '/search' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.label), 'augmentin')
    await user.click(await screen.findByRole('button', { name: new RegExp(s.filters) }))
    await user.type(screen.getByLabelText(s.maxPrice), '500000')
    await user.click(screen.getByLabelText(s.openNow))
    await user.selectOptions(screen.getByLabelText(s.sort), s.sorts.cheapest)

    await waitFor(() => {
      expect(api.sent('POST', '/api/v1/listings/search-by-name').at(-1)?.body).toMatchObject({
        max_price: { amount: '500000', currency: 'LBP' },
        open_now: true,
        sort: 'cheapest',
        days_of_use: null,
        pickup_day: null,
      })
    })
  })

  it("keeps the client's place out of every address", async () => {
    const api = searchApi()
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: new RegExp(s.filters) }))
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

  it('opens the chat with the medicine named when no pharmacy has it', async () => {
    searchApi({
      'POST /api/v1/listings/search': result([]),
      'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
      [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([]),
      'GET /api/v1/conversations/chats': { items: [], server_now: CONFIG.server_now },
    })
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    expect(await screen.findByText(s.empty(PRODUCT.name))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: s.askToFind }))

    expect(await screen.findByLabelText(strings.chat.messageLabel)).toHaveValue(s.askDraft(PRODUCT.name))
  })

  it('carries the place from the search to the offer the client opens', async () => {
    const api = searchApi()
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: new RegExp(s.filters) }))
    await user.click(await screen.findByRole('button', { name: new RegExp(s.near) }))
    await user.selectOptions(await screen.findByLabelText(strings.chat.location.orDistrict), 'Matn')
    await user.click(screen.getByRole('button', { name: strings.chat.location.useDistrict }))
    await user.click(await screen.findByRole('link', { name: /Hamra Pharmacy/ }))

    await screen.findByRole('button', { name: strings.offer.reserve })
    // The offer is read for the same place: nothing is asked twice. The days of use are
    // asked in the reserve sheet.
    expect(api.sent('POST', `/api/v1/listings/${LISTING_ID}/view`).at(-1)?.body).toEqual({
      location: { district_id: 2 },
      days_of_use: null,
    })
  })

  it('says so when no pharmacy has the name, and offers close names', async () => {
    searchApi({
      'POST /api/v1/listings/search-by-name': byName({ groups: [], did_you_mean: ['AUGMENTIN 1G'] }),
    })
    renderApp(<AppRoutes />, { path: '/search' })

    await userEvent.type(await screen.findByLabelText(s.label), 'ogmntn')

    expect(await screen.findByRole('button', { name: 'AUGMENTIN 1G' })).toBeInTheDocument()
    expect(screen.getByText(s.nothingInStock('ogmntn'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: s.askToFind })).toBeInTheDocument()
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
    expect(screen.queryByRole('button', { name: strings.common.tryAgain })).not.toBeInTheDocument()
  })

  it('never sends more days of use than the most, whatever is typed', async () => {
    // Found by the owner on 2026-11-18: 999 days were sent, the server refused them, the
    // page said "this offer is no longer available", and every other offer said the
    // same until the page was loaded again, because the choice travels with each one.
    const api = searchApi()
    renderApp(<AppRoutes />, { path: `/listings/${LISTING_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: strings.offer.reserve }))
    await user.click(await screen.findByRole('button', { name: strings.search.other }))
    await user.type(screen.getByLabelText(strings.search.otherDays), '99999')

    await waitFor(() => {
      const days = api
        .sent('POST', `/api/v1/listings/${LISTING_ID}/view`)
        .map((call) => (call.body as { days_of_use: number | null }).days_of_use)
      expect(days.at(-1)).not.toBeNull()
      expect(days.every((count) => count === null || (count >= 1 && count <= 365))).toBe(true)
    })
    // The offer is still on the screen, with its sheet.
    expect(screen.getByRole('button', { name: strings.reserve.submit(1) })).toBeInTheDocument()
    expect(screen.queryByText(strings.offer.gone)).not.toBeInTheDocument()
  })

  it('says a failure as what it is, and tries again from clean choices', async () => {
    let refuse = true
    const api = searchApi({
      [`POST /api/v1/listings/${LISTING_ID}/view`]: () =>
        refuse
          ? refusal(422, 'VALIDATION_ERROR')
          : {
              listing: LISTING,
              week: [{ day: '2026-11-16', hours: '08:00-21:00' }],
              location: { source: 'profile', label: 'Beirut' },
              server_now: CONFIG.server_now,
            },
    })
    renderApp(<AppRoutes />, { path: `/listings/${LISTING_ID}` })
    const user = userEvent.setup()

    // Not "no longer available": the box is there, the request was wrong.
    expect(await screen.findByRole('alert')).toHaveTextContent(errorMessage('VALIDATION_ERROR'))
    expect(screen.queryByText(strings.offer.gone)).not.toBeInTheDocument()

    refuse = false
    await user.click(screen.getByRole('button', { name: strings.common.tryAgain }))

    expect(await screen.findByRole('button', { name: strings.offer.reserve })).toBeInTheDocument()
    expect(api.sent('POST', `/api/v1/listings/${LISTING_ID}/view`).at(-1)?.body).toMatchObject({
      days_of_use: null,
    })
  })
})

describe('What the client chose is always safe to send', () => {
  it('cuts a number down to the most, and takes anything else as not said', () => {
    expect(tidy({ daysOfUse: 999 })).toEqual({ daysOfUse: 365 })
    expect(tidy({ daysOfUse: 12 })).toEqual({ daysOfUse: 12 })
    expect(tidy({ daysOfUse: 0 })).toEqual({ daysOfUse: null })
    expect(tidy({ daysOfUse: -3 })).toEqual({ daysOfUse: null })
    expect(tidy({ daysOfUse: Number.NaN })).toEqual({ daysOfUse: null })
    expect(tidy({ daysOfUse: 2.7 })).toEqual({ daysOfUse: 2 })
    expect(tidy({ maxPriceLbp: 1e30 })).toEqual({ maxPriceLbp: 99_999_999_999 })
    expect(tidy({ maxPriceLbp: 500_000 })).toEqual({ maxPriceLbp: 500_000 })
    // What is not a number is left as it is.
    expect(tidy({ sort: 'cheapest', openNow: true })).toEqual({ sort: 'cheapest', openNow: true })
  })
})
