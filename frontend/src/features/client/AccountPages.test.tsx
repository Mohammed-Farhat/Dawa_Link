import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useLocation } from 'react-router-dom'

import { getToken } from '../../api/client'
import { AppRoutes } from '../../app/App'
import { errorMessage, strings } from '../../strings/en'
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
} from '../../test/render'

// The real map needs a browser that draws. Here it is a button that puts the pin.
vi.mock('../pharmacy/PinMap', () => ({
  default: ({ onChange }: { onChange: (pin: { lat: number; lon: number }) => void }) => (
    <button type="button" onClick={() => onChange({ lat: 33.8959, lon: 35.4828 })}>
      put the pin
    </button>
  ),
}))

const s = strings.signUp
const REGISTER = '/api/v1/auth/register/client'

type User = ReturnType<typeof userEvent.setup>

/** Fills the sign-up form right, except what `wrong` replaces. */
async function fillSignUp(user: User, wrong: { firstName?: string; phone?: string; pin?: boolean } = {}) {
  await user.type(await screen.findByLabelText(s.firstName), wrong.firstName ?? 'Nour')
  await user.type(screen.getByLabelText(s.lastName), 'Khoury')
  await user.type(screen.getByLabelText(s.birthDate), '1990-05-17')
  if (wrong.phone) await user.type(screen.getByLabelText(s.phone), wrong.phone)
  await user.type(screen.getByLabelText(s.email), 'nour@example.com')
  await user.type(screen.getByLabelText(s.password), 'A long enough passphrase, 1')
  if (wrong.pin !== false) {
    await user.click(screen.getByRole('button', { name: strings.where.openMap }))
    await user.click(await screen.findByRole('button', { name: 'put the pin' }))
  }
  await user.click(screen.getByLabelText(s.terms))
}

