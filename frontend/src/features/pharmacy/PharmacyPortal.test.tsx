import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '../../api/client'
import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
import { PHARMACIST, PROFILE } from '../../test/pharmacy'
import {
  accessibilityProblems,
  answer,
  CLIENT,
  CONFIG,
  loggedIn,
  pretendApi,
  renderApp,
  RESERVATION,
} from '../../test/render'

const s = strings.pharmacy
const NOW = CONFIG.server_now

const HELD = {
  id: RESERVATION.id,
  ref: 'R-7K3Q2F',
  state: 'RESERVED',
  status_text: 'Hand over by today 21:00',
  product: RESERVATION.product,
  batch: 'A123',
  expiry_date: '2027-01-15',
  qty: 2,
  qty_requested: 2,
  price_each: { lbp: 600_000, usd_approx: 6.7 },
  total: { lbp: 1_200_000, usd_approx: 13.4 },
  pickup_day: '2026-11-16',
  deadline: '2026-11-16T19:00:00Z',
  is_new: true,
  created_at: NOW,
  closed_at: null,
} satisfies Schemas['PharmacyReservation']
const ASK = {
  id: '88888888-8888-4888-8888-888888888888',
  state: 'ASKED',
  product: { ...RESERVATION.product, name: 'CONCOR 5MG', public_price: { lbp: 800_000, usd_approx: 8.9 } },
  qty_needed: 2,
  private_item: { batch: 'X9', expiry_date: '2027-06-03', qty_available: 5 },
  suggested_price: { lbp: 600_000, usd_approx: 6.7 },
  respond_by: '2026-11-16T09:42:00Z',
  answered_at: null,
} satisfies Schemas['EarlyReleaseAsk']
const NUMBERS = {
  new_reservations: 1,
  due_today: 1,
  open_asks: 1,
  live_listings: 40,
  units_reserved: 2,
  last_inventory_update: NOW,
  stale: false,
  server_now: NOW,
} satisfies Schemas['Dashboard']
const list = (items: unknown[]) => ({ items, next_cursor: null, server_now: NOW })

function pharmacyApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': PHARMACIST,
    'GET /api/v1/pharmacy/me': PROFILE,
    'GET /api/v1/pharmacy/dashboard': NUMBERS,
    'GET /api/v1/pharmacy/reservations': (call: { path: string }) =>
      call.path.includes('q=') && !call.path.includes('q=R-7K3Q2F') ? list([]) : list([HELD]),
    'GET /api/v1/pharmacy/early-release-asks': { items: [ASK], server_now: NOW },
    ...more,
  })
}

