import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Schemas } from '../../api/client'
import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
import {
  ADMIN,
  AUDIT_EVENT,
  CATALOG_ROW,
  CLIENT_ROW,
  HEALTH,
  OVERVIEW,
  PHARMACY_ID,
  WAITING,
  WAITING_ROW,
} from '../../test/admin'
import { accessibilityProblems, CLIENT, CONFIG, DISTRICTS, loggedIn, pretendApi, renderApp } from '../../test/render'
import { details, SENTENCES, sentence } from './auditWords'

vi.mock('../pharmacy/PinMap', () => ({ default: () => <div>the map</div> }))

// The admin's lists as numbered pages, the audit log in words, the Health page's limits
// and the catalog's columns (the owner, 2026-11-23).

const s = strings.admin
const a = s.audit
const h = s.health
const k = s.catalog
const pages = strings.pager

function adminApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': ADMIN,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/admin/overview': OVERVIEW,
    'GET /api/v1/admin/pharmacies': { items: [WAITING_ROW], next_cursor: '25', total: 60 },
    [`GET /api/v1/admin/pharmacies/${PHARMACY_ID}`]: WAITING,
    'GET /api/v1/admin/clients': { items: [CLIENT_ROW], next_cursor: '25', total: 80 },
    'GET /api/v1/admin/catalog/products': { items: [CATALOG_ROW], next_cursor: '25', total: 5628 },
    'GET /api/v1/admin/catalog/imports': { items: [] },
    'GET /api/v1/admin/audit': { items: [AUDIT_EVENT], next_cursor: '42', total: 30 },
    'GET /api/v1/admin/health': HEALTH,
    ...more,
  })
}

const pager = () => screen.getByRole('navigation', { name: pages.label })

describe('Numbered pages on the admin lists', () => {
  it('pharmacies: page 2 asks for rows 26 to 50, and survives "Back to the list"', async () => {
    const api = adminApi()
    const { container } = renderApp(<AppRoutes />, { path: '/admin?status=APPROVED&q=hamra' })
    const user = userEvent.setup()

    expect(await screen.findByText(pages.summary(1, 3, 60))).toBeInTheDocument()
    await user.click(within(pager()).getByRole('button', { name: pages.page(2) }))

    await waitFor(() =>
      expect(
        api.sent('GET', '/api/v1/admin/pharmacies').some(
          (call) => call.path.includes('cursor=25') && call.path.includes('limit=25') && call.path.includes('q=hamra'),
        ),
      ).toBe(true),
    )
    expect(await accessibilityProblems(container)).toEqual([])
    // The typed text is written back to the address by the page: that must not lose the page.
    await user.click(await screen.findByRole('link', { name: /Hamra Pharmacy/ }))
    await user.click(await screen.findByRole('link', { name: s.back }))
    expect(await screen.findByText(pages.summary(2, 3, 60))).toBeInTheDocument()
    expect(within(pager()).getByRole('button', { name: pages.page(2) })).toHaveAttribute('aria-current', 'page')
  })

  it('pharmacies: a new tab goes back to page 1', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin?status=APPROVED&page=2' })
    const user = userEvent.setup()

    expect(await screen.findByText(pages.summary(2, 3, 60))).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: s.pharmacies.statuses.SUSPENDED }))

    await waitFor(() =>
      expect(
        api.sent('GET', '/api/v1/admin/pharmacies').some(
          (call) => call.path.includes('status=SUSPENDED') && call.path.includes('cursor=0'),
        ),
      ).toBe(true),
    )
  })

  it('clients: the page is in the address with the filters', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin/clients?show=look&page=3' })

    expect(await screen.findByText(pages.summary(3, 4, 80))).toBeInTheDocument()
    expect(
      api.sent('GET', '/api/v1/admin/clients').some(
        (call) => call.path.includes('having=look') && call.path.includes('cursor=50'),
      ),
    ).toBe(true)
    // No "Show more" left on a list with pages.
    expect(screen.queryByRole('button', { name: s.more })).not.toBeInTheDocument()
  })

  it('the catalog: a page, and typing goes back to the first', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin/catalog' })
    const user = userEvent.setup()

    expect(await screen.findByText(pages.summary(1, 226, 5628))).toBeInTheDocument()
    await user.click(within(pager()).getByRole('button', { name: pages.next }))
    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/admin/catalog/products').some((call) => call.path.includes('cursor=25'))).toBe(
        true,
      ),
    )
    await user.type(screen.getByLabelText(k.search), 'x')

    await waitFor(() =>
      expect(
        api.sent('GET', '/api/v1/admin/catalog/products').some(
          (call) => call.path.includes('q=x') && call.path.includes('cursor=0'),
        ),
      ).toBe(true),
    )
  })

  it('the audit log pages by offset', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin/audit?kind=pharmacies' })
    const user = userEvent.setup()

    await user.click(await within(await screen.findByRole('navigation', { name: pages.label })).findByRole('button', { name: pages.page(2) }))

    await waitFor(() =>
      expect(
        api.sent('GET', '/api/v1/admin/audit').some(
          (call) => call.path.includes('offset=25') && call.path.includes('kind=pharmacies'),
        ),
      ).toBe(true),
    )
    // Numbered pages never send the last ID seen.
    expect(api.sent('GET', '/api/v1/admin/audit').every((call) => !call.path.includes('cursor='))).toBe(true)
  })
})

