import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/App'
import { strings } from '../strings/en'
import {
  answer,
  CLIENT,
  CONFIG,
  loggedIn,
  pretendApi,
  refusal,
  renderApp,
  RESERVATION,
} from '../test/render'
import { api, failureFrom, formField, getToken, LOGGED_OUT_EVENT, setToken, TOKEN_KEY, unwrap } from './client'
import { useSession } from './session'

const none = { items: [], next_cursor: null, server_now: CONFIG.server_now }

/** The person's own pages: Home, and the profile with Change password. */
const HOME_ROUTES = {
  'GET /api/v1/reservations': { ...none, items: [RESERVATION] },
  'GET /api/v1/offers': none,
  'GET /api/v1/requests': none,
  'GET /api/v1/watches': none,
  'GET /api/v1/config/public': CONFIG,
  'GET /api/v1/notifications/unread-count': { count: 0 },
}

function anotherTab(oldValue: string | null, newValue: string | null) {
  window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, oldValue, newValue }))
}

describe('Who is logged in, when the API is out of reach (A#8)', () => {
  it('says it is retrying, never sends a logged-in client to the welcome page, and comes back', async () => {
    loggedIn()
    const api = pretendApi({ 'GET /api/v1/auth/me': CLIENT, ...HOME_ROUTES })
    api.spy.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    renderApp(<AppRoutes />, { path: '/' })

    expect(await screen.findByText(strings.banner.offline)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: strings.welcome.title })).not.toBeInTheDocument()
    expect(getToken()).toBe('a-test-token')
    // Asked again after a pause: the API answers, and Home is there.
    expect(await screen.findByRole('heading', { name: strings.home.title })).toBeInTheDocument()
    expect(screen.queryByText(strings.banner.offline)).not.toBeInTheDocument()
  })

  it('takes a failing API for the same thing, never for a log out', async () => {
    loggedIn()
    let first = true
    pretendApi({
      'GET /api/v1/auth/me': () => {
        if (!first) return CLIENT
        first = false
        return refusal(503, 'SERVICE_UNAVAILABLE')
      },
      ...HOME_ROUTES,
    })

    renderApp(<AppRoutes />, { path: `/reservations/${RESERVATION.id}` })

    expect(await screen.findByText(strings.banner.offline)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: strings.login.title })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText(strings.banner.offline)).not.toBeInTheDocument())
    expect(getToken()).toBe('a-test-token')
  })

  it('shows "Loading…" while it asks, never a blank page', async () => {
    loggedIn()
    pretendApi({ 'GET /api/v1/auth/me': () => new Promise(() => {}) })

    renderApp(<AppRoutes />, { path: '/' })

    expect(screen.getByText(strings.common.loading)).toBeInTheDocument()
  })

  it('keeps the page when asking again later fails', async () => {
    loggedIn()
    const api = pretendApi({ 'GET /api/v1/auth/me': CLIENT, ...HOME_ROUTES })
    function AskAgain() {
      const { refresh } = useSession()
      return (
        <button type="button" onClick={() => void refresh()}>
          ask again
        </button>
      )
    }
    renderApp(
      <>
        <AppRoutes />
        <AskAgain />
      </>,
      { path: '/' },
    )
    await screen.findByText('R-7K3Q2F')

    api.spy.mockRejectedValue(new TypeError('Failed to fetch'))
    await userEvent.click(screen.getByRole('button', { name: 'ask again' }))

    await waitFor(() => expect(api.spy.mock.calls.length).toBeGreaterThan(api.calls.length))
    expect(screen.getByText('R-7K3Q2F')).toBeInTheDocument()
    expect(screen.queryByText(strings.banner.offline)).not.toBeInTheDocument()
  })
})

