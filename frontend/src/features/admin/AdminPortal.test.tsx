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
    // Without the code a press says so on the code's box, and the focus goes there.
    await user.click(screen.getByRole('button', { name: strings.login.submit }))
    expect(screen.getByText(strings.login.codeMissing)).toBeInTheDocument()
    expect(screen.getByLabelText(strings.login.code)).toHaveFocus()
    expect(api.sent('POST', '/api/v1/auth/login')).toEqual([])
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
    // A row is named by what it shows, its status included (WCAG 2.5.3).
    expect(await screen.findByRole('link', { name: /^Hamra Pharmacy Waiting/ })).toBeInTheDocument()
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
    // The question closed: the focus is back on the button that opened it.
    expect(screen.getByRole('button', { name: one.askMore })).toHaveFocus()
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

  it('says a refusal of a field it does not mark in its own panel, never nothing (A#35)', async () => {
    adminApi({
      [`PATCH ${PHARMACY}`]: refusal(422, 'VALIDATION_ERROR', { fields: [{ field: 'reason', problem: 'too long' }] }),
    })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    const edit = await screen.findByRole('region', { name: one.edit })
    await user.type(within(edit).getByLabelText(d.address), ' 2')
    await user.type(within(edit).getByLabelText(new RegExp(`^${s.reason}`)), 'As on its sign.')
    await user.click(within(edit).getByRole('button', { name: one.save }))

    expect(await within(edit).findByText(strings.errors.VALIDATION_ERROR)).toBeInTheDocument()
  })

  it("never lets a text grow past the API's bound (A#35)", async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })

    const edit = await screen.findByRole('region', { name: one.edit })
    expect(within(edit).getByLabelText(d.name)).toHaveAttribute('maxlength', '120')
    expect(within(edit).getByLabelText(d.license)).toHaveAttribute('maxlength', '40')
    expect(within(edit).getByLabelText(d.phone)).toHaveAttribute('maxlength', '30')
    expect(within(edit).getByLabelText(d.address)).toHaveAttribute('maxlength', '300')
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
    // Its status is in the row's spoken name, not hidden behind a label.
    await user.click(screen.getByRole('link', { name: /^Hamra Pharmacy Pin to check/ }))
    expect(await screen.findByText(/The pharmacy changed its address or its pin on Sun 15 Nov/)).toBeInTheDocument()
    // Its own page says why the admin is here, as the row did.
    expect(screen.getByText(s.pharmacies.pinToCheck)).toBeInTheDocument()
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

  it("reads a client's words in Arabic letters with an Arabic voice, and the labels as English (B#10)", async () => {
    adminApi({
      [`GET ${ESCALATED}`]: {
        ...ESCALATION_DETAIL,
        thread: [
          { seq: 1, author: 'client', text: 'بدي بنادول', cards: [], created_at: '2026-11-16T07:38:00Z' },
          { seq: 2, author: 'agent', text: 'Which strength?', cards: [], created_at: '2026-11-16T07:39:00Z' },
        ],
      },
    })
    renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })

    expect(await screen.findByText('بدي بنادول')).toHaveAttribute('lang', 'ar')
    expect(screen.getByText('Which strength?')).not.toHaveAttribute('lang')
    for (const label of screen.getAllByText(e.authors.client)) expect(label).not.toHaveAttribute('lang')
  })

  it('is closed with a note, and then offers nothing more to do', async () => {
    const resolved = {
      ...ESCALATION_DETAIL,
      escalation: { ...ESCALATION, state: 'RESOLVED', resolution_note: 'Pointed to 140.' },
    }
    const api = adminApi({ [`POST ${ESCALATED}/resolve`]: resolved })
    renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(new RegExp(`^${e.note.replace(/[()]/g, '\\$&')}`)), 'Pointed to 140.')
    await user.click(screen.getByRole('button', { name: e.close }))

    expect(await screen.findByText(e.resolvedNote('Pointed to 140.'))).toBeInTheDocument()
    expect(api.sent('POST', `${ESCALATED}/resolve`)[0].body).toEqual({ note: 'Pointed to 140.' })
    expect(screen.queryByRole('button', { name: e.send })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: e.close })).not.toBeInTheDocument()
  })

  it('is closed in one press: no note is asked for, and nobody "takes" it first', async () => {
    const resolved = { ...ESCALATION_DETAIL, escalation: { ...ESCALATION, state: 'RESOLVED' } }
    const api = adminApi({ [`POST ${ESCALATED}/resolve`]: resolved })
    renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })
    const user = userEvent.setup()

    const close = await screen.findByRole('button', { name: e.close })
    expect(close).toBeEnabled()
    expect(screen.queryByRole('button', { name: /take/i })).not.toBeInTheDocument()
    // The tracing tool's IDs are for developers: not on an admin's page.
    expect(screen.queryByText(/trace/i)).not.toBeInTheDocument()
    await user.click(close)

    expect(await screen.findByText(e.closed)).toBeInTheDocument()
    expect(api.sent('POST', `${ESCALATED}/resolve`)[0].body).toEqual({ note: '' })
  })

  it('says the rule about priority on an emergency claim only', async () => {
    adminApi({
      [`GET ${ESCALATED}`]: {
        ...ESCALATION_DETAIL,
        escalation: { ...ESCALATION, reason: 'client_asked_human', request_ref: null },
      },
    })
    renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })

    expect(await screen.findByRole('heading', { name: e.summary })).toBeInTheDocument()
    expect(screen.getByText(e.reasons.client_asked_human)).toBeInTheDocument()
    expect(screen.queryByText(e.noPriority)).not.toBeInTheDocument()
  })

  it('shows a contested missed pickup with its own button, and no chat that never was', async () => {
    const contested = {
      id: 'dddddddd-4444-4444-8444-dddddddddddd',
      ref: 'R-7K3Q2F',
      product: 'AUGMENTIN 1G',
      pharmacy: 'Hamra Pharmacy',
      expired_at: '2026-11-15T19:00:00Z',
      contested_at: '2026-11-16T07:00:00Z',
      counts_as_no_show: true,
    }
    const complaint = {
      escalation: {
        ...ESCALATION,
        reason: 'complaint',
        request_ref: null,
        summary:
          'The client says they collected order R-7K3Q2F, but the pharmacy never pressed [Picked up]: it was counted as a missed pickup.',
      },
      thread: [],
      contested: [contested],
    }
    const clearing = `/api/v1/admin/reservations/${contested.id}/clear-no-show`
    const api = adminApi({ [`GET ${ESCALATED}`]: complaint, [`POST ${clearing}`]: {} })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })
    const user = userEvent.setup()

    expect(await screen.findByRole('heading', { name: e.missed })).toBeInTheDocument()
    expect(screen.getByText(/AUGMENTIN 1G · Hamra Pharmacy/)).toBeInTheDocument()
    // The case came from a button: the page doesn't claim a chat was deleted.
    expect(screen.getByText(e.noThread)).toBeInTheDocument()
    expect(screen.queryByText(/deleted/)).not.toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(screen.getByRole('button', { name: e.clear }))
    await user.type(screen.getByLabelText(new RegExp(`^${e.clear}`)), 'The pharmacy confirmed.')
    await user.click(screen.getByRole('button', { name: e.clear }))

    expect(await screen.findByText(e.cleared)).toBeInTheDocument()
    expect(api.sent('POST', clearing)[0].body).toEqual({ reason: 'The pharmacy confirmed.' })
  })

  it('says how a closed contest ended, and offers [Clear] only while it counts (B#61)', async () => {
    const missed = {
      id: 'dddddddd-4444-4444-8444-dddddddddddd',
      ref: 'R-7K3Q2F',
      product: 'AUGMENTIN 1G',
      pharmacy: 'Hamra Pharmacy',
      expired_at: '2026-11-15T19:00:00Z',
      contested_at: '2026-11-16T07:00:00Z',
      counts_as_no_show: true,
    }
    const closed = { ...ESCALATION, reason: 'complaint', state: 'RESOLVED', resolved_at: CONFIG.server_now } as const
    adminApi({
      [`GET ${ESCALATED}`]: {
        escalation: closed,
        thread: [],
        // A trip of two: one cleared, one that still counts.
        contested: [
          { ...missed, counts_as_no_show: false },
          { ...missed, id: 'dddddddd-5555-4555-8555-dddddddddddd', ref: 'R-9PQ4ZD', counts_as_no_show: true },
        ],
      },
    })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })

    const block = await screen.findByRole('region', { name: e.missed })
    const [cleared, counting] = within(block).getAllByText(/^R-/).map((ref) => ref.closest('.row-card') as HTMLElement)
    expect(within(cleared).getByText(s.clients.notCounted)).toHaveClass('status-pill--grey')
    expect(within(cleared).queryByRole('button', { name: e.clear })).not.toBeInTheDocument()
    expect(within(counting).getByText(s.clients.orderStates.EXPIRED_NO_SHOW)).toBeInTheDocument()
    expect(within(counting).getByRole('button', { name: e.clear })).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('has no missed pickup on a case of another kind (B#61)', async () => {
    adminApi({
      [`GET ${ESCALATED}`]: {
        ...ESCALATION_DETAIL,
        escalation: { ...ESCALATION, reason: 'client_asked_human' },
        contested: [],
      },
    })
    renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })

    expect(await screen.findByRole('heading', { name: e.summary })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: e.missed })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: e.clear })).not.toBeInTheDocument()
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
  it('is one list: the reply, what it answered, the reason, and two buttons', async () => {
    const api = adminApi({ [`POST ${REPORTED}/confirm`]: {} })
    const { container } = renderApp(<AppRoutes />, { path: '/admin/reports' })
    const user = userEvent.setup()

    expect(await screen.findByText('Take two tablets a day.')).toBeInTheDocument()
    expect(screen.getByText('How much Panadol can I take?')).toBeInTheDocument()
    // The client's comment stands apart from its English label, in its own direction.
    const comment = screen.getByText('It told me how much to take.')
    expect(comment).toHaveAttribute('dir', 'auto')
    expect(comment.parentElement).toHaveTextContent(r.comment('It told me how much to take.'))
    // Nothing to file and nothing to download: no category, no model, no export.
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Take two tablets/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(screen.getByRole('button', { name: r.confirm }))

    expect(await screen.findByText(r.reviewed)).toBeInTheDocument()
    // A real problem is a regression case (A-D6).
    expect(api.sent('POST', `${REPORTED}/confirm`)[0].body).toEqual({
      category: 'other',
      add_to_regression: true,
    })
  })

  it("reads the client's and the assistant's words in their own language (B#10)", async () => {
    adminApi({
      'GET /api/v1/admin/answer-reports': {
        items: [{ ...REPORT, asked: 'بدي بنادول', reply: 'أي عيار؟', comment: 'غلط' }],
        next_cursor: null,
      },
    })
    renderApp(<AppRoutes />, { path: '/admin/reports' })

    expect(await screen.findByText('بدي بنادول')).toHaveAttribute('lang', 'ar')
    expect(screen.getByText('أي عيار؟')).toHaveAttribute('lang', 'ar')
    expect(screen.getByText('غلط')).toHaveAttribute('lang', 'ar')
    // The English labels beside them are read as English.
    expect(screen.getByText(r.asked)).not.toHaveAttribute('lang')
    expect(screen.getByText(r.commentLabel, { exact: false })).not.toHaveAttribute('lang')
  })

  it('dismisses a report that is not a problem', async () => {
    const api = adminApi({ [`POST ${REPORTED}/dismiss`]: {} })
    renderApp(<AppRoutes />, { path: '/admin/reports' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: r.dismiss }))

    expect(await screen.findByText(r.reviewed)).toBeInTheDocument()
    expect(api.sent('POST', `${REPORTED}/dismiss`)).toHaveLength(1)
  })

  it('offers no button on an answer that was already reviewed', async () => {
    adminApi({
      'GET /api/v1/admin/answer-reports': {
        items: [{ ...REPORT, state: 'CONFIRMED', in_regression: true }],
        next_cursor: null,
      },
    })
    renderApp(<AppRoutes />, { path: '/admin/reports' })

    expect(await screen.findByText('Take two tablets a day.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: r.confirm })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: r.dismiss })).not.toBeInTheDocument()
  })
})