type Row = Schemas['AuditRow']

const CLIENT_SHORT = CLIENT.id.slice(0, 8)

const ROWS: Row[] = [
  {
    ...AUDIT_EVENT,
    id: 50,
    actor_type: 'CLIENT',
    actor_id: CLIENT.id,
    entity_type: 'order',
    entity_id: 'abababab-1111-4111-8111-abababababab',
    action: 'order.no_show_contested',
    known_action: 'order.no_show_contested',
    who: { kind: 'client', name: null, id: CLIENT.id },
    subject: { kind: 'client', id: CLIENT.id },
    state_from: null,
    state_to: 'EXPIRED_NO_SHOW',
  },
  {
    ...AUDIT_EVENT,
    id: 49,
    actor_type: 'PHARMACY',
    actor_id: PHARMACY_ID,
    entity_type: 'pharmacy',
    action: 'pharmacy.settings',
    known_action: 'pharmacy.settings',
    who: { kind: 'pharmacy', name: 'Hamra Pharmacy', id: PHARMACY_ID },
    subject: { kind: 'pharmacy', id: PHARMACY_ID },
    changed: ['hours', 'pickup_days'],
    state_from: null,
    state_to: null,
  },
  {
    ...AUDIT_EVENT,
    id: 48,
    action: 'pharmacy.suspend',
    known_action: 'pharmacy.suspend',
    state_from: 'APPROVED',
    state_to: 'SUSPENDED',
    counts: { offers_cancelled: 2, asks_withdrawn: 1 },
    reason: 'Sold boxes it did not have.',
  },
  {
    ...AUDIT_EVENT,
    id: 47,
    actor_type: 'SYSTEM',
    actor_id: null,
    entity_type: 'claim',
    action: 'claim.state',
    known_action: 'claim.state',
    who: { kind: 'system', name: null, id: null },
    subject: null,
    state_from: 'ACTIVE',
    state_to: 'EXPIRED',
  },
  {
    ...AUDIT_EVENT,
    id: 46,
    actor_type: 'ADMIN',
    entity_type: 'app_state',
    entity_id: null,
    action: 'clock.advance',
    known_action: 'clock.advance',
    subject: { kind: 'clock', id: null },
    changed: ['offset_seconds'],
    state_from: null,
    state_to: null,
  },
  {
    ...AUDIT_EVENT,
    id: 45,
    action: 'thing.from_the_future',
    known_action: null,
    who: { kind: 'agent', name: null, id: null },
    subject: null,
    state_from: null,
    state_to: null,
  },
]

