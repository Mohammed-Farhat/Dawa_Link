import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { strings } from '../strings/en'
import {
  accessibilityProblems,
  answer,
  CLIENT,
  CONFIG,
  DISTRICTS,
  loggedIn,
  pretendApi,
  refusal,
  renderApp,
  RESERVATION,
} from '../test/render'
import { AppRoutes } from './App'

const none = { items: [], next_cursor: null, server_now: CONFIG.server_now }

// The real map needs a browser that draws. Here it is a button that puts the pin.
vi.mock('../features/pharmacy/PinMap', () => ({
  default: ({ onChange }: { onChange: (pin: { lat: number; lon: number }) => void }) => (
    <button type="button" onClick={() => onChange({ lat: 33.8959, lon: 35.4828 })}>
      put the pin
    </button>
  ),
}))

describe('Who sees what', () => {
  it('shows the welcome page to a visitor, with no stock on it', async () => {
    const api = pretendApi({})

    const { container } = renderApp(<AppRoutes />, { path: '/' })

    expect(await screen.findByRole('heading', { name: strings.welcome.title })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: strings.welcome.signUp })).toHaveAttribute('href', '/signup')
    // Nobody is logged in, so the website asks the API for nothing.
    expect(api.calls).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('shows Home to a logged-in client, with the pickup first', async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      'GET /api/v1/reservations': { ...none, items: [RESERVATION] },
    })

    const { container } = renderApp(<AppRoutes />, { path: '/' })

    expect(await screen.findByRole('heading', { name: strings.home.title })).toBeInTheDocument()
    expect(await screen.findByText('R-7K3Q2F')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: strings.home.showAtCounter })).toHaveAttribute(
      'href',
      `/reservations/${RESERVATION.id}`,
    )
    expect(screen.getByRole('navigation', { name: strings.nav.label })).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('sends the login token with every call', async () => {
    loggedIn()
    const api = pretendApi({ 'GET /api/v1/auth/me': CLIENT, 'GET /api/v1/reservations': none })

    renderApp(<AppRoutes />, { path: '/' })
    await screen.findByText(strings.home.nothingReserved)

    expect(api.calls.length).toBeGreaterThanOrEqual(2)
    expect(api.calls.every((call) => call.headers.get('Authorization') === 'Bearer a-test-token')).toBe(true)
  })

  it('goes back to the welcome page when the session has ended', async () => {
    loggedIn()
    pretendApi({ 'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED') })

    renderApp(<AppRoutes />, { path: '/' })

    expect(await screen.findByRole('heading', { name: strings.welcome.title })).toBeInTheDocument()
    expect(window.localStorage.length).toBe(0)
  })

  it('asks an unverified client to confirm their email, and sends the link again', async () => {
    loggedIn()
    const api = pretendApi({
      'GET /api/v1/auth/me': { ...CLIENT, email_verified: false },
      'GET /api/v1/reservations': none,
      'POST /api/v1/auth/verify-email/resend': answer(202, { message: 'ok' }),
    })
    renderApp(<AppRoutes />, { path: '/assistant' })

    await userEvent.click(await screen.findByRole('button', { name: strings.banner.resend }))

    expect(await screen.findByText(strings.banner.resent)).toBeInTheDocument()
    // The assistant itself was never asked for: it needs a confirmed email.
    expect(api.sent('GET', '/api/v1/conversations')).toEqual([])
  })

  it('shows a clear page for an address that does not exist', async () => {
    pretendApi({})
    const { container } = renderApp(<AppRoutes />, { path: '/no-such-page' })

    expect(screen.getByRole('heading', { name: strings.notFound.title })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: strings.notFound.back })).toHaveAttribute('href', '/')
    expect(await accessibilityProblems(container)).toEqual([])
  })
})