describe('Signing up with a mistake (B#2)', () => {
  it('takes the focus to the field to correct, and says how many to check', async () => {
    const api = pretendApi({ 'GET /api/v1/districts': DISTRICTS })
    const { container } = renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()

    await fillSignUp(user, { firstName: '1' })
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(strings.forms.check(1))
    expect(screen.getByLabelText(s.firstName)).toHaveFocus()
    expect(api.sent('POST', REGISTER)).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('takes the focus to "where you live" when only that is missing', async () => {
    pretendApi({ 'GET /api/v1/districts': DISTRICTS })
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()

    await fillSignUp(user, { pin: false })
    await user.click(screen.getByRole('button', { name: s.submit }))

    await waitFor(() => expect(screen.getByText(strings.where.problem)).toHaveFocus())
    expect(screen.getByText(strings.forms.check(1))).toBeInTheDocument()
  })

  it('says what a phone number needs, before sending and when the API refuses it (B#4)', async () => {
    const api = pretendApi({
      'GET /api/v1/districts': DISTRICTS,
      [`POST ${REGISTER}`]: refusal(422, 'VALIDATION_ERROR', { field: 'phone' }),
    })
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()

    await fillSignUp(user, { phone: '71 123' })
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByText(s.phoneProblem)).toBeInTheDocument()
    expect(screen.getByLabelText(s.phone)).toHaveFocus()
    expect(screen.queryByText(errorMessage('VALIDATION_ERROR'))).not.toBeInTheDocument()
    expect(api.sent('POST', REGISTER)).toEqual([])

    // A number the form takes, that the API refuses all the same: the same sentence.
    await user.clear(screen.getByLabelText(s.phone))
    await user.type(screen.getByLabelText(s.phone), '71 123 456')
    await user.click(screen.getByRole('button', { name: s.submit }))
    await waitFor(() => expect(api.sent('POST', REGISTER)).toHaveLength(1))
    expect(await screen.findByText(s.phoneProblem)).toBeInTheDocument()
    expect(screen.getByLabelText(s.phone)).toHaveFocus()
  })

  it('says a refusal of a field the form has no box for above the button (A#35)', async () => {
    pretendApi({
      'GET /api/v1/districts': DISTRICTS,
      [`POST ${REGISTER}`]: refusal(422, 'VALIDATION_ERROR', { field: 'something_else' }),
    })
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()

    await fillSignUp(user)
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(errorMessage('VALIDATION_ERROR'))
  })

  it('never lets a field be longer than the API takes', async () => {
    pretendApi({ 'GET /api/v1/districts': DISTRICTS })
    renderApp(<AppRoutes />, { path: '/signup' })

    expect(await screen.findByLabelText(s.firstName)).toHaveAttribute('maxLength', '40')
    expect(screen.getByLabelText(s.phone)).toHaveAttribute('maxLength', '30')
    expect(screen.getByLabelText(s.email)).toHaveAttribute('maxLength', '320')
    expect(screen.getByLabelText(s.password)).toHaveAttribute('maxLength', '200')
  })

  it('takes the focus into the password box itself when only the password is wrong', async () => {
    const api = pretendApi({ 'GET /api/v1/districts': DISTRICTS })
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()

    await fillSignUp(user)
    await user.clear(screen.getByLabelText(s.password))
    await user.type(screen.getByLabelText(s.password), 'short')
    await user.click(screen.getByRole('button', { name: s.submit }))

    // The library's password box is a frame around the box: the box takes the focus.
    const box = screen.getByLabelText(s.password)
    expect(box.tagName).toBe('INPUT')
    expect(box).toHaveFocus()
    expect(api.sent('POST', REGISTER)).toEqual([])
  })

  it('says a refusal of the password box on that box, never nothing (A#35)', async () => {
    pretendApi({
      'GET /api/v1/districts': DISTRICTS,
      [`POST ${REGISTER}`]: refusal(422, 'VALIDATION_ERROR', { field: 'password' }),
    })
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()

    await fillSignUp(user)
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByText(errorMessage('WEAK_PASSWORD'))).toBeInTheDocument()
    expect(screen.getByLabelText(s.password)).toHaveFocus()
  })

  it('says DawaLink is busy, and keeps everything typed', async () => {
    const api = pretendApi({
      'GET /api/v1/districts': DISTRICTS,
      [`POST ${REGISTER}`]: refusal(503, 'SERVICE_UNAVAILABLE', { retry_after_s: 1 }),
    })
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()

    await fillSignUp(user)
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(strings.limits.busy)
    expect(screen.getByLabelText(s.email)).toHaveValue('nour@example.com')
    expect(screen.getByLabelText(s.password)).toHaveValue('A long enough passphrase, 1')
    expect(screen.getByLabelText(s.terms)).toBeChecked()

    // Pressed again, the same form goes out again.
    await user.click(screen.getByRole('button', { name: s.submit }))
    await waitFor(() => expect(api.sent('POST', REGISTER)).toHaveLength(2))
  })

  it('says the password rule in the password box, for a screen reader (B §7)', async () => {
    pretendApi({ 'GET /api/v1/districts': DISTRICTS })
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()
    const rules = strings.password.rules

    await user.type(await screen.findByLabelText(s.password), 'abc')

    const box = screen.getByLabelText(s.password)
    expect(box).toHaveAccessibleDescription(new RegExp(`^${strings.password.rulesLabel}`))
    expect(box).toHaveAccessibleDescription(expect.stringContaining(`${rules.small} ${strings.password.met}`))
    expect(box).toHaveAccessibleDescription(expect.stringContaining(`${rules.capital} ${strings.password.missing}`))
    // Said, not shown: the list under the box already shows it.
    const described = (box.getAttribute('aria-describedby') ?? '').split(' ').filter(Boolean)
    const said = described.map((id) => document.getElementById(id))
    expect(said.some((element) => element?.classList.contains('sr-only'))).toBe(true)
  })

  it('names the privacy notice above it, not terms that do not exist', () => {
    expect(s.terms).toMatch(/privacy notice/)
    expect(s.terms).not.toMatch(/terms/)
    expect(s.termsProblem).not.toMatch(/terms/)
  })
})

