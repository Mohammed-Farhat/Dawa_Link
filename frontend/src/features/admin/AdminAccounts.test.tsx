import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
import {
  ADMIN,
  CATALOG_ROW,
  CLIENT_DETAIL,
  CLIENT_ROW,
  CONTESTED_ID,
  ESCALATION_DETAIL,
  ESCALATION_ID,
  FLAG,
  HEALTH,
  OVERVIEW,
  PHARMACY_ID,
  WAITING,
} from '../../test/admin'
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

vi.mock('../pharmacy/PinMap', () => ({ default: () => <div>the map</div> }))

const s = strings.admin
const one = s.pharmacy
const c = s.clients
const f = s.flags
const h = s.health

const PHARMACY = `/api/v1/admin/pharmacies/${PHARMACY_ID}`
const A_CLIENT = `/api/v1/admin/clients/${CLIENT.id}`
const APPROVED = { ...WAITING, status: 'APPROVED', pin_checked: true }

function adminApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': ADMIN,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/admin/overview': { ...OVERVIEW, contests_waiting: 1, flags_open: 1, flags_high: 1 },
    [`GET ${PHARMACY}`]: APPROVED,
    'GET /api/v1/admin/clients': { items: [CLIENT_ROW], next_cursor: null },
    [`GET ${A_CLIENT}`]: CLIENT_DETAIL,
    'GET /api/v1/admin/catalog/products': { items: [CATALOG_ROW], next_cursor: null },
    'GET /api/v1/admin/catalog/imports': {
      items: [
        {
          id: 'import-1',
          file_name: 'prices.xls',
          source_date: '2026-11-11',
          lbp_per_usd: 89500,
          rows_total: 5739,
          rows_imported: 5628,
          imported_at: '2026-11-12T08:00:00Z',
        },
      ],
    },
    'GET /api/v1/admin/health': HEALTH,
    ...more,
  })
}

describe('Suspending a pharmacy (AS-4)', () => {
  it('suspends with a reason the pharmacy reads, then offers to reinstate', async () => {
    const api = adminApi({
      [`POST ${PHARMACY}/suspend`]: { ...APPROVED, status: 'SUSPENDED', status_reason: 'A check.' },
    })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    const confirm = await screen.findByRole('button', { name: one.confirmSuspend })
    // What is already reserved there is kept: said before the click.
    expect(screen.getByText(one.suspendHint)).toBeInTheDocument()
    expect(confirm).toBeDisabled()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.type(screen.getByLabelText(one.suspensionReason), 'A check.')
    await user.click(confirm)

    expect(await screen.findByText(one.suspended)).toBeInTheDocument()
    expect(api.sent('POST', `${PHARMACY}/suspend`)[0].body).toEqual({ reason: 'A check.' })
    expect(await screen.findByRole('button', { name: one.confirmReinstate })).toBeInTheDocument()
  })
})

