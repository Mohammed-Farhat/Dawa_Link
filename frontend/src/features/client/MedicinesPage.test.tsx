import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '../../api/client'
import { AppRoutes } from '../../app/App'
import { errorMessage, strings } from '../../strings/en'
import {
  accessibilityProblems,
  CLIENT,
  CONFIG,
  DISTRICTS,
  loggedIn,
  pretendApi,
  refusal,
  renderApp,
  RESERVATION,
} from '../../test/render'

const m = strings.medicines
const NOW = CONFIG.server_now // 10:00 in Beirut

const WATCH = {
  id: 'aaaaaaaa-7777-4777-8777-aaaaaaaaaaaa',
  product: RESERVATION.product,
  qty: 1,
  qty_missing: 1,
  days_of_use: 1,
  max_price: null,
  state: 'ACTIVE',
  district: 'Beirut',
  ends_at: '2026-11-16T14:00:00Z',
  created_at: NOW,
} satisfies Schemas['Watch']

const none = { items: [], next_cursor: null, server_now: NOW }

function medicinesApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/watches': { items: [WATCH], server_now: NOW },
    'GET /api/v1/reservations': none,
    ...more,
  })
}

describe('Watches on Home (B#39)', () => {
  it('says the day a watch ends when it is not today, by the server clock', async () => {
    medicinesApi({
      'GET /api/v1/watches': { items: [{ ...WATCH, ends_at: '2026-11-16T23:30:00Z' }], server_now: NOW },
      'GET /api/v1/offers': { items: [], server_now: NOW },
      'GET /api/v1/requests': { items: [], server_now: NOW },
    })
    renderApp(<AppRoutes />, { path: '/' })

    expect(await screen.findByText(m.watchUntil('tomorrow 01:30', 'Beirut'))).toBeInTheDocument()
  })
})

describe('My medicines', () => {
  it("shows a watch's offer in amber: the client's tap is needed (B#17)", async () => {
    medicinesApi({ 'GET /api/v1/watches': { items: [{ ...WATCH, state: 'OFFER_PENDING' }], server_now: NOW } })
    renderApp(<AppRoutes />, { path: '/medicines' })

    const watching = await screen.findByRole('region', { name: m.watchingTitle })
    expect(within(watching).getByText(m.watchOffer)).toHaveClass('status-pill--amber')
  })

  it('says the day a watch ends when it is not today (B#39)', async () => {
    // Started at 19:30: it ends at 01:30 the next day, by the server's clock.
    medicinesApi({
      'GET /api/v1/watches': { items: [{ ...WATCH, ends_at: '2026-11-16T23:30:00Z' }], server_now: NOW },
    })
    renderApp(<AppRoutes />, { path: '/medicines' })

    expect(await screen.findByText(m.watchUntil('tomorrow 01:30', 'Beirut'))).toBeInTheDocument()
  })

  it('says "today" for a watch that ends today, so the day is never guessed (B#39)', async () => {
    medicinesApi()
    renderApp(<AppRoutes />, { path: '/medicines' })

    expect(await screen.findByText(m.watchUntil('today 16:00', 'Beirut'))).toBeInTheDocument()
  })

  it('offers the ways to find a medicine when nothing is to pick up, and none for an empty history', async () => {
    medicinesApi({ 'GET /api/v1/watches': { items: [], server_now: NOW } })
    const { container } = renderApp(<AppRoutes />, { path: '/medicines' })
    const user = userEvent.setup()

    const panel = await screen.findByRole('tabpanel')
    expect(await within(panel).findByText(m.nothingActive)).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: strings.home.goSearch })).toHaveAttribute('href', '/search')
    expect(within(panel).getByRole('link', { name: strings.home.goAsk })).toHaveAttribute('href', '/assistant')
    expect(await accessibilityProblems(container)).toEqual([])

    await user.click(screen.getByRole('tab', { name: m.history }))
    expect(await within(panel).findByText(m.nothingBefore)).toBeInTheDocument()
    expect(within(panel).queryByRole('link')).not.toBeInTheDocument()
  })

  it('says so when [Stop watching] failed, keeps the row, and never sends twice at once (A#41)', async () => {
    const api = medicinesApi({ [`POST /api/v1/watches/${WATCH.id}/cancel`]: refusal(503, 'SERVICE_UNAVAILABLE') })
    renderApp(<AppRoutes />, { path: '/medicines' })
    const user = userEvent.setup()

    const stop = await screen.findByRole('button', { name: m.stopWatchingFor(WATCH.product.name) })
    await user.click(stop)

    expect(await screen.findByRole('alert')).toHaveTextContent(errorMessage('SERVICE_UNAVAILABLE'))
    expect(screen.getByRole('region', { name: m.watchingTitle })).toHaveTextContent(WATCH.product.name)
    expect(api.sent('POST', `/api/v1/watches/${WATCH.id}/cancel`)).toHaveLength(1)
    await waitFor(() => expect(stop).toBeEnabled())
  })

  it('calls a reservation nobody came for a missed pickup, never "Expired" (B#13)', async () => {
    const missed = { ...RESERVATION, state: 'EXPIRED_NO_SHOW', status_text: "Expired: it wasn't picked up in time" }
    medicinesApi({ 'GET /api/v1/reservations': { ...none, items: [missed] } })
    const { container } = renderApp(<AppRoutes />, { path: '/medicines' })

    expect(await screen.findByText(strings.ticket.missedPickup)).toBeInTheDocument()
    expect(screen.queryByText(/^Expired/)).not.toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('moves between its two tabs with the arrow keys', async () => {
    medicinesApi()
    renderApp(<AppRoutes />, { path: '/medicines' })
    const user = userEvent.setup()

    const active = await screen.findByRole('tab', { name: m.active })
    expect(screen.getByRole('tabpanel')).toBeInTheDocument()
    active.focus()
    await user.keyboard('{ArrowRight}')

    const history = screen.getByRole('tab', { name: m.history })
    expect(history).toHaveAttribute('aria-selected', 'true')
    expect(history).toHaveFocus()
  })
})

describe('A list that is loading (B#43)', () => {
  it("shows its cards' grey shapes, and says it is loading", async () => {
    medicinesApi({ 'GET /api/v1/reservations': () => new Promise(() => {}) })
    const { container } = renderApp(<AppRoutes />, { path: '/medicines' })

    await screen.findByRole('heading', { name: m.title })
    const words = await screen.findByText(strings.common.loading)
    // Heard, not seen: what is seen is the cards' shapes, in a status a reader announces.
    expect(words).toHaveClass('sr-only')
    expect(words.closest('[role="status"]')).toHaveClass('placeholder')
    expect(container.querySelectorAll('.placeholder__card').length).toBeGreaterThan(0)
    expect(await accessibilityProblems(container)).toEqual([])
  })
})
