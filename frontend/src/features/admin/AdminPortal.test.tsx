import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../../app/App'
import { errorMessage, strings } from '../../strings/en'
import {
  ADMIN,
  AUDIT_EVENT,
  ESCALATION,
  ESCALATION_DETAIL,
  ESCALATION_ID,
  OVERVIEW,
  PHARMACY_ID,
  REPORT,
  REPORT_DETAIL,
  REPORT_ID,
  WAITING,
  WAITING_ROW,
} from '../../test/admin'
import { PHARMACIST } from '../../test/pharmacy'
import {
  accessibilityProblems,
  CLIENT,
  CONFIG,
  DISTRICTS,
  loggedIn,
  pretendApi,
  refusal,
  renderApp,
} from '../../test/render'

// The real map needs a browser that draws. Here it is a button that moves the pin.
vi.mock('../pharmacy/PinMap', () => ({
  default: ({ onChange }: { onChange: (pin: { lat: number; lon: number }) => void }) => (
    <button type="button" onClick={() => onChange({ lat: 33.9, lon: 35.5 })}>
      move the pin
    </button>
  ),
}))

const s = strings.admin
const one = s.pharmacy
const e = s.escalations
const r = s.reports
const d = strings.pharmacy.details

const PHARMACY = `/api/v1/admin/pharmacies/${PHARMACY_ID}`
const ESCALATED = `/api/v1/admin/escalations/${ESCALATION_ID}`
const REPORTED = `/api/v1/admin/answer-reports/${REPORT_ID}`

function adminApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': ADMIN,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/admin/overview': OVERVIEW,
    'GET /api/v1/admin/pharmacies': { items: [WAITING_ROW], next_cursor: null },
    [`GET ${PHARMACY}`]: WAITING,
    'GET /api/v1/admin/escalations': { items: [ESCALATION], next_cursor: null },
    [`GET ${ESCALATED}`]: ESCALATION_DETAIL,
    'GET /api/v1/admin/answer-reports': { items: [REPORT], next_cursor: null },
    [`GET ${REPORTED}`]: REPORT_DETAIL,
    'GET /api/v1/admin/audit': { items: [AUDIT_EVENT], next_cursor: null },
    ...more,
  })
}