describe('Logging in', () => {
  const l = strings.login

  it('keeps [Log in] on, and says what is missing on its box (B §7)', async () => {
    const api = pretendApi({})
    const { container } = renderApp(<AppRoutes />, { path: '/login' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(l.email), 'nour@example.com')
    const button = screen.getByRole('button', { name: l.submit })
    expect(button).toBeEnabled()
    await user.click(button)

    expect(screen.getByText(l.passwordMissing)).toBeInTheDocument()
    expect(screen.queryByText(l.emailMissing)).not.toBeInTheDocument()
    expect(screen.getByLabelText(l.password)).toHaveFocus()
    expect(await screen.findByRole('alert')).toHaveTextContent(strings.forms.check(1))
    expect(api.sent('POST', '/api/v1/auth/login')).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('never lets a box be longer than the API takes', async () => {
    pretendApi({})
    renderApp(<AppRoutes />, { path: '/login' })

    expect(await screen.findByLabelText(l.email)).toHaveAttribute('maxLength', '320')
    expect(screen.getByLabelText(l.password)).toHaveAttribute('maxLength', '200')
  })

  it("never lets the admins' code be longer than the API takes", async () => {
    pretendApi({ 'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED') })
    renderApp(<AppRoutes />, { path: '/admin/login' })

    expect(await screen.findByLabelText(l.code)).toHaveAttribute('maxLength', '10')
  })

  it("says a wrong code on the admins' login in the one sentence, which names the code too", async () => {
    // The API answers a wrong code exactly like a wrong password, on purpose (R-AU2).
    pretendApi({
      'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED'),
      'POST /api/v1/auth/login': refusal(401, 'INVALID_CREDENTIALS'),
    })
    renderApp(<AppRoutes />, { path: '/admin/login' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(l.email), 'admin@example.com')
    await user.type(screen.getByLabelText(l.password), 'a long enough passphrase')
    await user.type(screen.getByLabelText(l.code), '000000')
    await user.click(screen.getByRole('button', { name: l.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(l.wrongWithCode)
  })

  it("keeps the admins' [Log in] on, and says an empty code on its box", async () => {
    const api = pretendApi({ 'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED') })
    renderApp(<AppRoutes />, { path: '/admin/login' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(l.email), 'admin@example.com')
    await user.type(screen.getByLabelText(l.password), 'a long enough passphrase')
    expect(screen.getByRole('button', { name: l.submit })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: l.submit }))

    expect(screen.getByText(l.codeMissing)).toBeInTheDocument()
    expect(screen.getByLabelText(l.code)).toHaveFocus()
    expect(api.sent('POST', '/api/v1/auth/login')).toEqual([])
  })

  it('says a refused box as the one sentence of a wrong login, never nothing (A#35)', async () => {
    pretendApi({ 'POST /api/v1/auth/login': refusal(422, 'VALIDATION_ERROR', { field: 'email' }) })
    renderApp(<AppRoutes />, { path: '/login' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(l.email), 'nour@example.com')
    await user.type(screen.getByLabelText(l.password), 'not the password')
    await user.click(screen.getByRole('button', { name: l.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(errorMessage('INVALID_CREDENTIALS'))
  })

  it('says how long a locked account waits', async () => {
    pretendApi({ 'POST /api/v1/auth/login': refusal(429, 'ACCOUNT_LOCKED', { retry_after: 600 }) })
    renderApp(<AppRoutes />, { path: '/login' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(l.email), 'nour@example.com')
    await user.type(screen.getByLabelText(l.password), 'not the password')
    await user.click(screen.getByRole('button', { name: l.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(strings.limits.locked(10))
  })

  it('says DawaLink is busy, and keeps what was typed', async () => {
    pretendApi({ 'POST /api/v1/auth/login': refusal(503, 'SERVICE_UNAVAILABLE', { retry_after_s: 1 }) })
    renderApp(<AppRoutes />, { path: '/login' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(l.email), 'nour@example.com')
    await user.type(screen.getByLabelText(l.password), 'A long enough passphrase, 1')
    await user.click(screen.getByRole('button', { name: l.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(strings.limits.busy)
    expect(screen.getByLabelText(l.email)).toHaveValue('nour@example.com')
    expect(screen.getByLabelText(l.password)).toHaveValue('A long enough passphrase, 1')
  })
})

describe('A confirmation link that works', () => {
  it('logs out whoever was logged in on this browser, and offers [Log in]', async () => {
    // The server ended every session of the account: the log out is answered "ended".
    loggedIn()
    const api = pretendApi({
      'GET /api/v1/auth/me': { ...CLIENT, email_verified: false },
      'POST /api/v1/auth/verify-email': answer(204),
      'POST /api/v1/auth/logout': refusal(401, 'UNAUTHENTICATED'),
    })
    const { container } = renderApp(
      <>
        <AppRoutes />
        <Address />
      </>,
      { path: '/verify-email?token=a-fresh-token-of-an-email' },
    )

    expect(await screen.findByText(strings.verify.done)).toBeInTheDocument()
    await waitFor(() => expect(getToken()).toBeNull())
    expect(api.sent('POST', '/api/v1/auth/logout')).toHaveLength(1)
    expect(screen.getByLabelText('address')).toHaveTextContent(/^\/verify-email$/)
    expect(screen.getByRole('link', { name: strings.verify.logIn })).toHaveAttribute('href', '/login')
    expect(strings.verify.done).toMatch(/Log in/)
    expect(await accessibilityProblems(container)).toEqual([])
  })
})

describe('A confirmation link that no longer works', () => {
  it('says what to do whether the email is already confirmed or not, with [Log in]', async () => {
    pretendApi({ 'POST /api/v1/auth/verify-email': refusal(400, 'TOKEN_INVALID') })
    renderApp(<AppRoutes />, { path: '/verify-email?token=a-used-token-of-an-email' })

    expect(await screen.findByText(new RegExp(strings.verify.failed))).toBeInTheDocument()
    expect(strings.verify.failedHint).toMatch(/already confirmed, just log in/)
    expect(strings.verify.failedHint).toContain(strings.banner.resend)
    expect(screen.getByRole('link', { name: strings.login.submit })).toHaveAttribute('href', '/login')
  })
})

describe('The name in the same order everywhere (B#30)', () => {
  const order: string[] = [s.firstName, s.middleName, s.lastName]
  const labels = (scope: HTMLElement) =>
    within(scope)
      .getAllByRole('textbox')
      .map((box) => (box as HTMLInputElement).labels?.[0]?.textContent?.trim())
      .filter((label) => label !== undefined && order.includes(label))

  it('is First, Middle (optional), Last on the sign-up form', async () => {
    pretendApi({ 'GET /api/v1/districts': DISTRICTS })
    renderApp(<AppRoutes />, { path: '/signup' })

    await screen.findByLabelText(s.firstName)
    expect(labels(document.body)).toEqual(order)
    expect(s.middleName).toMatch(/optional/i)
  })

  it('is the same in the profile', async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      'GET /api/v1/districts': DISTRICTS,
      'GET /api/v1/config/public': CONFIG,
      'GET /api/v1/notifications/unread-count': { count: 0 },
    })
    renderApp(<AppRoutes />, { path: '/me' })

    const details = await screen.findByRole('region', { name: strings.me.profile })
    expect(labels(details)).toEqual(order)
  })
})

describe('The profile', () => {
  function profileApi(more: Record<string, unknown> = {}) {
    loggedIn()
    return pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      'GET /api/v1/districts': DISTRICTS,
      'GET /api/v1/config/public': CONFIG,
      'GET /api/v1/notifications/unread-count': { count: 0 },
      ...more,
    })
  }
  const phoneBox = (details: HTMLElement) =>
    within(details).getByLabelText(new RegExp(`^${strings.me.phone.replace(/[()]/g, '\\$&')}`))

  it('says what a phone number needs, and sends nothing (B#4)', async () => {
    const api = profileApi()
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    const details = await screen.findByRole('region', { name: strings.me.profile })
    await user.type(phoneBox(details), 'call me')
    await user.click(within(details).getByRole('button', { name: strings.me.save }))

    expect(await within(details).findByText(s.phoneProblem)).toBeInTheDocument()
    expect(phoneBox(details)).toHaveFocus()
    expect(api.sent('PATCH', '/api/v1/me/profile')).toEqual([])
  })

  it('never lets a box be longer than the API takes', async () => {
    profileApi()
    renderApp(<AppRoutes />, { path: '/me' })

    const details = await screen.findByRole('region', { name: strings.me.profile })
    expect(within(details).getByLabelText(s.firstName)).toHaveAttribute('maxLength', '40')
    expect(within(details).getByLabelText(s.lastName)).toHaveAttribute('maxLength', '40')
    expect(phoneBox(details)).toHaveAttribute('maxLength', '30')
  })

  it('says a refusal of a box it does not have, instead of nothing (A#35)', async () => {
    profileApi({ 'PATCH /api/v1/me/profile': refusal(422, 'VALIDATION_ERROR', { field: 'alternatives_ok_default' }) })
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    const details = await screen.findByRole('region', { name: strings.me.profile })
    await user.click(within(details).getByRole('button', { name: strings.me.save }))

    expect(await within(details).findByText(errorMessage('VALIDATION_ERROR'))).toBeInTheDocument()
  })

  it('says how long to wait when places were changed too often', async () => {
    profileApi({
      'PUT /api/v1/me/home-place': refusal(429, 'RATE_LIMITED', { retry_after_s: 1200 }),
      'DELETE /api/v1/me/home-place': answer(204),
    })
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    const home = await screen.findByRole('region', { name: strings.me.homeTitle })
    await user.click(within(home).getByRole('radio', { name: strings.where.map }))
    await user.click(within(home).getByRole('button', { name: strings.where.openMap }))
    await user.click(await within(home).findByRole('button', { name: 'put the pin' }))
    await user.click(within(home).getByRole('button', { name: strings.me.save }))

    expect(await within(home).findByText(strings.limits.tryInMinutes(20))).toBeInTheDocument()
  })
})

describe('After signing up', () => {
  it('says what to do if the email does not come (B#33)', async () => {
    pretendApi({})
    renderApp(<AppRoutes />, { path: '/check-email' })

    expect(await screen.findByText(strings.checkEmail.noEmail)).toBeInTheDocument()
    expect(strings.checkEmail.noEmail).toContain(strings.banner.resend)
  })
})

/** Shows the address the router is at, to see what a page left in it. */
function Address() {
  const { pathname, search } = useLocation()
  return <output aria-label="address">{pathname + search}</output>
}

describe('Forgot your password? (R-AU9)', () => {
  const f = strings.forgot
  const FORGOT = '/api/v1/auth/password/forgot'

  it("is a link on the login page, never on the admins' login", async () => {
    pretendApi({ 'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED') })
    const { unmount } = renderApp(<AppRoutes />, { path: '/login' })

    expect(await screen.findByRole('link', { name: strings.login.forgot })).toHaveAttribute(
      'href',
      '/forgot-password',
    )
    unmount()

    renderApp(<AppRoutes />, { path: '/admin/login' })
    await screen.findByLabelText(strings.login.code)
    expect(screen.queryByRole('link', { name: strings.login.forgot })).not.toBeInTheDocument()
  })

  it('says the same sentence whatever the email, and that an unconfirmed one signs up again', async () => {
    const api = pretendApi({ [`POST ${FORGOT}`]: answer(202, { message: 'whatever the API says' }) })
    const { container } = renderApp(<AppRoutes />, { path: '/forgot-password' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(strings.login.email), ' nour@example.com ')
    await user.click(screen.getByRole('button', { name: f.submit }))

    expect(await screen.findByText(f.sent)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(f.neverConfirmed))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: f.signUp })).toHaveAttribute('href', '/signup')
    expect(api.sent('POST', FORGOT).map((call) => call.body)).toEqual([{ email: 'nour@example.com' }])
    expect(f.sent).toMatch(/If this email has an account/)
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('says what is missing on the box, and sends nothing', async () => {
    const api = pretendApi({})
    const { container } = renderApp(<AppRoutes />, { path: '/forgot-password' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: f.submit }))

    expect(screen.getByText(strings.login.emailMissing)).toBeInTheDocument()
    expect(screen.getByLabelText(strings.login.email)).toHaveFocus()
    expect(api.sent('POST', FORGOT)).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('says how long to wait after too many asks, never "tomorrow"', async () => {
    pretendApi({ [`POST ${FORGOT}`]: refusal(429, 'RATE_LIMITED', { retry_after_s: 3601 }) })
    renderApp(<AppRoutes />, { path: '/forgot-password' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(strings.login.email), 'nour@example.com')
    await user.click(screen.getByRole('button', { name: f.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(strings.limits.tryInMinutes(60))
    expect(screen.queryByText(f.sent)).not.toBeInTheDocument()
    expect(screen.getByLabelText(strings.login.email)).toHaveValue('nour@example.com')
  })

  it('is open to someone logged in too, and asks for the link the same way', async () => {
    // The reset page's [Send me a new link] leads here, whoever is logged in.
    loggedIn()
    const api = pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      [`POST ${FORGOT}`]: answer(202, { message: 'whatever the API says' }),
    })
    renderApp(
      <>
        <AppRoutes />
        <Address />
      </>,
      { path: '/forgot-password' },
    )
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(strings.login.email), 'nour@example.com')
    expect(screen.getByRole('heading', { name: f.title })).toBeInTheDocument()
    expect(screen.getByLabelText('address')).toHaveTextContent(/^\/forgot-password$/)
    await user.click(screen.getByRole('button', { name: f.submit }))

    expect(await screen.findByText(f.sent)).toBeInTheDocument()
    expect(api.sent('POST', FORGOT).map((call) => call.body)).toEqual([{ email: 'nour@example.com' }])
  })
})

describe('The link of the reset email (R-AU9)', () => {
  const r = strings.reset
  const RESET = '/api/v1/auth/password/reset'
  const TOKEN = 'a-reset-token-from-the-email'
  // Where the page keeps the link's token for a reload (this tab's storage only).
  const KEPT = 'dawalink.resetToken'

  beforeEach(() => window.sessionStorage.clear())

  function open(routes: Parameters<typeof pretendApi>[0] = {}) {
    const api = pretendApi(routes)
    const rendered = renderApp(
      <>
        <AppRoutes />
        <Address />
      </>,
      { path: `/reset-password?token=${TOKEN}` },
    )
    return { api, ...rendered }
  }

  it('takes the token out of the address at once, and sends it with the new password', async () => {
    const { api, container } = open({ [`POST ${RESET}`]: answer(204) })
    const user = userEvent.setup()

    await waitFor(() => expect(screen.getByLabelText('address')).toHaveTextContent(/^\/reset-password$/))
    await user.type(screen.getByLabelText(r.password), 'A brand new passphrase, 3')
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByText(r.done)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: r.logIn })).toHaveAttribute('href', '/login')
    expect(api.sent('POST', RESET).map((call) => call.body)).toEqual([
      { token: TOKEN, new_password: 'A brand new passphrase, 3' },
    ])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('shows the rule as the sign-up does, and sends nothing until it is met', async () => {
    const { api, container } = open()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(r.password), 'short')
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(screen.getByLabelText(r.password)).toHaveAccessibleDescription(
      new RegExp(`^${strings.password.rulesLabel}`),
    )
    expect(screen.getByLabelText(r.password)).toHaveFocus()
    expect(screen.getByText(errorMessage('WEAK_PASSWORD'))).toBeInTheDocument()
    expect(api.sent('POST', RESET)).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('says a common password on its box, and the link can still be used', async () => {
    let tries = 0
    open({
      [`POST ${RESET}`]: () => {
        tries += 1
        return tries === 1 ? refusal(422, 'WEAK_PASSWORD', { missing: ['uncommon'] }) : answer(204)
      },
    })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(r.password), 'Password123!')
    await user.click(screen.getByRole('button', { name: r.submit }))
    expect(await screen.findByText(strings.password.common)).toBeInTheDocument()

    await user.clear(screen.getByLabelText(r.password))
    await user.type(screen.getByLabelText(r.password), 'A brand new passphrase, 3')
    await user.click(screen.getByRole('button', { name: r.submit }))
    expect(await screen.findByText(r.done)).toBeInTheDocument()
  })

  it('says a link that no longer works, and offers a new one', async () => {
    const { container } = open({ [`POST ${RESET}`]: refusal(400, 'TOKEN_INVALID') })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(r.password), 'A brand new passphrase, 3')
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByText(new RegExp(r.failed))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: r.askAgain })).toHaveAttribute('href', '/forgot-password')
    expect(screen.queryByLabelText(r.password)).not.toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('says so at once for an address with no token', async () => {
    pretendApi({})
    renderApp(<AppRoutes />, { path: '/reset-password' })

    expect(await screen.findByText(new RegExp(r.failed))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: r.askAgain })).toBeInTheDocument()
  })

  it('is shown to someone logged in, who is logged out once the password is set', async () => {
    loggedIn()
    const { api } = open({
      'GET /api/v1/auth/me': CLIENT,
      [`POST ${RESET}`]: answer(204),
      'POST /api/v1/auth/logout': answer(204),
    })
    const user = userEvent.setup()

    // The link's own page, never the logged-in person's Home.
    await user.type(await screen.findByLabelText(r.password), 'A brand new passphrase, 3')
    expect(screen.getByLabelText('address')).toHaveTextContent(/^\/reset-password$/)
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByText(r.done)).toBeInTheDocument()
    expect(getToken()).toBeNull()
    expect(api.sent('POST', '/api/v1/auth/logout')).toHaveLength(1)
    expect(api.sent('POST', RESET).map((call) => call.body)).toEqual([
      { token: TOKEN, new_password: 'A brand new passphrase, 3' },
    ])
  })

  it('logs out the very account whose password was reset, whose session already ended', async () => {
    // The reset ended every session of the account: the log out is answered "ended".
    loggedIn()
    open({
      'GET /api/v1/auth/me': CLIENT,
      [`POST ${RESET}`]: answer(204),
      'POST /api/v1/auth/logout': refusal(401, 'UNAUTHENTICATED'),
    })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(r.password), 'A brand new passphrase, 3')
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByText(r.done)).toBeInTheDocument()
    expect(getToken()).toBeNull()
    expect(screen.getByLabelText('address')).toHaveTextContent(/^\/reset-password$/)
    expect(screen.getByRole('link', { name: r.logIn })).toHaveAttribute('href', '/login')
  })

  it('keeps the link through a reload of the page, in this tab only', async () => {
    const { unmount } = open({})
    await waitFor(() => expect(screen.getByLabelText('address')).toHaveTextContent(/^\/reset-password$/))
    expect(window.sessionStorage.getItem(KEPT)).toBe(TOKEN)
    expect(window.localStorage.getItem(KEPT)).toBeNull()
    unmount()

    // A reload: the address has no token any more, the tab's storage still has it.
    window.sessionStorage.setItem(KEPT, TOKEN)
    const api = pretendApi({ [`POST ${RESET}`]: answer(204) })
    renderApp(<AppRoutes />, { path: '/reset-password' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(r.password), 'A brand new passphrase, 3')
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByText(r.done)).toBeInTheDocument()
    expect(api.sent('POST', RESET).map((call) => call.body)).toEqual([
      { token: TOKEN, new_password: 'A brand new passphrase, 3' },
    ])
    expect(window.sessionStorage.getItem(KEPT)).toBeNull()
  })

  it('forgets a refused link at once', async () => {
    open({ [`POST ${RESET}`]: refusal(400, 'TOKEN_INVALID') })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(r.password), 'A brand new passphrase, 3')
    expect(window.sessionStorage.getItem(KEPT)).toBe(TOKEN)
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByText(new RegExp(r.failed))).toBeInTheDocument()
    expect(window.sessionStorage.getItem(KEPT)).toBeNull()
  })

  it('says DawaLink is busy, and keeps what was typed', async () => {
    open({ [`POST ${RESET}`]: refusal(503, 'SERVICE_UNAVAILABLE', { retry_after_s: 1 }) })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(r.password), 'A brand new passphrase, 3')
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(strings.limits.busy)
    expect(screen.getByLabelText(r.password)).toHaveValue('A brand new passphrase, 3')
  })
})

