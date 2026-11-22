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
  refusal,
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

  it('takes no more than the API reads, and says why a lookup was refused', async () => {
    pharmacyApi({ 'GET /api/v1/pharmacy/reservations': refusal(503, 'SERVICE_UNAVAILABLE') })
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    const box = await screen.findByLabelText(s.orderNumber)
    expect(box).toHaveAttribute('maxLength', '20')
    // Its label stays in sight, not only "R-" in the box (docs/11 §9).
    expect(screen.getByText(s.orderNumber, { selector: 'label' })).not.toHaveClass('sr-only')
    await user.type(box, 'R-7K3Q2F')
    await user.click(screen.getByRole('button', { name: s.find }))

    expect(await screen.findByText(strings.errors.SERVICE_UNAVAILABLE)).toBeInTheDocument()
  })

  it('brings the card of a tapped row into view and gives it the focus', async () => {
    pharmacyApi()
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    // A row of "Due today" or "For the next days": both are taps on the number.
    await user.click(await screen.findByRole('button', { name: /R-7K3Q2F/ }))

    const card = await screen.findByRole('article', { name: s.reservation('R-7K3Q2F') })
    await waitFor(() => expect(card).toHaveFocus())
  })

  it('puts an ask, which must be answered within hours, before what is due today', async () => {
    pharmacyApi()
    renderApp(<AppRoutes />, { path: '/pharmacy' })

    const ask = await screen.findByRole('region', { name: s.ask.title(2, 'CONCOR 5MG') })
    const due = screen.getByRole('region', { name: s.dueToday })
    // On a phone the columns stack: the ask must come first in the page's own order.
    expect(ask.compareDocumentPosition(due) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("says inside the dialog why [Not available] was refused", async () => {
    pharmacyApi({
      [`POST /api/v1/pharmacy/reservations/${HELD.id}/not-available`]: refusal(
        409,
        'RESERVATION_NOT_ACTIVE',
      ),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/reservations' })
    const user = userEvent.setup()

    const card = await screen.findByRole('article', { name: s.reservation('R-7K3Q2F') })
    await user.click(within(card).getByRole('button', { name: s.notAvailable }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: s.confirmNotAvailable }))

    expect(
      await within(dialog).findByText(strings.errors.RESERVATION_NOT_ACTIVE),
    ).toBeInTheDocument()
  })

  it('keeps what the server said when the card leaves the list', async () => {
    let picked = false
    pharmacyApi({
      'GET /api/v1/pharmacy/reservations': () => list(picked ? [] : [HELD]),
      [`POST /api/v1/pharmacy/reservations/${HELD.id}/picked-up`]: () => {
        picked = true
        return refusal(409, 'PICKUP_DEADLINE_PASSED')
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/reservations' })
    const user = userEvent.setup()

    const card = await screen.findByRole('article', { name: s.reservation('R-7K3Q2F') })
    await user.click(within(card).getByRole('button', { name: s.pickedUp }))

    await waitFor(() =>
      expect(screen.queryByRole('article', { name: s.reservation('R-7K3Q2F') })).not.toBeInTheDocument(),
    )
    expect(screen.getByText(strings.errors.PICKUP_DEADLINE_PASSED)).toBeInTheDocument()
  })

  it('opens the history from a notification about a cancelled reservation (B#52)', async () => {
    const cancelled = { ...HELD, state: 'CANCELLED_BY_CLIENT', closed_at: NOW } as const
    const api = pharmacyApi({
      'GET /api/v1/pharmacy/reservations': (call: { path: string }) =>
        list(call.path.includes('view=history') ? [cancelled] : []),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/reservations?view=history' })
    const user = userEvent.setup()

    expect(await screen.findByRole('article', { name: s.reservation('R-7K3Q2F') })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: s.history })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByText(s.nothingActive)).not.toBeInTheDocument()
    // The tabs still work, and the address follows them.
    await user.click(screen.getByRole('tab', { name: s.active }))
    expect(await screen.findByText(s.nothingActive)).toBeInTheDocument()
    expect(api.sent('GET', '/api/v1/pharmacy/reservations?view=active')).not.toEqual([])
  })
})

describe("The pharmacy's bar", () => {
  it.each([
    ['APPROVED', 'var(--green)'],
    ['PENDING', 'var(--amber)'],
    ['REJECTED', 'var(--red)'],
    ['SUSPENDED', 'var(--red)'],
  ])('shows %s in its own colour', async (status, colour) => {
    pharmacyApi({
      'GET /api/v1/pharmacy/me': { ...PROFILE, status },
      'GET /api/v1/districts': [],
    })
    renderApp(<AppRoutes />, { path: '/pharmacy' })

    const banner = await screen.findByRole('banner')
    expect(within(banner).getByText(s.status[status] ?? '')).toHaveStyle({ color: colour })
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

  it('says what is offered, and keeps the thank-you after the ask has gone', async () => {
    let answered = false
    pharmacyApi({
      'GET /api/v1/pharmacy/early-release-asks': () => ({
        items: answered ? [] : [ASK],
        server_now: NOW,
      }),
      [`POST /api/v1/pharmacy/early-release-asks/${ASK.id}/accept`]: () => {
        answered = true
        return { state: 'WITHDRAWN', message: 'Thank you, this need was just met.' }
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    const ask = await screen.findByRole('region', { name: s.ask.title(2, 'CONCOR 5MG') })
    // 600,000 of a public price of 800,000: a quarter off.
    expect(within(ask).getByText(s.ask.offer(2, '600,000 LBP', 25))).toBeInTheDocument()
    await user.click(within(ask).getByRole('button', { name: s.ask.accept }))

    await waitFor(() =>
      expect(screen.queryByRole('region', { name: s.ask.title(2, 'CONCOR 5MG') })).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Thank you, this need was just met.')).toBeInTheDocument()
  })

  it('never sends an emptied price, nor cuts down one above the public price', async () => {
    const api = pharmacyApi()
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    const ask = await screen.findByRole('region', { name: s.ask.title(2, 'CONCOR 5MG') })
    const price = within(ask).getByLabelText(s.ask.price)
    const accept = within(ask).getByRole('button', { name: s.ask.accept })
    await user.clear(price)
    expect(price).toHaveValue('')
    expect(accept).toBeDisabled()
    expect(within(ask).getByText(s.ask.range('800,000'))).toBeInTheDocument()

    await user.type(price, '8000000')
    await user.tab()
    // Left as typed, never clamped to the public price behind the pharmacist's back.
    expect(price).toHaveValue('8,000,000')
    expect(accept).toBeDisabled()
    await user.click(accept)
    expect(api.sent('POST', '/api/v1/pharmacy/early-release-asks')).toEqual([])
  })

  it('offers a box for free only once the pharmacist ticks that it is free', async () => {
    const api = pharmacyApi({
      [`POST /api/v1/pharmacy/early-release-asks/${ASK.id}/accept`]: {
        state: 'ACCEPTED',
        message: 'Thank you. The client has two hours to accept.',
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    const ask = await screen.findByRole('region', { name: s.ask.title(2, 'CONCOR 5MG') })
    const price = within(ask).getByLabelText(s.ask.price)
    const accept = within(ask).getByRole('button', { name: s.ask.accept })
    await user.clear(price)
    await user.type(price, '0')
    expect(accept).toBeDisabled()
    await user.click(within(ask).getByLabelText(s.ask.free))
    expect(within(ask).getByText(s.ask.offerFree(2))).toBeInTheDocument()
    await user.click(accept)

    await waitFor(() => expect(api.sent('POST', '/api/v1/pharmacy/early-release-asks')).toHaveLength(1))
    expect(api.sent('POST', '/api/v1/pharmacy/early-release-asks')[0].body).toEqual({
      qty: 2,
      price_lbp: 0,
    })
  })

  it('says inside the dialog why a decline was refused', async () => {
    pharmacyApi({
      [`POST /api/v1/pharmacy/early-release-asks/${ASK.id}/decline`]: refusal(409, 'ASK_NOT_OPEN'),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    const ask = await screen.findByRole('region', { name: s.ask.title(2, 'CONCOR 5MG') })
    await user.click(within(ask).getByRole('button', { name: s.ask.decline }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: s.ask.confirmDecline }))

    expect(await within(dialog).findByText(strings.errors.ASK_NOT_OPEN)).toBeInTheDocument()
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
    expect(await screen.findByText(s.ask.declined)).toBeInTheDocument()
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

  it("shows a page that isn't there, with its main area and heading, for an address it can't open (B#34)", async () => {
    // A suspended pharmacy keeps its reservations, never its stock.
    pharmacyApi({ 'GET /api/v1/pharmacy/me': { ...PROFILE, status: 'SUSPENDED' } })
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })

    const heading = await screen.findByRole('heading', { level: 1, name: strings.notFound.title })
    expect(screen.getByRole('main')).toContainElement(heading)
    expect(await accessibilityProblems(container)).toEqual([])
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