describe("The admin's login and console", () => {
  it('logs in with the code of the authenticator app, and lands on the console', async () => {
    const api = pretendApi({
      'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED'),
      'POST /api/v1/auth/login': { me: ADMIN, token: 'admin-token', expires_at: '2026-11-16T20:00:00Z' },
      'GET /api/v1/admin/overview': OVERVIEW,
      'GET /api/v1/admin/pharmacies': { items: [WAITING_ROW], next_cursor: null },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/admin' })
    const user = userEvent.setup()

    // Not logged in: the admins' own login page, with no way to sign up from it.
    expect(await screen.findByRole('heading', { name: s.loginTitle })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: strings.login.noAccount })).not.toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.type(screen.getByLabelText(strings.login.email), 'admin@example.com')
    await user.type(screen.getByLabelText(strings.login.password), 'a long enough passphrase')
    // Without the code the button stays off.
    expect(screen.getByRole('button', { name: strings.login.submit })).toBeDisabled()
    await user.type(screen.getByLabelText(strings.login.code), '123456')
    await user.click(screen.getByRole('button', { name: strings.login.submit }))

    expect(await screen.findByRole('heading', { name: s.pharmacies.title })).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/auth/login')[0].body).toMatchObject({ totp_code: '123456' })
  })

  it('says so when the network has made too many failed logins (N-52)', async () => {
    pretendApi({
      'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED'),
      'POST /api/v1/auth/login': refusal(429, 'RATE_LIMITED'),
    })
    renderApp(<AppRoutes />, { path: '/admin/login' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(strings.login.email), 'admin@example.com')
    await user.type(screen.getByLabelText(strings.login.password), 'a long enough passphrase')
    await user.type(screen.getByLabelText(strings.login.code), '123456')
    await user.click(screen.getByRole('button', { name: strings.login.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(strings.login.networkBlocked)
  })

  it('comes back, after the login, to the page that asked for it', async () => {
    // A session that ran out while the admin was reading the audit log.
    pretendApi({
      'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED'),
      'POST /api/v1/auth/login': { me: ADMIN, token: 'admin-token', expires_at: '2026-11-16T20:00:00Z' },
      'GET /api/v1/admin/overview': OVERVIEW,
      'GET /api/v1/admin/pharmacies': { items: [WAITING_ROW], next_cursor: null },
      'GET /api/v1/admin/audit': { items: [AUDIT_EVENT], next_cursor: null },
    })
    renderApp(<AppRoutes />, { path: '/admin/audit' })
    const user = userEvent.setup()

    expect(await screen.findByRole('heading', { name: s.loginTitle })).toBeInTheDocument()
    await user.type(screen.getByLabelText(strings.login.email), 'admin@example.com')
    await user.type(screen.getByLabelText(strings.login.password), 'a long enough passphrase')
    await user.type(screen.getByLabelText(strings.login.code), '123456')
    await user.click(screen.getByRole('button', { name: strings.login.submit }))

    expect(await screen.findByRole('heading', { name: s.audit.title })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: s.pharmacies.title })).not.toBeInTheDocument()
  })

  it('shows what waits on its tabs, and the demo clock only in demo mode', async () => {
    adminApi({ 'GET /api/v1/admin/overview': { ...OVERVIEW, demo_mode: false } })
    const { container } = renderApp(<AppRoutes />, { path: '/admin' })

    const tabs = await screen.findByRole('navigation', { name: s.nav })
    expect(await within(tabs).findByRole('link', { name: 'Pharmacies (1)' })).toBeInTheDocument()
    expect(within(tabs).getByRole('link', { name: 'Escalations (2)' })).toBeInTheDocument()
    expect(within(tabs).getByRole('link', { name: s.tabs.reports })).toBeInTheDocument()
    expect(within(tabs).queryByRole('link', { name: s.tabs.clock })).not.toBeInTheDocument()
    expect(await screen.findByRole('link', { name: s.pharmacies.open('Hamra Pharmacy') })).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it.each([
    ['a client', CLIENT],
    ['a pharmacist', PHARMACIST],
  ])('is not for %s', async (_who, me) => {
    loggedIn()
    const api = pretendApi({ 'GET /api/v1/auth/me': me, 'GET /api/v1/config/public': CONFIG })
    renderApp(<AppRoutes />, { path: '/admin' })

    await waitFor(() => expect(api.sent('GET', '/api/v1/auth/me').length).toBeGreaterThan(0))
    await waitFor(() => expect(screen.queryByRole('navigation', { name: s.nav })).not.toBeInTheDocument())
    expect(api.sent('GET', '/api/v1/admin')).toEqual([])
  })
})

describe('A registration that waits (AS-3)', () => {
  it('is approved as it was seen', async () => {
    const api = adminApi({
      [`POST ${PHARMACY}/approve`]: { ...WAITING, status: 'APPROVED', pin_checked: true },
    })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    expect(await screen.findByRole('heading', { name: 'Hamra Pharmacy' })).toBeInTheDocument()
    expect(screen.getByText('owner@hamra.example.com')).toBeInTheDocument()
    expect(screen.getByText('Monday: 08:00 to 13:00, 16:00 to 21:00')).toBeInTheDocument()
    expect(screen.getByText(one.pinNotChecked)).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(screen.getByRole('button', { name: one.approve }))

    expect(await screen.findByText(one.approved)).toBeInTheDocument()
    // The version that was on the screen goes with the click.
    expect(api.sent('POST', `${PHARMACY}/approve`)[0].body).toEqual({ version: 'version-1' })
    // Approved: there is nothing left to decide.
    expect(screen.queryByRole('button', { name: one.approve })).not.toBeInTheDocument()
  })

  it('says so when the pharmacy changed its details in the meantime', async () => {
    const api = adminApi({ [`POST ${PHARMACY}/approve`]: refusal(409, 'CHANGED_SINCE') })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: one.approve }))

    expect(await screen.findByText(s.changed)).toBeInTheDocument()
    // And it reads the pharmacy again.
    await waitFor(() => expect(api.sent('GET', PHARMACY).length).toBeGreaterThan(1))
  })

  it('is rejected with a reason the pharmacy reads', async () => {
    const api = adminApi({
      [`POST ${PHARMACY}/reject`]: { ...WAITING, status: 'REJECTED', status_reason: 'Not in the list.' },
    })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: one.reject }))
    const confirm = screen.getByRole('button', { name: one.confirmReject })
    expect(confirm).toBeDisabled()
    await user.type(screen.getByLabelText(one.rejectReason), 'Not in the list.')
    await user.click(confirm)

    expect(await screen.findByText(one.rejected)).toBeInTheDocument()
    expect(api.sent('POST', `${PHARMACY}/reject`)[0].body).toEqual({ reason: 'Not in the list.' })
    expect(screen.getByText(one.reasonGiven('Not in the list.'))).toBeInTheDocument()
  })

  it('is asked for more information and stays in the queue', async () => {
    const api = adminApi({
      [`POST ${PHARMACY}/request-info`]: { ...WAITING, info_requested: true, status_reason: 'Which street?' },
    })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: one.askMore }))
    await user.type(screen.getByLabelText(one.askReason), 'Which street?')
    await user.click(screen.getByRole('button', { name: one.confirmAsk }))

    expect(await screen.findByText(one.asked)).toBeInTheDocument()
    expect(api.sent('POST', `${PHARMACY}/request-info`)[0].body).toEqual({ reason: 'Which street?' })
    expect(screen.getByRole('button', { name: one.approve })).toBeInTheDocument()
  })
})