describe('Location radio keyboard pattern (I-02)', () => {
  it('uses one tab stop and wraps arrow selection without asking for location or saving', async () => {
    const locate = vi.fn()
    vi.stubGlobal('navigator', Object.assign(Object.create(navigator), { geolocation: { getCurrentPosition: locate } }))
    const api = pretendApi({ 'GET /api/v1/districts': DISTRICTS })
    renderApp(<AppRoutes />, { path: '/signup' })
    const user = userEvent.setup()
    const map = await screen.findByRole('radio', { name: strings.where.map })
    const area = screen.getByRole('radio', { name: strings.where.area })
    map.focus()
    expect(map).toHaveAttribute('tabindex', '0')
    expect(area).toHaveAttribute('tabindex', '-1')
    await user.keyboard('{ArrowRight}')
    expect(area).toHaveFocus()
    expect(area).toHaveAttribute('aria-checked', 'true')
    await user.keyboard('{ArrowDown}')
    expect(map).toHaveFocus()
    expect(map).toHaveAttribute('aria-checked', 'true')
    await user.keyboard('{ArrowLeft}')
    expect(area).toHaveFocus()
    expect(locate).not.toHaveBeenCalled()
    expect(api.calls.filter((call) => call.method !== 'GET')).toHaveLength(0)
    vi.unstubAllGlobals()
  })
})