describe("The pharmacy's Today", () => {
  it('opens for a pharmacist, with what is due and what needs an answer', async () => {
    pharmacyApi()

    const { container } = renderApp(<AppRoutes />, { path: '/' })

    expect(await screen.findByRole('heading', { name: s.counter })).toBeInTheDocument()
    expect(screen.getByText('Hamra Pharmacy')).toBeInTheDocument()
    expect(await screen.findByText(s.isNew)).toBeInTheDocument()
    expect(await screen.findByText(s.ask.title(2, 'CONCOR 5MG'))).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('finds a reservation by its number and hands it over in one tap', async () => {
    const api = pharmacyApi({
      [`POST /api/v1/pharmacy/reservations/${HELD.id}/picked-up`]: { ...HELD, state: 'PICKED_UP' },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.orderNumber), 'r-7k3q2f')
    await user.click(screen.getByRole('button', { name: s.find }))
    const card = await screen.findByRole('article', { name: s.reservation('R-7K3Q2F') })
    expect(within(card).getByText(s.checkPrescription)).toBeInTheDocument()
    expect(within(card).getByText(/Batch A123/)).toBeInTheDocument()
    await user.click(within(card).getByRole('button', { name: s.pickedUp }))

    await waitFor(() => expect(api.sent('POST', '/api/v1/pharmacy/reservations')).toHaveLength(1))
    // The number is sent as it reads on the client's ticket.
    expect(api.sent('GET', '/api/v1/pharmacy/reservations?q=')[0].path).toContain('q=R-7K3Q2F')
  })

  it('marks only some packs as not available, after asking which', async () => {
    const api = pharmacyApi({
      [`POST /api/v1/pharmacy/reservations/${HELD.id}/not-available`]: { ...HELD, qty: 1 },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/reservations' })
    const user = userEvent.setup()

    const card = await screen.findByRole('article', { name: s.reservation('R-7K3Q2F') })
    await user.click(within(card).getByRole('button', { name: s.notAvailable }))
    expect(api.sent('POST', '/api/v1/pharmacy/reservations')).toEqual([])
    await user.click(await screen.findByRole('button', { name: s.somePacks(1) }))
    await user.click(screen.getByRole('button', { name: s.confirmNotAvailable }))

    await waitFor(() => expect(api.sent('POST', '/api/v1/pharmacy/reservations')).toHaveLength(1))
    expect(api.sent('POST', '/api/v1/pharmacy/reservations')[0].body).toEqual({ units: 1 })
  })

  it('says so when no reservation has that number', async () => {
    pharmacyApi()
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.orderNumber), 'R-222222')
    await user.click(screen.getByRole('button', { name: s.find }))

    expect(await screen.findByText(s.noSuchNumber('R-222222'))).toBeInTheDocument()
  })
})

describe('An early-release ask', () => {
  it('is accepted with the packs and the price the pharmacist chose', async () => {
    const api = pharmacyApi({
      [`POST /api/v1/pharmacy/early-release-asks/${ASK.id}/accept`]: {
        state: 'ACCEPTED',
        message: 'Thank you. The client has two hours to accept.',
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    const ask = await screen.findByRole('region', { name: s.ask.title(2, 'CONCOR 5MG') })
    await user.selectOptions(within(ask).getByLabelText(s.ask.release), '2')
    await user.click(within(ask).getByRole('button', { name: s.ask.accept }))

    await waitFor(() => expect(api.sent('POST', '/api/v1/pharmacy/early-release-asks')).toHaveLength(1))
    expect(api.sent('POST', '/api/v1/pharmacy/early-release-asks')[0].body).toEqual({
      qty: 2,
      price_lbp: 600_000,
    })
  })

  it('is declined with a reason from a list, never typed words', async () => {
    const api = pharmacyApi({
      [`POST /api/v1/pharmacy/early-release-asks/${ASK.id}/decline`]: answer(204),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    const ask = await screen.findByRole('region', { name: s.ask.title(2, 'CONCOR 5MG') })
    await user.click(within(ask).getByRole('button', { name: s.ask.decline }))
    await user.selectOptions(await screen.findByRole('combobox', { name: s.ask.declineTitle }), 'price')
    await user.click(screen.getByRole('button', { name: s.ask.confirmDecline }))

    await waitFor(() => expect(api.sent('POST', '/api/v1/pharmacy/early-release-asks')).toHaveLength(1))
    expect(api.sent('POST', '/api/v1/pharmacy/early-release-asks')[0].body).toEqual({ reason: 'price' })
    // The decline sheet holds a list and buttons: nowhere to type.
    expect(screen.queryByRole('textbox', { name: s.ask.declineTitle })).not.toBeInTheDocument()
  })
})

describe('Who sees the portal', () => {
  it('shows a pending pharmacy its status, and no counter', async () => {
    pharmacyApi({ 'GET /api/v1/pharmacy/me': { ...PROFILE, status: 'PENDING' } })

    renderApp(<AppRoutes />, { path: '/pharmacy' })

    expect(await screen.findByText(s.pending)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: s.counter })).not.toBeInTheDocument()
  })

  it('sends a client who types its address back to their own Home', async () => {
    loggedIn()
    const api = pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      'GET /api/v1/reservations': list([]),
    })

    renderApp(<AppRoutes />, { path: '/pharmacy' })

    expect(await screen.findByRole('heading', { name: strings.home.title })).toBeInTheDocument()
    expect(api.sent('GET', '/api/v1/pharmacy')).toEqual([])
  })
})