describe('The audit log and the demo clock (AS-11, AS-12)', () => {
  it('shows who changed what, and filters by kind', async () => {
    const api = adminApi()
    const { container } = renderApp(<AppRoutes />, { path: '/admin/audit' })
    const user = userEvent.setup()

    expect(await screen.findByRole('rowheader', { name: 'pharmacy.approve' })).toBeInTheDocument()
    expect(screen.getByText('status: PENDING → status: APPROVED')).toBeInTheDocument()
    // The short ID is a button of its own style: the wrapping style of the Change column
    // made it run into that column.
    const id = screen.getByRole('button', { name: PHARMACY_ID.slice(0, 8) })
    expect(id).toHaveClass('audit-id')
    expect(id).not.toHaveClass('audit-change')
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

describe("The console's lists and questions (design review B#27, B#28, B#44, B#56, B#63)", () => {
  it('gives the focus to a question when it opens, back to its button when it closes, and starts each one empty', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: one.reject }))
    expect(screen.getByLabelText(one.rejectReason)).toHaveFocus()
    await user.type(screen.getByLabelText(one.rejectReason), 'test')
    await user.click(screen.getByRole('button', { name: one.cancel }))
    expect(screen.getByRole('button', { name: one.reject })).toHaveFocus()

    // What was typed for Reject is not the question the pharmacy would read.
    await user.click(screen.getByRole('button', { name: one.askMore }))
    expect(screen.getByLabelText(one.askReason)).toHaveValue('')
    expect(screen.getByLabelText(one.askReason)).toHaveFocus()
    await user.click(screen.getByRole('button', { name: one.cancel }))
    expect(screen.getByRole('button', { name: one.askMore })).toHaveFocus()
    expect(api.calls.every((call) => call.method === 'GET')).toBe(true)
  })

  it('says a refusal in the panel whose button caused it', async () => {
    adminApi({ [`POST ${PHARMACY}/approve`]: refusal(403, 'FORBIDDEN') })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: one.approve }))

    const decide = screen.getByRole('region', { name: one.decide })
    expect(await within(decide).findByText(errorMessage('FORBIDDEN'))).toBeInTheDocument()
    // Said once, there: not also at the top of the page.
    expect(screen.getAllByText(errorMessage('FORBIDDEN'))).toHaveLength(1)
  })

  it('keeps the Pharmacies tab lit on a pharmacy of the list', async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })

    const tabs = await screen.findByRole('navigation', { name: s.nav })
    expect(await within(tabs).findByRole('link', { name: 'Pharmacies (1)' })).toHaveAttribute('aria-current', 'page')
    expect(within(tabs).getByRole('link', { name: 'Escalations (2)' })).not.toHaveAttribute('aria-current')
    // [Log out] is not one of the tabs.
    expect(within(tabs).queryByRole('button', { name: s.logOut })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: s.logOut })).toBeInTheDocument()
  })

  it('goes back to the list as it was left: its tab and what was typed', async () => {
    const api = adminApi({ [`GET ${PHARMACY}`]: { ...WAITING, status: 'APPROVED' } })
    renderApp(<AppRoutes />, { path: '/admin' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('tab', { name: s.pharmacies.statuses.APPROVED }))
    await user.type(screen.getByLabelText(s.pharmacies.search), 'Ham')
    await user.click(await screen.findByRole('link', { name: /^Hamra Pharmacy/ }))
    await user.click(await screen.findByRole('link', { name: s.back }))

    expect(await screen.findByRole('tab', { name: s.pharmacies.statuses.APPROVED })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByLabelText(s.pharmacies.search)).toHaveValue('Ham')
    const asked = api.sent('GET', '/api/v1/admin/pharmacies?')
    expect(asked[asked.length - 1].path).toContain('status=APPROVED')
    expect(asked[asked.length - 1].path).toContain('q=Ham')
  })

  it('goes back to the closed escalations from a closed one', async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: '/admin/escalations' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('tab', { name: e.resolved }))
    await user.click(await screen.findByRole('link', { name: /Glucophage 850/ }))
    await user.click(await screen.findByRole('link', { name: s.back }))

    expect(await screen.findByRole('tab', { name: e.resolved })).toHaveAttribute('aria-selected', 'true')
  })

  it('says in red when a page could not be read, and a mistyped address is a page not found', async () => {
    adminApi({ [`GET ${PHARMACY}`]: refusal(422, 'VALIDATION_ERROR') })
    renderApp(<AppRoutes />, { path: `/admin/pharmacies/${PHARMACY_ID}` })

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(errorMessage('NOT_FOUND'))
    expect(alert).toHaveClass('banner--red')
    // A heading in the main area, for the focus and the tab's title (B#19, B#34).
    const heading = screen.getByRole('heading', { level: 1, name: s.pharmacies.title })
    expect(screen.getByRole('main')).toContainElement(heading)
  })

  it.each([
    ['clients', '/admin/clients/', 'GET /api/v1/admin/clients/'],
    ['escalations', '/admin/escalations/', 'GET /api/v1/admin/escalations/'],
  ])('gives a %s page that could not be read its heading too', async (section, path, route) => {
    const id = '99999999-9999-4999-8999-999999999999'
    adminApi({ [`${route}${id}`]: refusal(503, 'SERVICE_UNAVAILABLE') })
    const { container } = renderApp(<AppRoutes />, { path: `${path}${id}` })

    const title = section === 'clients' ? s.clients.title : e.title
    const heading = await screen.findByRole('heading', { level: 1, name: title })
    expect(screen.getByRole('main')).toContainElement(heading)
    expect(await screen.findByRole('alert')).toHaveTextContent(errorMessage('SERVICE_UNAVAILABLE'))
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('marks an emergency claim in amber, as on the design canvas', async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: '/admin/escalations' })

    expect(await screen.findByText(e.reasons.emergency_claim)).toHaveClass('status-pill--amber')
  })

  it('says a refused clear under the missed pickup it is about', async () => {
    const contested = {
      id: 'dddddddd-4444-4444-8444-dddddddddddd',
      ref: 'R-7K3Q2F',
      product: 'AUGMENTIN 1G',
      pharmacy: 'Hamra Pharmacy',
      expired_at: '2026-11-15T19:00:00Z',
      contested_at: '2026-11-16T07:00:00Z',
      counts_as_no_show: true,
    }
    const clearing = `/api/v1/admin/reservations/${contested.id}/clear-no-show`
    adminApi({
      [`GET ${ESCALATED}`]: { ...ESCALATION_DETAIL, contested: [contested] },
      [`POST ${clearing}`]: refusal(403, 'FORBIDDEN'),
    })
    renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: e.clear }))
    await user.type(screen.getByLabelText(new RegExp(`^${e.clear}`)), 'Checked.')
    await user.click(screen.getByRole('button', { name: e.clear }))

    const missed = screen.getByRole('region', { name: e.missed })
    expect(await within(missed).findByText(errorMessage('FORBIDDEN'))).toBeInTheDocument()
  })

  it('says a refused review under the answer it is about', async () => {
    adminApi({ [`POST ${REPORTED}/dismiss`]: refusal(403, 'FORBIDDEN') })
    renderApp(<AppRoutes />, { path: '/admin/reports' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: r.dismiss }))

    const row = screen.getByRole('article', { name: strings.chat.report.reasons.unsafe })
    expect(await within(row).findByText(errorMessage('FORBIDDEN'))).toBeInTheDocument()
  })

  it('filters the audit log by the actions on clients and on flags', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin/audit' })
    const user = userEvent.setup()

    const kind = await screen.findByRole('combobox', { name: s.audit.kind })
    await user.selectOptions(kind, 'client.')
    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/admin/audit').some((call) => call.path.includes('action=client.'))).toBe(true),
    )
    await user.selectOptions(kind, 'abuse_flag.')
    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/admin/audit').some((call) => call.path.includes('action=abuse_flag.'))).toBe(
        true,
      ),
    )
  })
})