describe('The audit log in words', () => {
  it('says who did what, the fields that changed and the page it is about', async () => {
    adminApi({ 'GET /api/v1/admin/audit': { items: ROWS, next_cursor: null, total: ROWS.length } })
    const { container } = renderApp(<AppRoutes />, { path: '/admin/audit' })

    // A client is "A client" and the short ID of their page, never a name.
    const contested = await screen.findByRole('rowheader', { name: a.actions['order.no_show_contested'] })
    const contestRow = contested.closest('tr')!
    expect(within(contestRow).getByText(a.who.client)).toBeInTheDocument()
    expect(within(contestRow).getByText(CLIENT_SHORT)).toBeInTheDocument()
    expect(within(contestRow).getByRole('link', { name: a.links.client(CLIENT_SHORT) })).toHaveAttribute(
      'href',
      `/admin/clients/${CLIENT.id}`,
    )
    expect(screen.queryByText(CLIENT.full_name)).not.toBeInTheDocument()

    // A pharmacy by its name; the fields in words, never their values.
    const settings = screen.getByRole('rowheader', { name: /changed its opening hours or its pickup time/ }).closest('tr')!
    expect(within(settings).getAllByText('Hamra Pharmacy').length).toBeGreaterThan(0)
    expect(within(settings).getByText(a.changed('opening hours, pickup time'))).toBeInTheDocument()

    // A move between two states, how many things it ended, and the admin's reason.
    const suspended = screen.getByRole('rowheader', { name: /suspended a pharmacy/ }).closest('tr')!
    expect(
      within(suspended).getByText(
        [a.moved('approved', 'suspended'), '2 offers cancelled', '1 ask withdrawn'].join(' · '),
      ),
    ).toBeInTheDocument()
    expect(within(suspended).getByText('Sold boxes it did not have.')).toBeInTheDocument()

    // A state the sentence already says is not said twice; the system has no link.
    const expired = screen.getByRole('rowheader', { name: a.byState['claim.state']!.EXPIRED! }).closest('tr')!
    expect(within(expired).getByText(a.who.system)).toBeInTheDocument()
    expect(within(expired).queryByRole('link')).not.toBeInTheDocument()

    // The demo clock's page, in demo mode.
    const table = screen.getByRole('region', { name: a.table })
    expect(within(table).getByRole('link', { name: a.links.clock })).toHaveAttribute('href', '/admin/clock')
    // A code no sentence knows is said as it is stored.
    expect(screen.getByRole('rowheader', { name: a.unknownAction('thing.from_the_future') })).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('has no link to the demo clock outside demo mode', async () => {
    adminApi({
      'GET /api/v1/admin/overview': { ...OVERVIEW, demo_mode: false },
      'GET /api/v1/admin/audit': { items: [ROWS[4]], next_cursor: null, total: 1 },
    })
    renderApp(<AppRoutes />, { path: '/admin/audit' })

    expect(await screen.findByRole('rowheader', { name: /moved the demo clock forward/ })).toBeInTheDocument()
    const table = screen.getByRole('region', { name: a.table })
    await waitFor(() => expect(within(table).queryByRole('link', { name: a.links.clock })).not.toBeInTheDocument())
  })

  it('[Only this] shows the events about one thing, and [Show every event] all again', async () => {
    const api = adminApi({ 'GET /api/v1/admin/audit': { items: [ROWS[0]], next_cursor: null, total: 1 } })
    renderApp(<AppRoutes />, { path: '/admin/audit' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: a.onlyLabel('reservation') }))

    expect(await screen.findByText(a.about('reservation'))).toBeInTheDocument()
    await waitFor(() =>
      expect(
        api.sent('GET', '/api/v1/admin/audit').some(
          (call) => call.path.includes('entity_type=order') && call.path.includes(`entity_id=${ROWS[0]!.entity_id}`),
        ),
      ).toBe(true),
    )
    await user.click(screen.getByRole('button', { name: a.showAll }))
    expect(screen.queryByText(a.about('reservation'))).not.toBeInTheDocument()
  })

  it('ignores an address that names no thing', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin/audit?about=order:not-an-id' })

    expect(await screen.findByRole('rowheader', { name: /approved a pharmacy/ })).toBeInTheDocument()
    expect(api.sent('GET', '/api/v1/admin/audit').every((call) => !call.path.includes('entity_id'))).toBe(true)
  })
})