describe('Only the API ends a session (A#11)', () => {
  it('says a wrong current password on its field, and the person stays logged in', async () => {
    loggedIn()
    const api = pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      ...HOME_ROUTES,
      'GET /api/v1/me/home-place': answer(404, null),
      'POST /api/v1/auth/password': refusal(401, 'INVALID_CREDENTIALS'),
    })
    const s = strings.password
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.current), 'not my password')
    await user.type(screen.getByLabelText(s.new), 'A long enough passphrase, 1')
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByText(s.wrong)).toBeInTheDocument()
    expect(screen.getByLabelText(s.current)).toHaveFocus()
    expect(getToken()).toBe('a-test-token')
    expect(screen.queryByRole('heading', { name: strings.welcome.title })).not.toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/auth/password')).toHaveLength(1)
  })

  it('asks for the current password on its own field, and sends nothing', async () => {
    loggedIn()
    const api = pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      ...HOME_ROUTES,
      'GET /api/v1/me/home-place': answer(404, null),
    })
    const s = strings.password
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.new), 'A long enough passphrase, 1')
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(screen.getByText(s.currentMissing)).toBeInTheDocument()
    expect(screen.queryByText(strings.errors.WEAK_PASSWORD)).not.toBeInTheDocument()
    expect(screen.getByLabelText(s.current)).toHaveFocus()
    expect(api.sent('POST', '/api/v1/auth/password')).toEqual([])
  })

  it('says how long a locked account waits, and the person stays logged in', async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      ...HOME_ROUTES,
      'GET /api/v1/me/home-place': answer(404, null),
      'POST /api/v1/auth/password': refusal(429, 'ACCOUNT_LOCKED', { retry_after: 841 }),
    })
    const s = strings.password
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.current), 'not my password')
    await user.type(screen.getByLabelText(s.new), 'A long enough passphrase, 1')
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByText(strings.limits.locked(15))).toBeInTheDocument()
    expect(getToken()).toBe('a-test-token')
    expect(screen.getByRole('heading', { name: strings.me.title })).toBeInTheDocument()
  })

  it('says DawaLink is busy, and keeps both passwords typed', async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      ...HOME_ROUTES,
      'GET /api/v1/me/home-place': answer(404, null),
      'POST /api/v1/auth/password': refusal(503, 'SERVICE_UNAVAILABLE', { retry_after_s: 1 }),
    })
    const s = strings.password
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.current), 'my old passphrase, 1A')
    await user.type(screen.getByLabelText(s.new), 'A long enough passphrase, 1')
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByText(strings.limits.busy)).toBeInTheDocument()
    expect(screen.getByLabelText(s.current)).toHaveValue('my old passphrase, 1A')
    expect(screen.getByLabelText(s.new)).toHaveValue('A long enough passphrase, 1')
    // The new password's box says its rule, and that the other devices are logged out.
    expect(screen.getByLabelText(s.new)).toHaveAccessibleDescription(expect.stringContaining(s.hint))
    expect(screen.getByLabelText(s.new)).toHaveAccessibleDescription(
      expect.stringContaining(`${s.rules.symbol} ${s.met}`),
    )
  })

  it('logs out on the API\'s "session ended", and not for another 401', async () => {
    const ended = vi.fn()
    window.addEventListener(LOGGED_OUT_EVENT, ended)
    setToken('a-test-token')
    pretendApi({
      'POST /api/v1/auth/password': refusal(401, 'INVALID_CREDENTIALS'),
      'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED'),
    })

    await unwrap(api.POST('/api/v1/auth/password', { body: { current_password: 'x', new_password: 'y' } })).catch(
      () => null,
    )
    expect(getToken()).toBe('a-test-token')
    expect(ended).not.toHaveBeenCalled()

    await unwrap(api.GET('/api/v1/auth/me')).catch(() => null)
    expect(getToken()).toBeNull()
    expect(ended).toHaveBeenCalledTimes(1)
    window.removeEventListener(LOGGED_OUT_EVENT, ended)
  })

  it("never logs out the person who logged in while an answer for the one before was on its way", async () => {
    setToken('the-one-before')
    pretendApi({
      'GET /api/v1/auth/me': () => {
        setToken('the-new-one') // a login in another tab, while this call was out
        return refusal(401, 'UNAUTHENTICATED')
      },
    })

    await unwrap(api.GET('/api/v1/auth/me')).catch(() => null)

    expect(getToken()).toBe('the-new-one')
  })
})

describe('Another tab (A#33)', () => {
  it('logs this tab out when another one logs out', async () => {
    loggedIn()
    pretendApi({ 'GET /api/v1/auth/me': CLIENT, ...HOME_ROUTES })
    renderApp(<AppRoutes />, { path: '/' })
    await screen.findByText('R-7K3Q2F')

    window.localStorage.removeItem(TOKEN_KEY)
    anotherTab('a-test-token', null)

    expect(await screen.findByRole('heading', { name: strings.welcome.title })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: strings.home.title })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: strings.home.showAtCounter })).not.toBeInTheDocument()
  })

  it("asks who is there when another tab logs in as someone else, and drops the first person's pages", async () => {
    loggedIn()
    const someoneElse = { ...CLIENT, id: '77777777-7777-4777-8777-777777777777', full_name: 'Rami Haddad' }
    const api = pretendApi({
      'GET /api/v1/auth/me': (call: { headers: Headers }) =>
        call.headers.get('Authorization') === 'Bearer another-token' ? someoneElse : CLIENT,
      ...HOME_ROUTES,
      'GET /api/v1/reservations': (call: { headers: Headers }) =>
        call.headers.get('Authorization') === 'Bearer another-token' ? none : { ...none, items: [RESERVATION] },
    })
    renderApp(<AppRoutes />, { path: '/' })
    await screen.findByText('R-7K3Q2F')

    setToken('another-token')
    anotherTab('a-test-token', 'another-token')

    expect(await screen.findByText(strings.home.nothingReserved)).toBeInTheDocument()
    expect(screen.queryByText('R-7K3Q2F')).not.toBeInTheDocument()
    expect(api.sent('GET', '/api/v1/auth/me').at(-1)?.headers.get('Authorization')).toBe('Bearer another-token')
  })

  it('follows a cleared storage too', async () => {
    loggedIn()
    pretendApi({ 'GET /api/v1/auth/me': CLIENT, ...HOME_ROUTES })
    renderApp(<AppRoutes />, { path: '/' })
    await screen.findByText('R-7K3Q2F')

    window.localStorage.clear()
    window.dispatchEvent(new StorageEvent('storage', { key: null }))

    expect(await screen.findByRole('heading', { name: strings.welcome.title })).toBeInTheDocument()
  })
})

describe('A refused field is named the way the forms name it (A#35)', () => {
  it('reads the field of a body the API refused', () => {
    const body = {
      error: {
        code: 'VALIDATION_ERROR',
        details: { fields: [{ field: 'phone', problem: 'String should have at most 30 characters' }] },
      },
    }

    const failure = failureFrom(body, 422)

    expect(failure.details.field).toBe('phone')
    expect(failure.details.fields).toEqual(body.error.details.fields)
  })

  it('keeps the field a rule named', () => {
    const failure = failureFrom({ error: { code: 'PHONE_TAKEN', details: { field: 'phone' } } }, 409)

    expect(failure.details.field).toBe('phone')
  })

  it.each([
    ['phone', 'phone'],
    ['pharmacy.name', 'name'],
    ['pharmacy.location.lat', 'location'],
    ['pharmacy.hours[3].open', 'hours'],
    ['hours[0].close', 'hours'],
    ['home_place.lon', 'home_place'],
    ['body', null],
  ])('gives "%s" to the form as %s', (path, field) => {
    expect(formField(path)).toBe(field)
  })
})