describe('Signing up and logging in', () => {
  it('creates an account and says to check the email', async () => {
    const api = pretendApi({
      'GET /api/v1/districts': DISTRICTS,
      'GET /api/v1/places': [
        { id: 40, name: 'Antelias' },
        { id: 41, name: 'Jdeideh' },
      ],
      'POST /api/v1/auth/register/client': answer(202, { message: 'ok' }),
    })
    const s = strings.signUp
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.firstName), 'Nour')
    await user.type(screen.getByLabelText(s.lastName), 'Khoury')
    await user.type(screen.getByLabelText(s.birthDate), '1990-05-17')
    await user.type(screen.getByLabelText(s.email), 'nour@example.com')
    await user.type(screen.getByLabelText(s.password), 'A long enough passphrase, 1')
    // Where the client lives, by area: three lists that follow each other.
    await user.click(screen.getByRole('radio', { name: strings.where.area }))
    await screen.findByRole('option', { name: 'Mount Lebanon' })
    await user.selectOptions(screen.getByLabelText(s.governorate), 'Mount Lebanon')
    await user.selectOptions(screen.getByLabelText(s.district), 'Matn')
    await screen.findByRole('option', { name: 'Antelias' })
    await user.selectOptions(screen.getByLabelText(s.town), 'Antelias')
    await user.click(screen.getByLabelText(s.terms))
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByRole('heading', { name: strings.checkEmail.title })).toBeInTheDocument()
    expect(screen.getByText(strings.checkEmail.body('nour@example.com'))).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/auth/register/client')[0].body).toEqual({
      email: 'nour@example.com',
      password: 'A long enough passphrase, 1',
      first_name: 'Nour',
      middle_name: null,
      last_name: 'Khoury',
      birth_date: '1990-05-17',
      phone: null,
      district_id: 2,
      home_area_id: 40,
      accept_terms: true,
    })
    expect(api.sent('GET', '/api/v1/places')[0].path).toContain('district_id=2')
  })

  it('takes a place on the map instead of an area', async () => {
    const api = pretendApi({
      'GET /api/v1/districts': DISTRICTS,
      'POST /api/v1/auth/register/client': answer(202, { message: 'ok' }),
    })
    const s = strings.signUp
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.firstName), 'Nour')
    await user.type(screen.getByLabelText(s.lastName), 'Khoury')
    await user.type(screen.getByLabelText(s.birthDate), '1990-05-17')
    await user.type(screen.getByLabelText(s.email), 'nour@example.com')
    await user.type(screen.getByLabelText(s.password), 'A long enough passphrase, 1')
    // The map is the first way offered: no governorate, district or town to fill.
    expect(screen.queryByLabelText(s.governorate)).not.toBeInTheDocument()
    // The map itself is not downloaded until the client asks for it (docs/10 §4.3).
    expect(screen.queryByRole('button', { name: 'put the pin' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: strings.where.openMap }))
    await user.click(await screen.findByRole('button', { name: 'put the pin' }))
    await user.click(screen.getByLabelText(s.terms))
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByRole('heading', { name: strings.checkEmail.title })).toBeInTheDocument()
    const sent = api.sent('POST', '/api/v1/auth/register/client')[0].body as Record<string, unknown>
    expect(sent.home_place).toEqual({ lat: 33.8959, lon: 35.4828 })
    expect('district_id' in sent).toBe(false)
    // The place is in the body of a request, never in an address.
    expect(api.calls.every((call) => !/lat=|lon=/.test(call.path))).toBe(true)
  })

  it('ticks each part of the password rule as it is typed', async () => {
    pretendApi({ 'GET /api/v1/districts': DISTRICTS })
    const rules = strings.password.rules
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()
    const met = (rule: string) => screen.getByText(rule).closest('li')?.getAttribute('data-met')

    await user.type(await screen.findByLabelText(strings.signUp.password), 'abc')
    expect([met(rules.small), met(rules.length), met(rules.capital)]).toEqual(['true', 'false', 'false'])

    await user.type(screen.getByLabelText(strings.signUp.password), 'DEFGH12345!')
    for (const rule of Object.values(rules)) expect(met(rule)).toBe('true')
  })

  it('says what is missing next to each field, and sends nothing', async () => {
    const api = pretendApi({ 'GET /api/v1/districts': DISTRICTS })
    const s = strings.signUp
    const { container } = renderApp(<AppRoutes />, { path: '/signup' })

    await userEvent.click(await screen.findByRole('button', { name: s.submit }))

    for (const problem of [s.birthProblem, s.emailProblem, strings.where.problem, s.termsProblem]) {
      expect(screen.getByText(problem)).toBeInTheDocument()
    }
    // The first and the last name each say so.
    expect(screen.getAllByText(s.partProblem)).toHaveLength(2)
    expect(api.sent('POST', '/api/v1/auth/register/client')).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('logs in and opens Home', async () => {
    pretendApi({
      'POST /api/v1/auth/login': { me: CLIENT, token: 'fresh-token', expires_at: '2026-11-23T08:00:00Z' },
      'GET /api/v1/reservations': none,
    })
    const s = strings.login
    renderApp(<AppRoutes />, { path: '/login' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.email), 'nour@example.com')
    await user.type(screen.getByLabelText(s.password), 'a long enough passphrase')
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByRole('heading', { name: strings.home.title })).toBeInTheDocument()
    expect(window.localStorage.getItem('dawalink.token')).toBe('fresh-token')
  })

  it('says one sentence for a wrong email or password', async () => {
    pretendApi({ 'POST /api/v1/auth/login': refusal(401, 'INVALID_CREDENTIALS') })
    const s = strings.login
    renderApp(<AppRoutes />, { path: '/login' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.email), 'nour@example.com')
    await user.type(screen.getByLabelText(s.password), 'not the password')
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(strings.errors.INVALID_CREDENTIALS)
    expect(window.localStorage.length).toBe(0)
  })

  it('confirms the email from the link and logs the client in', async () => {
    const api = pretendApi({
      'POST /api/v1/auth/verify-email': { me: CLIENT, token: 'from-the-link', expires_at: '2026-11-23T08:00:00Z' },
    })

    renderApp(<AppRoutes />, { path: '/verify-email?token=the-token-of-the-email' })

    expect(await screen.findByText(strings.verify.done)).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/auth/verify-email')[0].body).toEqual({
      token: 'the-token-of-the-email',
    })
    expect(window.localStorage.getItem('dawalink.token')).toBe('from-the-link')
  })

  it('says so when the link is no longer valid', async () => {
    pretendApi({ 'POST /api/v1/auth/verify-email': refusal(400, 'TOKEN_INVALID') })

    renderApp(<AppRoutes />, { path: '/verify-email?token=an-old-token-of-an-email' })

    expect(await screen.findByText(new RegExp(strings.verify.failed))).toBeInTheDocument()
  })
})