describe('Every audit code has a sentence', () => {
  it('covers every code of the API description (docs/openapi.json), and no other', async () => {
    // Read from the disk, as `app/global.test.ts` reads the stylesheet: the website's own
    // code has no Node types, hence the name. The tests run from frontend/.
    const fs = (await import(/* @vite-ignore */ ['node', 'fs'].join(':'))) as {
      readFileSync: (file: string, encoding: 'utf8') => string
    }
    const described = JSON.parse(fs.readFileSync('../docs/openapi.json', 'utf8')) as {
      components: { schemas: { AuditAction: { enum: string[] } } }
    }
    const codes = described.components.schemas.AuditAction.enum

    expect(codes.length).toBeGreaterThan(60)
    for (const code of codes) {
      expect(SENTENCES[code as keyof typeof SENTENCES], code).toBeTruthy()
    }
    expect(Object.keys(SENTENCES).sort()).toEqual([...codes].sort())
  })

  it('falls back to a neutral sentence that shows an unknown code', () => {
    const unknown = { ...AUDIT_EVENT, action: 'brand.new_thing', known_action: null }
    expect(sentence(unknown)).toBe(a.unknownAction('brand.new_thing'))
    // And says nothing it was not sent.
    expect(details({ ...unknown, state_from: null, state_to: null })).toEqual([])
  })
})

describe('Health: each client has a limit; the budget is for everyone', () => {
  it("reads the server's numbers, with no dollar figure for a client's limit", async () => {
    adminApi()
    const { container } = renderApp(<AppRoutes />, { path: '/admin/health' })

    const limits = await screen.findByRole('region', { name: h.limits })
    expect(within(limits).getByText(h.perClientValue(100, 3_000_000))).toBeInTheDocument()
    expect(within(limits).getByText(h.atLimitValue(2, 1))).toBeInTheDocument()
    expect(within(limits).getByText(h.perClientHint)).toBeInTheDocument()
    expect(within(limits).queryByText(/\$/)).not.toBeInTheDocument()

    const budget = screen.getByRole('region', { name: h.budget })
    expect(within(budget).getByText(h.spentOf('$12.40', '$20.00'))).toBeInTheDocument()
    expect(within(budget).getByText(h.budgetDay(10))).toBeInTheDocument()
    expect(within(budget).getByText(h.spentOf('$0.35', '$2.00'))).toBeInTheDocument()
    expect(within(budget).getByText(h.budgetHint)).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })
})

describe('The catalog in its own columns', () => {
  it('shows strength, form, pack and maker apart, a bare pack as "Pack: 30", an empty one as a dash', async () => {
    adminApi({
      'GET /api/v1/admin/catalog/products': {
        items: [CATALOG_ROW, { ...CATALOG_ROW, id: 'ffffffff-7777-4777-8777-ffffffffffff', name: 'SALINOL 0.9%', strength: null, form: 'Solution', pack: '500ml', manufacturer: null, controlled: false }],
        next_cursor: null,
        total: 2,
      },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/admin/catalog' })

    const locked = (await screen.findByRole('rowheader', { name: 'LOCKEDOL 10MG' })).closest('tr')!
    expect(within(locked).getByText('10mg')).toBeInTheDocument()
    expect(within(locked).getByText('Tablet')).toBeInTheDocument()
    expect(within(locked).getByText(k.packOf('30'))).toBeInTheDocument()
    expect(within(locked).getByText('Invented Labs')).toBeInTheDocument()
    const salt = screen.getByRole('rowheader', { name: 'SALINOL 0.9%' }).closest('tr')!
    expect(within(salt).getByText('500ml')).toBeInTheDocument()
    expect(within(salt).getAllByText(k.emptyLabel)).toHaveLength(2)
    expect(screen.getByText(k.help)).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: k.columns.maker })).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })
})
