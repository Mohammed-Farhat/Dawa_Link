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
    'GET /api/v1/admin/abuse-flags': { items: [FLAG], next_cursor: null },
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
    expect(await within(tabs).findByRole('link', { name: 'Clients (1)' })).toBeInTheDocument()
    expect(await screen.findByText(c.contestWaiting)).toBeInTheDocument()
    expect(screen.getByText(/1 open reservation · 0 open requests · 2 no-shows in 30 days/)).toBeInTheDocument()
    // No name anywhere: the contact endpoint was not called.
    expect(screen.queryByText(CLIENT.full_name)).not.toBeInTheDocument()
    expect(api.sent('GET', `${A_CLIENT}/contact`)).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])

    await user.type(screen.getByLabelText(c.ref), 'R-7K3Q2F')
    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/admin/clients').some((call) => call.path.includes('ref=R-7K3Q2F'))).toBe(true),
    )
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

  it('clears a contested no-show with a reason', async () => {
    const api = adminApi({
      [`POST /api/v1/admin/reservations/${CONTESTED_ID}/clear-no-show`]: {
        client: { ...CLIENT_ROW, status: 'ACTIVE', paused_until: null, no_shows: 1, contested: 0 },
        contested: [],
      },
    })
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    expect(await screen.findByText('R-7K3Q2F')).toBeInTheDocument()
    const clear = screen.getByRole('button', { name: c.clear })
    expect(clear).toBeDisabled()
    await user.type(screen.getByLabelText(new RegExp(`^${s.reason}`)), 'The pharmacy confirmed.')
    await user.click(clear)

    expect(await screen.findByText(c.cleared)).toBeInTheDocument()
    expect(api.sent('POST', `/api/v1/admin/reservations/${CONTESTED_ID}/clear-no-show`)[0].body).toEqual({
      reason: 'The pharmacy confirmed.',
    })
    expect(screen.getByText(c.noContests)).toBeInTheDocument()
    expect(screen.getByText(c.statuses.ACTIVE)).toBeInTheDocument()
  })

  it('suspends a client, saying first what that cancels', async () => {
    const api = adminApi({
      [`POST ${A_CLIENT}/suspend`]: { client: { ...CLIENT_ROW, status: 'SUSPENDED', paused_until: null }, contested: [] },
    })
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    expect(await screen.findByText(c.suspendHint)).toBeInTheDocument()
    await user.type(screen.getByLabelText(new RegExp(`^${s.reason}`)), 'Abuse of the assistant.')
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
  it('handles a flag with a reason', async () => {
    const api = adminApi({
      [`POST /api/v1/admin/abuse-flags/${FLAG.id}/act`]: { ...FLAG, state: 'ACTIONED', action: 'suspend' },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/admin/flags' })
    const user = userEvent.setup()

    expect(await screen.findByRole('heading', { name: f.rules.guardrail_repeat })).toBeInTheDocument()
    expect(screen.getByText(/attempts in 24 hours: 3/)).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    const suspend = screen.getByRole('button', { name: f.suspend })
    expect(suspend).toBeDisabled()
    await user.type(screen.getByLabelText(new RegExp(`^${s.reason}`)), 'Three attempts.')
    await user.click(suspend)

    expect(await screen.findByText(f.done)).toBeInTheDocument()
    expect(api.sent('POST', `/api/v1/admin/abuse-flags/${FLAG.id}/act`)[0].body).toEqual({
      action: 'suspend',
      reason: 'Three attempts.',
    })
  })

  it('notes a warning on a flag, and says that nothing is sent (Q52)', async () => {
    const api = adminApi({
      [`POST /api/v1/admin/abuse-flags/${FLAG.id}/act`]: { ...FLAG, state: 'ACTIONED', action: 'warn' },
    })
    renderApp(<AppRoutes />, { path: '/admin/flags' })
    const user = userEvent.setup()

    expect(await screen.findByText(f.warnHint)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Warned' })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText(new RegExp(`^${s.reason}`)), 'Told by phone.')
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
})

describe('A no-show the client contests (R-N3)', () => {
  it('offers [I picked it up] once on an expired reservation', async () => {
    loggedIn()
    const expired = { ...RESERVATION, state: 'EXPIRED_NO_SHOW', status_text: 'Expired', contestable: true }
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
