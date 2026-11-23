import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { strings } from '../strings/en'
import { ADMIN, AUDIT_EVENT, OVERVIEW } from '../test/admin'
import { PHARMACIST, PROFILE } from '../test/pharmacy'
import {
  accessibilityProblems,
  CHAT_ID,
  CLIENT,
  CONFIG,
  DISTRICTS,
  loggedIn,
  page,
  pretendApi,
  renderApp,
  RESERVATION,
} from '../test/render'
import { AppRoutes } from './App'

// The frame around every page: its title, where the focus goes, the skip link (B#19, B#34).

const none = { items: [], next_cursor: null, server_now: CONFIG.server_now }

function aClient() {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/reservations': { ...none, items: [RESERVATION] },
    'GET /api/v1/offers': none,
    'GET /api/v1/requests': none,
    'GET /api/v1/watches': none,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/me/searches': [],
  })
}

describe('Every page names itself (B#19)', () => {
  it("titles the browser's tab with the page's heading", async () => {
    aClient()
    renderApp(<AppRoutes />, { path: '/' })

    await screen.findByRole('heading', { name: strings.home.title })

    await waitFor(() => expect(document.title).toBe(`${strings.home.title} · ${strings.appName}`))
  })

  it('titles a public page too', async () => {
    pretendApi({})
    renderApp(<AppRoutes />, { path: '/login' })

    await screen.findByRole('heading', { name: strings.login.title })

    await waitFor(() => expect(document.title).toBe(`${strings.login.title} · ${strings.appName}`))
  })

  it("moves the focus to the new page's heading after a move, not on the first page", async () => {
    aClient()
    renderApp(<AppRoutes />, { path: '/' })
    await screen.findByRole('heading', { name: strings.home.title })
    expect(document.body).toHaveFocus()

    await userEvent.click(screen.getByRole('link', { name: strings.nav.medicines }))

    const heading = await screen.findByRole('heading', { name: strings.medicines.title })
    await waitFor(() => expect(heading).toHaveFocus())
    await waitFor(() => expect(document.title).toBe(`${strings.medicines.title} · ${strings.appName}`))
  })

  it('leaves the focus where a page put it itself: the box of Search', async () => {
    aClient()
    renderApp(<AppRoutes />, { path: '/' })
    await screen.findByRole('heading', { name: strings.home.title })

    await userEvent.click(screen.getByRole('link', { name: strings.nav.search }))

    await waitFor(() => expect(document.activeElement?.tagName).toBe('INPUT'))
    // Search shows no heading while nothing is chosen: the tab is still named.
    await waitFor(() => expect(document.title).toBe(`${strings.nav.search} · ${strings.appName}`))
  })

  it('names a ticket too', async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      [`GET /api/v1/reservations/${RESERVATION.id}`]: RESERVATION,
    })
    renderApp(<AppRoutes />, { path: `/reservations/${RESERVATION.id}` })

    await screen.findByText('R-7K3Q2F')

    await waitFor(() => expect(document.title).toMatch(new RegExp(` · ${strings.appName}$`)))
  })

  it('never pulls back the focus of someone who went on while the heading was coming', async () => {
    let chatArrives: (chat: unknown) => void = () => {}
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      'GET /api/v1/reservations': none,
      'GET /api/v1/offers': none,
      'GET /api/v1/requests': none,
      'GET /api/v1/watches': none,
      'GET /api/v1/config/public': CONFIG,
      'GET /api/v1/districts': DISTRICTS,
      'GET /api/v1/conversations/active-chat': () =>
        new Promise((resolve) => {
          chatArrives = resolve
        }),
      [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([]),
    })
    renderApp(<AppRoutes />, { path: '/' })
    await screen.findByRole('heading', { name: strings.home.title })
    const user = userEvent.setup()

    await user.click(screen.getByRole('link', { name: strings.nav.ask }))
    await screen.findByText(strings.common.loading)
    await user.tab()
    const skip = screen.getByRole('link', { name: strings.shell.skip })
    expect(skip).toHaveFocus()
    chatArrives({ conversation_id: CHAT_ID, kind: 'chat' })

    await screen.findByRole('heading', { name: strings.chat.title })
    expect(skip).toHaveFocus()
  })
})

