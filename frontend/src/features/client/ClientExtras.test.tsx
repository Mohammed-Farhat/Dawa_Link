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

describe('Logging out from the profile', () => {
  it.each([204, 503])('clears authentication and leaves the profile after status %i without refreshing', async (status) => {
    clientApi({ 'POST /api/v1/auth/logout': answer(status) })
    renderApp(<AppRoutes />, { path: '/me' })
    const button = await screen.findByRole('button', { name: 'Log out' })
    await userEvent.setup().click(button)
    expect(await screen.findByRole('heading', { name: strings.login.title })).toBeInTheDocument()
    expect(window.localStorage.getItem('dawalink.token')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument()
  })
})

describe('[Notify me] on a search that found nothing (CS-6)', () => {
  it('starts a 6-hour watch with a price limit, from where the search looked', async () => {
    const api = clientApi({
      'POST /api/v1/watches': answer(201, { ...WATCH, server_now: CONFIG.server_now }),
    })
    const { container } = renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    // Both ways on are offered: ask the assistant, or be told when it appears.
    expect(await screen.findByRole('button', { name: s.askToFind })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: s.notify.button }))
    expect(await accessibilityProblems(container)).toEqual([])
    await user.type(screen.getByLabelText(s.notify.maxPrice), '900000')
    await user.click(screen.getByRole('button', { name: s.notify.start }))

    // The watch ends at 16:00 today by the server's clock, and says so: its six hours
    // often cross midnight, so the day is always named (B#39).
    expect(await screen.findByText(s.notify.watching('today 16:00'))).toBeInTheDocument()
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

  it("says when requests open again, by the server's clock (B#37)", async () => {
    // 10:00 in Beirut is past the morning's opening: the next one is tomorrow's.
    clientApi({
      'POST /api/v1/watches': refusal(409, 'OUTSIDE_REQUEST_HOURS', { opens_at: '2026-11-17T06:00:00Z' }),
    })
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: s.notify.button }))
    await user.click(screen.getByRole('button', { name: s.notify.start }))

    const l = strings.limits
    expect(await screen.findByText(l.comeBack(l.comeBackTomorrow('08:00')))).toBeInTheDocument()
  })

  it('sends the price limit with a search', async () => {
    const api = clientApi()
    renderApp(<AppRoutes />, { path: `/search?product=${PRODUCT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: new RegExp(s.filters) }))
    await user.type(await screen.findByLabelText(s.maxPrice), '500000')

    await waitFor(() => {
      const sent = api.sent('POST', '/api/v1/listings/search').map((call) => call.body as { max_price: unknown })
      expect(sent[sent.length - 1].max_price).toEqual({ amount: '500000', currency: 'LBP' })
    })
  })
})

describe('Watches in My medicines (CS-11)', () => {
  it('opens the ticket of a past reservation from History', async () => {
    const past = { ...RESERVATION, state: 'EXPIRED_NO_SHOW', status_text: "Missed pickup: it wasn't picked up in time" }
    clientApi({
      'GET /api/v1/reservations': { items: [past], next_cursor: null, server_now: CONFIG.server_now },
    })
    renderApp(<AppRoutes />, { path: '/medicines' })

    const details = await screen.findByRole('link', { name: new RegExp(strings.medicines.details) })
    expect(details).toHaveAttribute('href', `/reservations/${RESERVATION.id}`)
  })

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
    await user.click(within(watching).getByRole('button', { name: m.stopWatchingFor(PRODUCT.name) }))

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

  it('shows a notification as plain text, and never follows a link that is not ours (FS-8)', async () => {
    const evil = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    clientApi({
      'GET /api/v1/notifications': {
        items: [{ ...NOTE, title: `Title ${evil}`, lines: [`Line ${evil}`], link: null }],
        next_cursor: null,
        unread: 1,
      },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/notifications' })

    expect(await screen.findByText(`Title ${evil}`)).toBeInTheDocument()
    expect(screen.getByText(`Line ${evil}`)).toBeInTheDocument()
    expect(container.querySelector('script, img, iframe')).toBeNull()
    expect(container.querySelector('[onerror]')).toBeNull()
  })

  it('is reached from Me, where the profile is edited', async () => {
    const api = clientApi({ 'PATCH /api/v1/me/profile': { ...CLIENT, phone: '70 123 456' } })
    const { container } = renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()
    const m = strings.me

    expect(await screen.findByText(strings.notifications.count(1))).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    // The client's own details: the name in parts, the date of birth, the phone.
    const details = screen.getByRole('region', { name: m.profile })
    await user.type(within(details).getByLabelText(new RegExp(`^${m.phone.replace(/[()]/g, '\\$&')}`)), '70 123 456')
    await user.click(within(details).getByRole('button', { name: m.save }))

    expect(await within(details).findByText(m.saved)).toBeInTheDocument()
    expect(api.sent('PATCH', '/api/v1/me/profile')[0].body).toEqual({
      first_name: 'Nour',
      middle_name: null,
      last_name: 'Khoury',
      birth_date: '1990-05-17',
      phone: '70 123 456',
    })

    // "Other brands" is saved by its own tick.
    await user.click(screen.getByRole('checkbox'))
    await waitFor(() =>
      expect(api.sent('PATCH', '/api/v1/me/profile').at(-1)?.body).toEqual({ alternatives_ok_default: true }),
    )
  })

  it('says what a missed pickup is, in a sentence', async () => {
    clientApi()
    renderApp(<AppRoutes />, { path: '/me' })
    const m = strings.me

    const missed = await screen.findByRole('region', { name: m.missedTitle })
    expect(within(missed).getByText(m.missedNone(30))).toBeInTheDocument()
    expect(within(missed).getByText(m.missedRule(2, 30, 7))).toBeInTheDocument()
  })

  it('changes where the client lives: the district with its town', async () => {
    const api = clientApi({
      'GET /api/v1/places': [{ id: 40, name: 'Antelias' }],
      'PATCH /api/v1/me/profile': CLIENT,
    })
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()
    const f = strings.signUp

    const home = await screen.findByRole('region', { name: strings.me.homeTitle })
    // This client gave an area, so the area is what is shown: the map is the other way.
    expect(within(home).getByRole('radio', { name: strings.where.area })).toBeChecked()
    await within(home).findByRole('option', { name: 'Mount Lebanon' })
    await user.selectOptions(within(home).getByLabelText(f.governorate), 'Mount Lebanon')
    await user.selectOptions(within(home).getByLabelText(f.district), 'Matn')
    await within(home).findByRole('option', { name: 'Antelias' })
    await user.selectOptions(within(home).getByLabelText(f.town), 'Antelias')
    await user.click(within(home).getByRole('button', { name: strings.me.save }))

    await waitFor(() =>
      expect(api.sent('PATCH', '/api/v1/me/profile')[0].body).toEqual({ district_id: 2, home_area_id: 40 }),
    )
  })

  it('saves a place on the map, sent in a body and kept out of the profile', async () => {
    const api = clientApi({ 'PUT /api/v1/me/home-place': { ...CLIENT, client: { ...CLIENT.client, home_place_saved: true } } })
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    const home = await screen.findByRole('region', { name: strings.me.homeTitle })
    await user.click(within(home).getByRole('radio', { name: strings.where.map }))
    // One way or the other: the lists of the area are gone while the map is chosen.
    expect(within(home).queryByLabelText(strings.signUp.governorate)).not.toBeInTheDocument()
    const save = within(home).getByRole('button', { name: strings.me.save })
    expect(save).toBeDisabled()
    await user.click(within(home).getByRole('button', { name: strings.where.openMap }))
    await user.click(await within(home).findByRole('button', { name: 'put the pin' }))
    await user.click(save)

    await waitFor(() =>
      expect(api.sent('PUT', '/api/v1/me/home-place')[0].body).toEqual({ lat: 33.8959, lon: 35.4828 }),
    )
    expect(api.calls.every((call) => !/lat=|lon=/.test(call.path))).toBe(true)
  })

  it('puts the pin where the device is and saves at once, on [Use my location]', async () => {
    const api = clientApi({ 'PUT /api/v1/me/home-place': { ...CLIENT, client: { ...CLIENT.client, home_place_saved: true } } })
    const getCurrentPosition = vi.fn((done: PositionCallback) =>
      done({ coords: { latitude: 33.9012, longitude: 35.5201 } } as GeolocationPosition),
    )
    vi.stubGlobal('navigator', { ...navigator, geolocation: { getCurrentPosition } })
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    const home = await screen.findByRole('region', { name: strings.me.homeTitle })
    await user.click(within(home).getByRole('radio', { name: strings.where.map }))
    // The browser is asked only after the tap.
    expect(getCurrentPosition).not.toHaveBeenCalled()
    await user.click(within(home).getByRole('button', { name: strings.where.useMine }))

    await waitFor(() =>
      expect(api.sent('PUT', '/api/v1/me/home-place')[0].body).toEqual({ lat: 33.9012, lon: 35.5201 }),
    )
    vi.unstubAllGlobals()
  })

  it('says so when the device refuses its location, and saves nothing', async () => {
    const api = clientApi()
    const getCurrentPosition = vi.fn((_done: PositionCallback, failed?: PositionErrorCallback | null) =>
      failed?.({ code: 1 } as GeolocationPositionError),
    )
    vi.stubGlobal('navigator', { ...navigator, geolocation: { getCurrentPosition } })
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    const home = await screen.findByRole('region', { name: strings.me.homeTitle })
    await user.click(within(home).getByRole('radio', { name: strings.where.map }))
    await user.click(within(home).getByRole('button', { name: strings.where.useMine }))

    expect(await within(home).findByText(strings.where.refused)).toBeInTheDocument()
    expect(api.sent('PUT', '/api/v1/me/home-place')).toEqual([])
    vi.unstubAllGlobals()
  })

  it('removes the saved place when the client goes back to an area', async () => {
    const withPlace = { ...CLIENT, client: { ...CLIENT.client, home_place_saved: true } }
    const api = clientApi({
      'GET /api/v1/auth/me': withPlace,
      'GET /api/v1/me/home-place': { lat: 33.8959, lon: 35.4828 },
      'DELETE /api/v1/me/home-place': CLIENT,
      'PATCH /api/v1/me/profile': CLIENT,
    })
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    const home = await screen.findByRole('region', { name: strings.me.homeTitle })
    // A saved place is what the page opens on. The map is not downloaded for it: its
    // pictures come from another company's servers, so the client asks for it first.
    expect(within(home).getByRole('radio', { name: strings.where.map })).toBeChecked()
    expect(await within(home).findByText(strings.where.pinPut)).toBeInTheDocument()
    expect(within(home).getByRole('button', { name: strings.where.showMap })).toBeInTheDocument()
    expect(within(home).queryByRole('button', { name: 'put the pin' })).not.toBeInTheDocument()
    await user.click(within(home).getByRole('radio', { name: strings.where.area }))
    await within(home).findByRole('option', { name: 'Mount Lebanon' })
    await user.click(within(home).getByRole('button', { name: strings.me.save }))

    // A saved place wins over an area when a search starts: keeping both would hide the area.
    await waitFor(() => expect(api.sent('DELETE', '/api/v1/me/home-place')).toHaveLength(1))
    // The area is saved before the place is removed: a failure in between never leaves
    // the client with nowhere a search can start from.
    const changes = api.calls.filter((call) => call.method !== 'GET').map((call) => call.method)
    expect(changes).toEqual(['PATCH', 'DELETE'])
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

describe('Home is what needs the client now (CS-5)', () => {
  it('shows what is watched, and has no search box of its own', async () => {
    clientApi({ 'GET /api/v1/watches': { items: [WATCH], server_now: CONFIG.server_now } })
    renderApp(<AppRoutes />, { path: '/' })

    const watched = await screen.findByRole('link', { name: new RegExp(PRODUCT.name) })
    expect(watched).toHaveAttribute('href', '/medicines')
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(s.label)).not.toBeInTheDocument()
    expect(screen.queryByText(strings.home.nothingReserved)).not.toBeInTheDocument()
  })

  it('shows every reservation to pick up as the same ticket, the nearest deadline first', async () => {
    const later = {
      ...RESERVATION,
      id: 'bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb',
      ref: 'R-42RZCD',
      deadline: '2026-11-18T18:00:00Z',
    }
    clientApi({
      // The later one comes first in the answer: the page puts them in order.
      'GET /api/v1/reservations': {
        items: [later, RESERVATION],
        next_cursor: null,
        server_now: CONFIG.server_now,
      },
    })
    renderApp(<AppRoutes />, { path: '/' })

    const first = await screen.findByRole('region', { name: `${strings.home.pickUp} ${RESERVATION.ref}` })
    const second = screen.getByRole('region', { name: `${strings.home.pickUp} ${later.ref}` })
    for (const [ticket, order] of [
      [first, RESERVATION],
      [second, later],
    ] as const) {
      expect(within(ticket).getByText(order.ref)).toBeInTheDocument()
      expect(within(ticket).getByRole('link', { name: strings.home.showAtCounter })).toHaveAttribute(
        'href',
        `/reservations/${order.id}`,
      )
    }
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('says that nothing is waiting, with the two ways on', async () => {
    clientApi()
    renderApp(<AppRoutes />, { path: '/' })

    expect(await screen.findByText(strings.home.nothingReserved)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: strings.home.goSearch })).toHaveAttribute('href', '/search')
    expect(screen.getByRole('link', { name: strings.home.goAsk })).toHaveAttribute('href', '/assistant')
  })

  it("has Search in the phone's menu", async () => {
    clientApi()
    renderApp(<AppRoutes />, { path: '/' })

    const menu = await screen.findByRole('navigation', { name: strings.nav.label })
    expect(within(menu).getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual([
      '/',
      '/search',
      '/medicines',
      '/assistant',
      '/me',
    ])
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
  const OLD_CHAT = 'cccccccc-1111-4111-8111-cccccccccccc'
  const chatRoutes = {
    'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
    [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([message(1, 'agent', 'Hello.')]),
    [`GET /api/v1/conversations/${OLD_CHAT}/messages`]: {
      ...page([message(1, 'client', 'baddi panadol'), message(2, 'agent', 'Which strength?')]),
      archived: true,
    },
    'GET /api/v1/conversations/chats': {
      items: [
        {
          conversation_id: CHAT_ID,
          active: true,
          started_at: '2026-11-16T08:00:00Z',
          last_activity_at: '2026-11-16T08:00:00Z',
          title: null,
        },
        {
          conversation_id: OLD_CHAT,
          active: false,
          started_at: '2026-11-14T08:00:00Z',
          last_activity_at: '2026-11-14T08:05:00Z',
          title: 'baddi panadol',
        },
      ],
      server_now: CONFIG.server_now,
    },
  }

  it('opens the assistant on a page of its own, never beside another page', async () => {
    wideScreen()
    clientApi(chatRoutes)
    const { container } = renderApp(<AppRoutes />, { path: '/medicines' })
    const user = userEvent.setup()

    await screen.findByRole('heading', { name: strings.medicines.title })
    // No panel (the owner, 2026-11-18): the page has the whole window.
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
    // A bar at the top, and no floating menu made for a thumb.
    expect(container.querySelector('.topbar')).not.toBeNull()
    expect(container.querySelector('.nav')).toBeNull()
    expect(await accessibilityProblems(container)).toEqual([])

    // The top bar's link (an empty list on the page offers one of its own).
    const ask = within(container.querySelector<HTMLElement>('.topbar')!).getByRole('link', {
      name: strings.nav.askAssistant,
    })
    expect(ask).toHaveAttribute('href', '/assistant')
    await user.click(ask)
    expect(await screen.findByText('Hello.')).toBeInTheDocument()
    expect(screen.getByText(strings.chat.aiNotice)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: strings.medicines.title })).not.toBeInTheDocument()
  })

  it('logs out from the account menu of the top bar', async () => {
    wideScreen()
    const api = clientApi({ ...chatRoutes, 'POST /api/v1/auth/logout': answer(204) })
    renderApp(<AppRoutes />, { path: '/medicines' })
    const user = userEvent.setup()

    await screen.findByRole('heading', { name: strings.medicines.title })
    await user.click(screen.getByRole('button', { name: new RegExp(CLIENT.client.first_name) }))
    await user.click(await screen.findByRole('menuitem', { name: strings.me.logOut }))

    await waitFor(() => expect(api.sent('POST', '/api/v1/auth/logout')).toHaveLength(1))
    // Nothing of the person who logged out stays on the screen: the login page is shown,
    // and their pages are gone (found by the break test of 2026-11-18).
    expect(await screen.findByRole('heading', { name: strings.login.title })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: strings.medicines.title })).not.toBeInTheDocument()
    expect(screen.queryByText(new RegExp(CLIENT.client.first_name))).not.toBeInTheDocument()
  })

  it('logs out from the button at the end of the profile too', async () => {
    const api = clientApi({ 'POST /api/v1/auth/logout': answer(204) })
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    expect(await screen.findByText(CLIENT.email)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: strings.me.logOut }))

    await waitFor(() => expect(api.sent('POST', '/api/v1/auth/logout')).toHaveLength(1))
    expect(await screen.findByRole('heading', { name: strings.login.title })).toBeInTheDocument()
    expect(screen.queryByText(CLIENT.email)).not.toBeInTheDocument()
  })

  it('lists the earlier chats beside the conversation, to read and not to write in', async () => {
    wideScreen()
    clientApi(chatRoutes)
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    const chats = await screen.findByRole('complementary', { name: strings.chat.chats })
    await user.click(await within(chats).findByRole('button', { name: /baddi panadol/ }))

    expect(await screen.findByText('Which strength?')).toBeInTheDocument()
    expect(screen.getByText(strings.chat.earlier)).toBeInTheDocument()
    // The box to write in is not there for an earlier chat.
    expect(screen.getByLabelText(strings.chat.messageLabel)).not.toBeVisible()

    await user.click(screen.getByRole('button', { name: strings.chat.backToCurrent }))
    expect(await screen.findByText('Hello.')).toBeInTheDocument()
    expect(screen.getByLabelText(strings.chat.messageLabel)).toBeVisible()
  })

  it('shows one conversation on the assistant\'s own page, never two', async () => {
    wideScreen()
    clientApi(chatRoutes)
    renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText('Hello.')).toBeInTheDocument()
    expect(screen.getAllByLabelText(strings.chat.messageLabel)).toHaveLength(1)
    // Beside it stands the list of chats, not a second conversation.
    expect(screen.queryByRole('complementary', { name: strings.chat.title })).not.toBeInTheDocument()
  })

  it('has no panel at all on a phone: nothing asks for the chat', async () => {
    const api = clientApi(chatRoutes)
    renderApp(<AppRoutes />, { path: '/medicines' })

    expect(await screen.findByRole('heading', { name: strings.medicines.title })).toBeInTheDocument()
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
    expect(api.sent('GET', '/api/v1/conversations')).toEqual([])
  })
})

describe('One computer, two people (docs/09 FS-34)', () => {
  it("shows nothing of the first client when their session ended and another one logs in", async () => {
    const OTHER = { ...CLIENT, id: '99999999-9999-4999-8999-999999999999', email: 'other@example.com', full_name: 'Other Person' }
    let now: 'first' | 'ended' | 'other' = 'first'
    const mine = { items: [RESERVATION], next_cursor: null, server_now: CONFIG.server_now }
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      'GET /api/v1/config/public': CONFIG,
      'GET /api/v1/offers': { items: [], server_now: CONFIG.server_now },
      'GET /api/v1/requests': { items: [], server_now: CONFIG.server_now },
      'GET /api/v1/watches': { items: [], server_now: CONFIG.server_now },
      // The first client's list; then "no session"; then the other client's, which never
      // arrives: whatever the page shows meanwhile comes from its own memory.
      'GET /api/v1/reservations': () =>
        now === 'first' ? mine : now === 'ended' ? refusal(401, 'UNAUTHENTICATED') : new Promise(() => {}),
      'POST /api/v1/auth/login': { me: OTHER, token: 'another-token', expires_at: '2026-11-23T08:00:00Z' },
    })
    renderApp(<AppRoutes />, { path: '/medicines' })
    const user = userEvent.setup()
    expect(await screen.findByText(RESERVATION.ref)).toBeInTheDocument()

    // The session ends while the page is open: the next thing the page asks is refused.
    now = 'ended'
    await user.click(screen.getByRole('tab', { name: strings.medicines.history }))
    expect(await screen.findByRole('heading', { name: strings.login.title })).toBeInTheDocument()

    now = 'other'
    await user.type(screen.getByLabelText(strings.login.email), 'other@example.com')
    await user.type(screen.getByLabelText(strings.login.password), 'A long enough passphrase, 1')
    await user.click(screen.getByRole('button', { name: strings.login.submit }))

    expect(await screen.findByRole('heading', { name: strings.medicines.title })).toBeInTheDocument()
    expect(screen.queryByText(RESERVATION.ref)).not.toBeInTheDocument()
  })
})
