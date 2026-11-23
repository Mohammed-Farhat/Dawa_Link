import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../../app/App'
import { errorMessage, strings } from '../../strings/en'
import {
  ADMIN,
  AUDIT_EVENT,
  CATALOG_ROW,
  CLIENT_DETAIL,
  CLIENT_ROW,
  ESCALATION,
  OVERVIEW,
  REPORT,
  WAITING_ROW,
} from '../../test/admin'
import { accessibilityProblems, CLIENT, CONFIG, DISTRICTS, loggedIn, pretendApi, refusal, renderApp } from '../../test/render'

vi.mock('../pharmacy/PinMap', () => ({ default: () => <div>the map</div> }))

const s = strings.admin
const c = s.clients

const A_CLIENT = `/api/v1/admin/clients/${CLIENT.id}`
const DELETED = { ...CLIENT_DETAIL, client: { ...CLIENT_ROW, status: 'DELETED', paused_until: null }, contested: [] }

function adminApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': ADMIN,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/admin/overview': OVERVIEW,
    'GET /api/v1/admin/pharmacies': { items: [WAITING_ROW], next_cursor: null },
    'GET /api/v1/admin/clients': { items: [CLIENT_ROW], next_cursor: null },
    [`GET ${A_CLIENT}`]: CLIENT_DETAIL,
    'GET /api/v1/admin/catalog/products': { items: [CATALOG_ROW], next_cursor: null },
    'GET /api/v1/admin/catalog/imports': { items: [] },
    'GET /api/v1/admin/escalations': { items: [ESCALATION], next_cursor: null },
    'GET /api/v1/admin/answer-reports': { items: [REPORT], next_cursor: null },
    'GET /api/v1/admin/audit': { items: [AUDIT_EVENT], next_cursor: null },
    ...more,
  })
}

describe('A client who deleted their account (R-AU10)', () => {
  it('has no contact button and no actions: one line says why', async () => {
    const api = adminApi({ [`GET ${A_CLIENT}`]: DELETED })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })

    const contact = await screen.findByRole('region', { name: c.contact })
    expect(within(contact).getByText(c.deletedContact)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: c.showContact })).not.toBeInTheDocument()
    expect(screen.queryByText(c.contactHint)).not.toBeInTheDocument()
    // A block is shown only when it has something to say.
    expect(screen.queryByRole('region', { name: c.actions })).not.toBeInTheDocument()
    expect(screen.getByText(c.statuses.DELETED)).toBeInTheDocument()
    expect(api.sent('GET', `${A_CLIENT}/contact`)).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('says the same when the account was deleted while the page was open', async () => {
    adminApi({
      [`GET ${A_CLIENT}/contact`]: refusal(404, 'NOT_FOUND', { reason: 'ACCOUNT_DELETED' }),
    })
    renderApp(<AppRoutes />, { path: `/admin/clients/${CLIENT.id}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: c.showContact }))

    expect(await screen.findByText(c.deletedContact)).toBeInTheDocument()
    expect(screen.queryByText(errorMessage('NOT_FOUND'))).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: c.showContact })).not.toBeInTheDocument()
  })

  it('are found with the Deleted filter', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: '/admin/clients' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('tab', { name: c.statuses.DELETED }))

    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/admin/clients').some((call) => call.path.includes('status=DELETED'))).toBe(true),
    )
  })
})

describe('A list that could not be loaded says so, with [Try again]', () => {
  it.each([
    ['pharmacies', '/admin', 'GET /api/v1/admin/pharmacies'],
    ['clients', '/admin/clients', 'GET /api/v1/admin/clients'],
    ['catalog', '/admin/catalog', 'GET /api/v1/admin/catalog/products'],
    ['escalations', '/admin/escalations', 'GET /api/v1/admin/escalations'],
    ['reports', '/admin/reports', 'GET /api/v1/admin/answer-reports'],
    ['audit', '/admin/audit', 'GET /api/v1/admin/audit'],
  ])('the %s', async (_name, path, route) => {
    const api = adminApi({ [route]: refusal(503, 'SERVICE_UNAVAILABLE') })
    renderApp(<AppRoutes />, { path })
    const user = userEvent.setup()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(s.listFailed)
    expect(alert).toHaveTextContent(errorMessage('SERVICE_UNAVAILABLE'))
    const asked = api.sent('GET', route.slice(4)).length
    await user.click(within(alert).getByRole('button', { name: strings.common.tryAgain }))
    await waitFor(() => expect(api.sent('GET', route.slice(4)).length).toBeGreaterThan(asked))
  })
})

describe("The lists' boxes take no more than the API", () => {
  it('an order number: 20 characters, an old longer address included', async () => {
    const api = adminApi()
    renderApp(<AppRoutes />, { path: `/admin/clients?ref=${'R'.repeat(30)}` })

    const box = await screen.findByLabelText(c.ref)
    expect(box).toHaveAttribute('maxlength', '20')
    expect(box).toHaveValue('R'.repeat(20))
    await waitFor(() => expect(api.sent('GET', '/api/v1/admin/clients').length).toBeGreaterThan(0))
    expect(api.sent('GET', '/api/v1/admin/clients').every((call) => !call.path.includes('R'.repeat(21)))).toBe(true)
  })

  it('a pharmacy or a medicine: 100 characters', async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: `/admin?q=${'x'.repeat(120)}` })
    expect(await screen.findByLabelText(s.pharmacies.search)).toHaveAttribute('maxlength', '100')
    expect(screen.getByLabelText(s.pharmacies.search)).toHaveValue('x'.repeat(100))
  })

  it('the catalog: 100 characters', async () => {
    adminApi()
    renderApp(<AppRoutes />, { path: '/admin/catalog' })
    expect(await screen.findByLabelText(s.catalog.search)).toHaveAttribute('maxlength', '100')
  })
})
