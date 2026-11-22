import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { getToken } from '../../api/client'
import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
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

const m = strings.me
const DELETE = '/api/v1/me/delete-account'

function clientApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/notifications/unread-count': { count: 0 },
    ...more,
  })
}

/** The profile, with "Delete my account" opened. */
async function opened() {
  renderApp(<AppRoutes />, { path: '/me' })
  const user = userEvent.setup()
  const section = await screen.findByRole('region', { name: m.deleteTitle })
  await user.click(within(section).getByRole('button', { name: m.deleteOpen }))
  return { user, section }
}

afterEach(() => window.sessionStorage.clear())

describe('Delete my account (R-AU10)', () => {
  it('is quiet until opened, then says what happens before it asks for the password', async () => {
    const api = clientApi()
    const { container } = renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()

    const section = await screen.findByRole('region', { name: m.deleteTitle })
    expect(within(section).queryByLabelText(new RegExp(m.deletePassword))).toBeNull()
    await user.click(within(section).getByRole('button', { name: m.deleteOpen }))

    // The focus goes into the form, not to the top of the page.
    expect(document.activeElement).toBe(within(section).getByLabelText(new RegExp(m.deletePassword)))
    for (const line of m.deleteLines) expect(within(section).getByText(line)).toBeInTheDocument()
    expect(within(section).getByText(m.deleteFinal)).toBeInTheDocument()
    expect(within(section).getByLabelText(new RegExp(m.deletePassword))).toBeInTheDocument()
    expect(within(section).getByRole('button', { name: m.deleteSubmit })).toHaveClass('pill-button--danger')
    expect(await accessibilityProblems(container)).toEqual([])

    await user.click(within(section).getByRole('button', { name: m.deleteKeep }))
    expect(within(section).queryByLabelText(new RegExp(m.deletePassword))).toBeNull()
    expect(document.activeElement).toBe(within(section).getByRole('button', { name: m.deleteOpen }))
    expect(api.sent('POST', DELETE)).toEqual([])
  })

  it('asks for the password before sending anything', async () => {
    const api = clientApi()
    const { user, section } = await opened()

    await user.click(within(section).getByRole('button', { name: m.deleteSubmit }))

    expect(await within(section).findByText(m.deletePasswordMissing)).toBeInTheDocument()
    expect(document.activeElement).toBe(within(section).getByLabelText(new RegExp(m.deletePassword)))
    expect(api.sent('POST', DELETE)).toEqual([])
  })

  it('says a wrong password on its box, and the client stays logged in', async () => {
    const api = clientApi({ [`POST ${DELETE}`]: refusal(401, 'INVALID_CREDENTIALS') })
    const { user, section } = await opened()
    const box = within(section).getByLabelText(new RegExp(m.deletePassword))

    await user.type(box, 'Not my password 9!')
    await user.click(within(section).getByRole('button', { name: m.deleteSubmit }))

    expect(await within(section).findByText(m.deleteWrong)).toBeInTheDocument()
    expect(api.sent('POST', DELETE)[0].body).toEqual({ password: 'Not my password 9!' })
    expect(document.activeElement).toBe(box)
    expect(getToken()).toBe('a-test-token')
    expect(screen.getByRole('heading', { name: m.title })).toBeInTheDocument()
  })

  it('says how long a locked account waits, and keeps what was typed when DawaLink is busy', async () => {
    const answers = [
      refusal(429, 'ACCOUNT_LOCKED', { retry_after: 600 }),
      refusal(503, 'SERVICE_UNAVAILABLE', { retry_after_s: 1 }),
    ]
    clientApi({ [`POST ${DELETE}`]: () => answers.shift() })
    const { user, section } = await opened()
    const box = within(section).getByLabelText(new RegExp(m.deletePassword))
    await user.type(box, 'My password 9!')

    await user.click(within(section).getByRole('button', { name: m.deleteSubmit }))
    expect(await within(section).findByText(strings.limits.locked(10))).toBeInTheDocument()
    await user.click(within(section).getByRole('button', { name: m.deleteSubmit }))
    expect(await within(section).findByText(strings.limits.busy)).toBeInTheDocument()

    expect(box).toHaveValue('My password 9!')
    expect(getToken()).toBe('a-test-token')
  })

  it('forgets the person, and the welcome page says once that the account is deleted', async () => {
    const api = clientApi({ [`POST ${DELETE}`]: answer(204) })
    const { user, section } = await opened()

    await user.type(within(section).getByLabelText(new RegExp(m.deletePassword)), 'My password 9!')
    await user.click(within(section).getByRole('button', { name: m.deleteSubmit }))

    expect(await screen.findByText(strings.welcome.accountDeleted)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: strings.welcome.title })).toBeInTheDocument()
    expect(getToken()).toBeNull()
    // No log out is asked for: every session of the account already ended.
    expect(api.sent('POST', '/api/v1/auth/logout')).toEqual([])
    await waitFor(() => expect(window.sessionStorage.length).toBe(0))
  })

  it('says it only once: the welcome page shown again is the usual one', async () => {
    window.sessionStorage.setItem('dawalink.accountDeleted', '1')
    pretendApi({ 'GET /api/v1/config/public': CONFIG })
    const first = renderApp(<AppRoutes />, { path: '/welcome' })
    expect(await screen.findByText(strings.welcome.accountDeleted)).toBeInTheDocument()
    first.unmount()

    renderApp(<AppRoutes />, { path: '/welcome' })

    expect(await screen.findByRole('heading', { name: strings.welcome.title })).toBeInTheDocument()
    expect(screen.queryByText(strings.welcome.accountDeleted)).toBeNull()
  })
})