describe('Skip to content (B#34)', () => {
  it('is the first stop of the keyboard, and takes it past the menus to the page', async () => {
    aClient()
    const { container } = renderApp(<AppRoutes />, { path: '/' })
    await screen.findByRole('heading', { name: strings.home.title })
    const user = userEvent.setup()

    await user.tab()
    const skip = screen.getByRole('link', { name: strings.shell.skip })
    expect(skip).toHaveFocus()
    await user.keyboard('{Enter}')

    expect(screen.getByRole('main')).toHaveFocus()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it("reaches the assistant's conversation, which is the page's main area", async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      'GET /api/v1/config/public': CONFIG,
      'GET /api/v1/districts': DISTRICTS,
      'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
      [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([]),
    })
    renderApp(<AppRoutes />, { path: '/assistant' })
    await screen.findByText(strings.chat.empty)

    await userEvent.click(screen.getByRole('link', { name: strings.shell.skip }))

    const main = screen.getByRole('main')
    expect(main).toHaveFocus()
    expect(main).toContainElement(screen.getByRole('heading', { name: strings.chat.title }))
    expect(main).toContainElement(screen.getByLabelText(strings.chat.messageLabel))
  })

  it('has a main area on the page that does not exist', async () => {
    pretendApi({})
    renderApp(<AppRoutes />, { path: '/no-such-page' })

    expect(screen.getByRole('main')).toContainElement(screen.getByRole('heading', { name: strings.notFound.title }))
  })
})

describe("The pharmacy's portal and the admin's console (B#19, B#34)", () => {
  it("moves the focus to the new page's heading after a tab of the pharmacy's bar", async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': PHARMACIST,
      'GET /api/v1/pharmacy/me': PROFILE,
      'GET /api/v1/districts': DISTRICTS,
      'GET /api/v1/pharmacy/reservations': { items: [], next_cursor: null, server_now: CONFIG.server_now },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy/settings' })
    await screen.findByRole('heading', { name: strings.pharmacy.settingsPage.title })

    await userEvent.click(screen.getByRole('link', { name: strings.pharmacy.reservations }))

    const heading = await screen.findByRole('heading', { level: 1, name: strings.pharmacy.reservations })
    await waitFor(() => expect(heading).toHaveFocus())
    await waitFor(() => expect(document.title).toBe(`${strings.pharmacy.reservations} · ${strings.appName}`))
    expect(screen.getByRole('main')).toContainElement(heading)
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it("moves the focus to the new page's heading after a tab of the admin's bar", async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': ADMIN,
      'GET /api/v1/config/public': CONFIG,
      'GET /api/v1/admin/overview': OVERVIEW,
      'GET /api/v1/admin/pharmacies': { items: [], next_cursor: null },
      'GET /api/v1/admin/audit': { items: [AUDIT_EVENT], next_cursor: null },
    })
    renderApp(<AppRoutes />, { path: '/admin' })
    await screen.findByRole('heading', { name: strings.admin.pharmacies.title })

    await userEvent.click(screen.getByRole('link', { name: strings.admin.tabs.audit }))

    const heading = await screen.findByRole('heading', { name: strings.admin.audit.title })
    await waitFor(() => expect(heading).toHaveFocus())
    await waitFor(() => expect(document.title).toBe(`${strings.admin.audit.title} · ${strings.appName}`))
  })

  it("has a main area on the admin's page that does not exist", async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': ADMIN,
      'GET /api/v1/config/public': CONFIG,
      'GET /api/v1/admin/overview': OVERVIEW,
    })
    renderApp(<AppRoutes />, { path: '/admin/no-such-page' })

    const heading = await screen.findByRole('heading', { name: strings.notFound.title })
    expect(screen.getByRole('main')).toContainElement(heading)
  })
})