describe('Clients (AS-5)', () => {
  it('lists clients as statuses and counts, with what waits marked', async () => {
    const api = adminApi()
    const { container } = renderApp(<AppRoutes />, { path: '/admin/clients' })
    const user = userEvent.setup()

    const tabs = await screen.findByRole('navigation', { name: s.nav })
    // One contested missed pickup and one flag wait: there is no tab of flags any more.
    expect(await within(tabs).findByRole('link', { name: 'Clients (2)' })).toBeInTheDocument()
    expect(within(tabs).queryByRole('link', { name: /Flags/ })).not.toBeInTheDocument()
    expect(await screen.findByText(c.contestWaiting)).toBeInTheDocument()
    expect(
      screen.getByText(/1 open reservation · 3 picked up · 1 open request · 2 missed pickups in 30 days/),
    ).toBeInTheDocument()
    // No name anywhere: the contact endpoint was not called.
    expect(screen.queryByText(CLIENT.full_name)).not.toBeInTheDocument()
    expect(api.sent('GET', `${A_CLIENT}/contact`)).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])

    await user.type(screen.getByLabelText(c.ref), 'R-7K3Q2F')
    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/admin/clients').some((call) => call.path.includes('ref=R-7K3Q2F'))).toBe(true),
    )
  })

  it('keeps who has an open request, a reservation, or needs a look', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin/clients' })
    const user = userEvent.setup()

    const everyone = await screen.findByRole('radio', { name: c.having.all })
    expect(everyone).toBeChecked()
    await user.click(screen.getByRole('radio', { name: c.having.request }))

    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/admin/clients').some((call) => call.path.includes('having=request'))).toBe(true),
    )
    expect(screen.getByRole('radio', { name: c.having.request })).toBeChecked()
  })

  it("lists on a client's page what they reserved, how each ended, and their requests", async () => {
    const api = adminApi({ [`GET ${A_CLIENT}`]: { ...CLIENT_DETAIL, contested: [] } })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })

    const reservations = await screen.findByRole('region', { name: c.reservations })
    expect(within(reservations).getByText('R-3TAKEN')).toBeInTheDocument()
    expect(within(reservations).getByText(c.orderStates.PICKED_UP)).toBeInTheDocument()
    expect(within(reservations).getByText(/PANADOL 500MG · Hamra Pharmacy/)).toBeInTheDocument()
    expect(within(reservations).getByText(c.orderStates.RESERVED)).toBeInTheDocument()
    expect(within(reservations).getByText(/pick up by Mon 16 Nov 20:00/)).toBeInTheDocument()
    expect(within(reservations).getByText(c.orderStates.EXPIRED_NO_SHOW)).toBeInTheDocument()
    // The same colours as the client's and the pharmacy's (B#21): live and picked up are
    // green, a missed pickup is red.
    expect(within(reservations).getByText(c.orderStates.RESERVED)).toHaveClass('status-pill--green')
    expect(within(reservations).getByText(c.orderStates.PICKED_UP)).toHaveClass('status-pill--green')
    expect(within(reservations).getByText(c.orderStates.EXPIRED_NO_SHOW)).toHaveClass('status-pill--red')
    const requests = screen.getByRole('region', { name: c.requestsTitle })
    expect(within(requests).getByText('Q-6BN2RA')).toBeInTheDocument()
    expect(within(requests).getByText(c.secured(1, 2), { exact: false })).toBeInTheDocument()
    // Nothing is contested and nothing is flagged: neither block is on the page.
    expect(screen.queryByRole('heading', { name: c.contests })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: c.flags })).not.toBeInTheDocument()
    // Still by an ID: the name was not asked for.
    expect(screen.queryByText(CLIENT.full_name)).not.toBeInTheDocument()
    expect(api.sent('GET', `${A_CLIENT}/contact`)).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('shows the contact details only when asked', async () => {
    const api = adminApi({
      [`GET ${A_CLIENT}/contact`]: { full_name: 'Rana Khoury', email: 'rana@example.com', phone: null },
    })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    expect(await screen.findByText(c.contactHint)).toBeInTheDocument()
    expect(screen.queryByText('Rana Khoury')).not.toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(screen.getByRole('button', { name: c.showContact }))

    expect(await screen.findByText('Rana Khoury')).toBeInTheDocument()
    expect(screen.getByText(c.noPhone)).toBeInTheDocument()
    expect(api.sent('GET', `${A_CLIENT}/contact`)).toHaveLength(1)
  })

  it('says so when the hourly limit of contact views is reached', async () => {
    adminApi({ [`GET ${A_CLIENT}/contact`]: refusal(429, 'RATE_LIMITED') })
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: c.showContact }))

    expect(await screen.findByText(c.contactLimit)).toBeInTheDocument()
  })

  it('clears a contested missed pickup, asking why where the button is', async () => {
    const api = adminApi({
      [`POST /api/v1/admin/reservations/${CONTESTED_ID}/clear-no-show`]: {
        ...CLIENT_DETAIL,
        client: { ...CLIENT_ROW, status: 'ACTIVE', paused_until: null, no_shows: 1, contested: 0 },
        contested: [],
      },
    })
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    expect(await screen.findByRole('heading', { name: c.contests })).toBeInTheDocument()
    // No reason box waits somewhere else on the page: the button asks for it itself.
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: c.clear }))
    const confirm = screen.getByRole('button', { name: c.clear })
    expect(confirm).toBeDisabled()
    await user.type(screen.getByLabelText(new RegExp(`^${s.why(c.clear)}`)), 'The pharmacy confirmed.')
    await user.click(confirm)

    expect(await screen.findByText(c.cleared)).toBeInTheDocument()
    expect(api.sent('POST', `/api/v1/admin/reservations/${CONTESTED_ID}/clear-no-show`)[0].body).toEqual({
      reason: 'The pharmacy confirmed.',
    })
    expect(screen.queryByRole('heading', { name: c.contests })).not.toBeInTheDocument()
    expect(screen.getByText(c.statuses.ACTIVE)).toBeInTheDocument()
  })

  it('lets a question be closed again without doing anything', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: c.suspend }))
    expect(screen.getByLabelText(new RegExp(`^${s.why(c.suspend)}`))).toHaveFocus()
    await user.type(screen.getByLabelText(new RegExp(`^${s.why(c.suspend)}`)), 'Not sure')
    await user.click(screen.getByRole('button', { name: s.cancel }))

    // The focus goes back to the button that opened the question, not to the page's top.
    expect(screen.getByRole('button', { name: c.suspend })).toBeEnabled()
    expect(screen.getByRole('button', { name: c.suspend })).toHaveFocus()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    // Asked again, the question starts empty.
    await user.click(screen.getByRole('button', { name: c.suspend }))
    expect(screen.getByLabelText(new RegExp(`^${s.why(c.suspend)}`))).toHaveValue('')
    expect(api.calls.every((call) => call.method === 'GET')).toBe(true)
  })

  it('says a refused action in the panel of its button, not at the top of the page', async () => {
    adminApi({ [`POST ${A_CLIENT}/suspend`]: refusal(403, 'FORBIDDEN') })
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: c.suspend }))
    await user.type(screen.getByLabelText(new RegExp(`^${s.why(c.suspend)}`)), 'Abuse.')
    await user.click(screen.getByRole('button', { name: c.suspend }))

    const actions = screen.getByRole('region', { name: c.actions })
    expect(await within(actions).findByText(strings.errors.FORBIDDEN)).toBeInTheDocument()
    expect(screen.getAllByText(strings.errors.FORBIDDEN)).toHaveLength(1)
  })

  it('names the two rows of choices, and a row by all it shows', async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: '/admin/clients' })

    expect(await screen.findByRole('tablist', { name: c.account })).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: c.show })).toBeInTheDocument()
    expect(screen.getByText(c.account)).toBeVisible()
    // "Says they picked it up" is the reason to open the row: it is in its spoken name.
    expect(
      await screen.findByRole('link', { name: new RegExp(`^${c.one} ${CLIENT.id.slice(0, 8)} ${c.contestWaiting}`) }),
    ).toBeInTheDocument()
  })

  it("keeps the typed number in the address when the bar's Clients tab is pressed", async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: '/admin/clients' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(c.ref), 'R-7K3Q2F')
    const tabs = screen.getByRole('navigation', { name: s.nav })
    await user.click(within(tabs).getByRole('link', { name: /^Clients/ }))
    await user.click(await screen.findByRole('link', { name: new RegExp(`^${c.one} ${CLIENT.id.slice(0, 8)}`) }))
    await user.click(await screen.findByRole('link', { name: s.back }))

    // What the box showed is what the list was: Back finds both again.
    expect(await screen.findByLabelText(c.ref)).toHaveValue('R-7K3Q2F')
  })

  it("has the client's ID in its page title", async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })

    const title = await screen.findByRole('heading', { level: 1, name: `${c.one} ${CLIENT.id.slice(0, 8)}` })
    expect(title).toHaveClass('page-title')
    expect(title).not.toHaveClass('audit-change')
  })

  it('goes back to the list as it was left: the filter and the typed number', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin/clients' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('radio', { name: c.having.look }))
    await user.type(screen.getByLabelText(c.ref), 'r-7vb8ub')
    await user.click(await screen.findByRole('link', { name: new RegExp(`^${c.one} ${CLIENT.id.slice(0, 8)}`) }))
    await user.click(await screen.findByRole('link', { name: s.back }))

    expect(await screen.findByRole('radio', { name: c.having.look })).toBeChecked()
    expect(screen.getByLabelText(c.ref)).toHaveValue('r-7vb8ub')
    const asked = api.sent('GET', '/api/v1/admin/clients?')
    expect(asked[asked.length - 1].path).toContain('having=look')
    expect(asked[asked.length - 1].path).toContain('ref=r-7vb8ub')
  })

  it('suspends a client, saying first what that cancels', async () => {
    const api = adminApi({
      [`POST ${A_CLIENT}/suspend`]: {
        ...CLIENT_DETAIL,
        client: { ...CLIENT_ROW, status: 'SUSPENDED', paused_until: null },
        contested: [],
      },
    })
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    expect(await screen.findByText(c.suspendHint)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: c.suspend }))
    await user.type(screen.getByLabelText(new RegExp(`^${s.why(c.suspend)}`)), 'Abuse of the assistant.')
    await user.click(screen.getByRole('button', { name: c.suspend }))

    expect(await screen.findByText(c.suspended)).toBeInTheDocument()
    expect(api.sent('POST', `${A_CLIENT}/suspend`)[0].body).toEqual({ reason: 'Abuse of the assistant.' })
    expect(screen.getByRole('button', { name: c.reinstate })).toBeInTheDocument()
  })

  it("is reached from an escalation by the client's ID, never a name", async () => {
    adminApi({ [`GET /api/v1/admin/escalations/${ESCALATION_ID}`]: ESCALATION_DETAIL })
    renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })

    const link = await screen.findByRole('link', { name: s.escalations.openClient })
    expect(link).toHaveAttribute('href', `/admin/clients/${CLIENT.id}`)
  })
})