describe('An admin corrects a pharmacy (AS-4)', () => {
  it('sends only what changed, with the reason, and a moved pin', async () => {
    const api = adminApi({ [`PATCH ${PHARMACY}`]: { ...WAITING, name: 'Hamra Pharmacy 2' } })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    const save = await screen.findByRole('button', { name: one.save })
    expect(save).toBeDisabled()
    const name = screen.getByLabelText(d.name)
    await user.clear(name)
    await user.type(name, 'Hamra Pharmacy 2')
    await user.click(await screen.findByRole('button', { name: 'move the pin' }))
    expect(screen.getByText(one.pinMoved)).toBeInTheDocument()
    // A change with no reason can't be saved.
    expect(save).toBeDisabled()
    await user.type(screen.getByLabelText(new RegExp(`^${s.reason}`)), 'As on its sign.')
    await user.click(save)

    expect(await screen.findByText(one.saved)).toBeInTheDocument()
    expect(api.sent('PATCH', PHARMACY)[0].body).toEqual({
      reason: 'As on its sign.',
      name: 'Hamra Pharmacy 2',
      location: { lat: 33.9, lon: 35.5 },
    })
  })

  it('shows a refusal on the field it names', async () => {
    adminApi({ [`PATCH ${PHARMACY}`]: refusal(422, 'VALIDATION_ERROR', { field: 'phone' }) })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    const phone = await screen.findByLabelText(d.phone)
    await user.clear(phone)
    await user.type(phone, '12')
    await user.type(screen.getByLabelText(new RegExp(`^${s.reason}`)), 'New number.')
    await user.click(screen.getByRole('button', { name: one.save }))

    expect(await screen.findByText(d.problems.phone)).toBeInTheDocument()
  })

  it('asks for a look at the pin of a pharmacy that moved, and notes it (Q45)', async () => {
    const moved = {
      ...WAITING,
      status: 'APPROVED',
      pin_to_check: true,
      moved_at: '2026-11-15T09:30:00Z',
    }
    const api = adminApi({
      'GET /api/v1/admin/overview': { ...OVERVIEW, pharmacies_waiting: 0, pins_to_check: 1 },
      'GET /api/v1/admin/pharmacies': {
        items: [{ ...WAITING_ROW, status: 'APPROVED', pin_to_check: true }],
        next_cursor: null,
      },
      [`GET ${PHARMACY}`]: moved,
      [`POST ${PHARMACY}/check-pin`]: { ...moved, pin_to_check: false, pin_checked: true },
    })
    renderApp(<AppRoutes />, { path: '/admin' })
    const user = userEvent.setup()

    // It is counted on the tab and marked in the list.
    expect(await screen.findByRole('link', { name: 'Pharmacies (1)' })).toBeInTheDocument()
    expect(await screen.findByText(s.pharmacies.movedWaiting(1))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: s.pharmacies.showMoved }))
    expect(await screen.findByText(s.pharmacies.pinToCheck)).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: s.pharmacies.open('Hamra Pharmacy') }))
    expect(await screen.findByText(/The pharmacy changed its address or its pin on Sun 15 Nov/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: one.pinIsRight }))

    expect(await screen.findByText(one.pinConfirmed)).toBeInTheDocument()
    expect(api.sent('POST', `${PHARMACY}/check-pin`)).toHaveLength(1)
    expect(screen.getByText(one.pinChecked)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: one.pinIsRight })).not.toBeInTheDocument()
  })

  it('shows how an approved pharmacy is doing, and nothing of the kind for a new one (AS-4)', async () => {
    const doing = {
      ...WAITING,
      status: 'APPROVED',
      live_listings: 12,
      last_inventory_update: '2026-11-15T09:30:00Z',
      handed_over_30d: 6,
      not_available_30d: 2,
    }
    adminApi({ [`GET ${PHARMACY}`]: doing })
    const { container, unmount } = renderApp(<AppRoutes />, {
      path: `/admin/pharmacies/${PHARMACY_ID}`,
    })

    expect(await screen.findByText(one.liveListings)).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText(/Sun 15 Nov 11:30/)).toBeInTheDocument()
    expect(screen.getByText('2 of 8 reservations in the last 30 days (25%)')).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    unmount()

    adminApi()
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    expect(await screen.findByRole('heading', { name: 'Hamra Pharmacy' })).toBeInTheDocument()
    expect(screen.queryByText(one.liveListings)).not.toBeInTheDocument()
  })

  it('says so when no reservation ended at the counter', async () => {
    adminApi({ [`GET ${PHARMACY}`]: { ...WAITING, status: 'APPROVED' } })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })

    expect(await screen.findByText(one.notAvailableOf(0, 0))).toBeInTheDocument()
    expect(screen.getByText(one.never)).toBeInTheDocument()
  })

  it('shows that the pharmacy changed its own phone', async () => {
    adminApi({ [`GET ${PHARMACY}`]: { ...WAITING, status: 'APPROVED', phone_changed_at: '2026-11-15T09:30:00Z' } })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })

    expect(await screen.findByText(/changed by the pharmacy on Sun 15 Nov/)).toBeInTheDocument()
    // Approved already: nothing to decide.
    expect(screen.queryByRole('button', { name: one.approve })).not.toBeInTheDocument()
  })
})

describe('Escalations (AS-6)', () => {
  it('lists who waits, the emergency claim marked', async () => {
    adminApi()
    const { container } = renderApp(<AppRoutes />, { path: '/admin/escalations' })

    expect(await screen.findByText(e.reasons.emergency_claim)).toBeInTheDocument()
    expect(screen.getByText(ESCALATION.summary)).toBeInTheDocument()
    expect(screen.getByText(/Request Q-6BN2RA/)).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('shows the conversation as stored and sends a reply', async () => {
    const replied = {
      ...ESCALATION_DETAIL,
      escalation: { ...ESCALATION, state: 'IN_PROGRESS' },
      thread: [
        ...ESCALATION_DETAIL.thread,
        { seq: 3, author: 'admin', text: 'Please call 140.', cards: [], created_at: '2026-11-16T08:00:00Z' },
      ],
    }
    const api = adminApi({ [`POST ${ESCALATED}/reply`]: replied })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })
    const user = userEvent.setup()

    expect(await screen.findByText('I need it today, call me on [phone].')).toBeInTheDocument()
    // The rule is said where the temptation is.
    expect(screen.getByText(e.noPriority)).toBeInTheDocument()
    expect(screen.getByText(e.card('reserve'))).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    const send = screen.getByRole('button', { name: e.send })
    expect(send).toBeDisabled()
    await user.type(screen.getByRole('textbox', { name: e.reply }), 'Please call 140.')
    await user.click(send)

    expect(await screen.findByText(e.sent)).toBeInTheDocument()
    expect(api.sent('POST', `${ESCALATED}/reply`)[0].body).toEqual({ text: 'Please call 140.' })
    expect(screen.getByText('Please call 140.')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: e.reply })).toHaveValue('')
  })

  it('shows a thread as plain text, whatever was typed into it (FS-8)', async () => {
    // An admin's session can suspend accounts and read contacts: a client must not be
    // able to run anything in it by writing a message.
    const evil = '<img src=x onerror="alert(1)"><script>alert(2)</script><a href="javascript:alert(3)">x</a>'
    adminApi({
      [`GET ${ESCALATED}`]: {
        ...ESCALATION_DETAIL,
        escalation: { ...ESCALATION, summary: `Summary ${evil}` },
        thread: [
          { seq: 1, author: 'client', text: `Client ${evil}`, cards: [`Card ${evil}`], created_at: '2026-11-16T07:38:00Z' },
          { seq: 2, author: 'admin', text: `Team ${evil}`, cards: [], created_at: '2026-11-16T07:39:00Z' },
        ],
      },
    })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })

    expect(await screen.findByText(`Client ${evil}`)).toBeInTheDocument()
    expect(screen.getByText(`Team ${evil}`)).toBeInTheDocument()
    expect(screen.getByText(new RegExp('Summary <img'))).toBeInTheDocument()
    expect(container.querySelector('script, img, iframe')).toBeNull()
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
    expect(container.querySelector('[onerror]')).toBeNull()
  })

  it('is resolved with a note, and then offers nothing more to do', async () => {
    const resolved = {
      ...ESCALATION_DETAIL,
      escalation: { ...ESCALATION, state: 'RESOLVED', resolution_note: 'Pointed to 140.' },
    }
    const api = adminApi({ [`POST ${ESCALATED}/resolve`]: resolved })
    renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(e.note), 'Pointed to 140.')
    await user.click(screen.getByRole('button', { name: e.resolve }))

    expect(await screen.findByText(e.resolvedNote('Pointed to 140.'))).toBeInTheDocument()
    expect(api.sent('POST', `${ESCALATED}/resolve`)[0].body).toEqual({ note: 'Pointed to 140.' })
    expect(screen.queryByRole('button', { name: e.send })).not.toBeInTheDocument()
  })

  it('says so when another admin resolved it first', async () => {
    adminApi({ [`POST ${ESCALATED}/reply`]: refusal(409, 'CHANGED_SINCE') })
    renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })
    const user = userEvent.setup()

    await user.type(await screen.findByRole('textbox', { name: e.reply }), 'Hello')
    await user.click(screen.getByRole('button', { name: e.send }))

    expect(await screen.findByText(s.changed)).toBeInTheDocument()
  })
})