describe('Flags, the catalog and health (AS-7, AS-9, AS-10)', () => {
  // A flag is on the page of the client it is about: the owner pressed "Open the
  // client's page" on a flag and found nothing about it there (2026-11-19).
  const FLAGGED = { ...CLIENT_DETAIL, client: { ...CLIENT_ROW, flags_open: 1 }, contested: [], flags: [FLAG] }

  it("handles a flag on the client's own page, with a reason", async () => {
    const api = adminApi({
      [`GET ${A_CLIENT}`]: FLAGGED,
      [`POST /api/v1/admin/abuse-flags/${FLAG.id}/dismiss`]: { ...FLAG, state: 'DISMISSED' },
    })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    expect(await screen.findByRole('heading', { name: c.flags })).toBeInTheDocument()
    expect(screen.getByText(f.rules.guardrail_repeat)).toBeInTheDocument()
    expect(screen.getByText(/attempts in 24 hours: 3/)).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(screen.getByRole('button', { name: f.dismiss }))
    await user.type(screen.getByLabelText(new RegExp(`^${s.why(f.dismiss)}`)), 'A test by our team.')
    await user.click(screen.getByRole('button', { name: f.dismiss }))

    expect(await screen.findByText(f.done)).toBeInTheDocument()
    expect(api.sent('POST', `/api/v1/admin/abuse-flags/${FLAG.id}/dismiss`)[0].body).toEqual({
      reason: 'A test by our team.',
    })
  })

  it('has one Suspend button on a flagged client\'s page, under Actions (B#58)', async () => {
    adminApi({ [`GET ${A_CLIENT}`]: FLAGGED })
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })

    const flags = await screen.findByRole('region', { name: c.flags })
    // A flag keeps its own two notes; suspending is one button, and it closes the flag.
    expect(within(flags).getByRole('button', { name: f.dismiss })).toBeInTheDocument()
    expect(within(flags).getByRole('button', { name: f.warn })).toBeInTheDocument()
    expect(within(flags).queryByRole('button', { name: /suspend/i })).not.toBeInTheDocument()
    expect(within(flags).getByText(f.warnHint)).toBeInTheDocument()
    const actions = screen.getByRole('region', { name: c.actions })
    expect(within(actions).getByRole('button', { name: c.suspend })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /suspend/i })).toHaveLength(1)
  })

  it('notes a warning on a flag, and says that nothing is sent (Q52)', async () => {
    const api = adminApi({
      [`GET ${A_CLIENT}`]: FLAGGED,
      [`POST /api/v1/admin/abuse-flags/${FLAG.id}/act`]: { ...FLAG, state: 'ACTIONED', action: 'warn' },
    })
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    expect(await screen.findByText(f.warnHint)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Warned' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Note a warning' }))
    await user.type(screen.getByLabelText(new RegExp(`^${s.why(f.warn)}`)), 'Told by phone.')
    await user.click(screen.getByRole('button', { name: 'Note a warning' }))

    expect(await screen.findByText(f.done)).toBeInTheDocument()
    expect(api.sent('POST', `/api/v1/admin/abuse-flags/${FLAG.id}/act`)[0].body).toEqual({
      action: 'warn',
      reason: 'Told by phone.',
    })
  })

  it('reads the catalog, the controlled products marked, with no way to change it', async () => {
    const api = adminApi()
    const { container } = renderApp(<AppRoutes />, { path: '/admin/catalog' })

    expect(await screen.findByRole('rowheader', { name: /LOCKEDOL 10MG/ })).toBeInTheDocument()
    expect(screen.getByText(s.catalog.controlled)).toBeInTheDocument()
    expect(screen.getByText(s.catalog.same(2))).toBeInTheDocument()
    expect(screen.getByText(/5,628 of 5,739 products/)).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    expect(api.calls.every((call) => call.method === 'GET')).toBe(true)
  })

  it('has words for every alert the server can raise', async () => {
    // The codes of `services/health.py`. One without words would be shown as its code.
    const codes = [
      'agent_error_rate',
      'llm_spend',
      'llm_daily_cap',
      'dead_emails',
      'clock_check_late',
      'agent_turn_stuck',
      'books_do_not_add_up',
      'retention_failing',
      'contact_views_limit',
      'admin_login_locked',
    ] as const
    adminApi({ 'GET /api/v1/admin/health': { ...HEALTH, alerts: [...codes] } })
    renderApp(<AppRoutes />, { path: '/admin/health' })

    expect(await screen.findByText(h.alerts.agent_turn_stuck)).toBeInTheDocument()
    for (const code of codes) {
      expect(screen.getByText(h.alerts[code])).toBeInTheDocument()
      expect(screen.queryByText(code)).not.toBeInTheDocument()
    }
    expect(Object.keys(h.alerts).sort()).toEqual([...codes].sort())
  })

  it("shows the assistant's numbers, and an alert when one fires", async () => {
    adminApi({ 'GET /api/v1/admin/health': { ...HEALTH, alerts: ['agent_turn_stuck'] } })
    const { container } = renderApp(<AppRoutes />, { path: '/admin/health' })

    expect(await screen.findByText(h.alerts.agent_turn_stuck)).toBeInTheDocument()
    expect(screen.getByText('2,310')).toBeInTheDocument()
    expect(screen.getByText('2.1 s · 4.2 s')).toBeInTheDocument()
    expect(screen.getByText('71%')).toBeInTheDocument()
    expect(screen.getByText('$12.40 / $20.00')).toBeInTheDocument()
    expect(screen.getByText('v1.13')).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('says so when no alert fires', async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: '/admin/health' })

    expect(await screen.findByText(h.noAlerts)).toBeInTheDocument()
  })

  it('calls its shortest period what it counts: the last 24 hours', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin/health' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('tab', { name: 'Last 24 hours' }))
    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/admin/health').some((call) => call.path.includes('days=1'))).toBe(true),
    )
    expect(screen.queryByRole('tab', { name: 'Today' })).not.toBeInTheDocument()
  })
})

describe('A no-show the client contests (R-N3)', () => {
  it('offers [I picked it up] once on an expired reservation', async () => {
    loggedIn()
    const expired = {
      ...RESERVATION,
      state: 'EXPIRED_NO_SHOW',
      status_text: "Missed pickup: it wasn't picked up in time",
      contestable: true,
    }
    const api = pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      'GET /api/v1/config/public': CONFIG,
      [`GET /api/v1/reservations/${RESERVATION.id}`]: expired,
      [`POST /api/v1/reservations/${RESERVATION.id}/contest`]: { ...expired, contestable: false },
    })
    renderApp(<AppRoutes />, { path: `/reservations/${RESERVATION.id}` })
    const user = userEvent.setup()
    const t = strings.ticket

    await user.click(await screen.findByRole('button', { name: t.contest }))

    expect(await screen.findByText(t.contested)).toBeInTheDocument()
    expect(api.sent('POST', `/api/v1/reservations/${RESERVATION.id}/contest`)).toHaveLength(1)
    expect(screen.queryByRole('button', { name: t.contest })).not.toBeInTheDocument()
  })
})