describe('Reported answers (AS-8)', () => {
  it('shows the reply with what came before, and confirms it into the regression tests', async () => {
    const api = adminApi({
      [`POST ${REPORTED}/confirm`]: {
        ...REPORT_DETAIL,
        report: { ...REPORT, state: 'CONFIRMED', category: 'safety', in_regression: true },
      },
    })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/reports/${REPORT_ID}` })
    const user = userEvent.setup()

    expect(await screen.findByText('Take two tablets a day.')).toBeInTheDocument()
    expect(screen.getByText('How much Panadol can I take?')).toBeInTheDocument()
    expect(screen.getByText(r.comment('It told me how much to take.'))).toBeInTheDocument()
    expect(screen.getByText('v1.13')).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.selectOptions(screen.getByRole('combobox', { name: r.category }), 'safety')
    await user.click(screen.getByRole('button', { name: r.confirm }))

    expect(await screen.findByText(r.reviewed)).toBeInTheDocument()
    expect(api.sent('POST', `${REPORTED}/confirm`)[0].body).toEqual({
      category: 'safety',
      add_to_regression: true,
    })
    expect(screen.getByText(r.inRegression)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: r.confirm })).not.toBeInTheDocument()
  })

  it('dismisses a report that is not a problem', async () => {
    const api = adminApi({
      [`POST ${REPORTED}/dismiss`]: { ...REPORT_DETAIL, report: { ...REPORT, state: 'DISMISSED' } },
    })
    renderApp(<AppRoutes />, { path: `/admin/reports/${REPORT_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: r.dismiss }))

    expect(await screen.findByText(r.reviewed)).toBeInTheDocument()
    expect(api.sent('POST', `${REPORTED}/dismiss`)).toHaveLength(1)
  })

  it('downloads the regression cases', async () => {
    const made = vi.fn(() => 'blob:test')
    Object.assign(URL, { createObjectURL: made, revokeObjectURL: vi.fn() })
    adminApi({ 'GET /api/v1/admin/answer-reports/export': { cases: [{ id: REPORT_ID }] } })
    renderApp(<AppRoutes />, { path: '/admin/reports' })
    const user = userEvent.setup()

    expect(await screen.findByText('Take two tablets a day.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: r.export }))

    expect(await screen.findByText(r.exported(1))).toBeInTheDocument()
    expect(made).toHaveBeenCalledTimes(1)
  })
})

describe('The audit log and the demo clock (AS-11, AS-12)', () => {
  it('shows who changed what, and filters by kind', async () => {
    const api = adminApi()
    const { container } = renderApp(<AppRoutes />, { path: '/admin/audit' })
    const user = userEvent.setup()

    expect(await screen.findByRole('rowheader', { name: 'pharmacy.approve' })).toBeInTheDocument()
    expect(screen.getByText('status: PENDING → status: APPROVED')).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.selectOptions(screen.getByRole('combobox', { name: s.audit.kind }), 'escalation.')

    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/admin/audit').some((call) => call.path.includes('action=escalation.'))).toBe(true),
    )
    // No button on this page changes anything.
    expect(api.calls.every((call) => call.method === 'GET')).toBe(true)
  })

  it('moves the demo clock forward', async () => {
    const clock = { server_now: '2026-11-16T08:00:00Z', offset_minutes: 0, demo_mode: true }
    const api = adminApi({
      'GET /api/v1/admin/demo-clock': clock,
      'POST /api/v1/admin/demo-clock/advance': { ...clock, server_now: '2026-11-16T10:00:00Z', offset_minutes: 120 },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/admin/clock' })
    const user = userEvent.setup()

    expect(await screen.findByText(s.clock.ahead(0))).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(screen.getByRole('button', { name: '+2 h' }))

    expect(await screen.findByText(s.clock.ahead(120))).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/admin/demo-clock/advance')[0].body).toMatchObject({ minutes: 120 })
  })

  it('has no clock outside demo mode', async () => {
    adminApi({ 'GET /api/v1/admin/overview': { ...OVERVIEW, demo_mode: false } })
    renderApp(<AppRoutes />, { path: '/admin/clock' })

    expect(await screen.findByText(strings.notFound.title)).toBeInTheDocument()
    expect(errorMessage('DEMO_MODE_OFF')).toBe(strings.errors.DEMO_MODE_OFF)
  })
})
