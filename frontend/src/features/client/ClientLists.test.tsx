import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '../../api/client'
import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
import { PHARMACIST, PROFILE } from '../../test/pharmacy'
import {
  accessibilityProblems,
  CLIENT,
  CONFIG,
  DISTRICTS,
  loggedIn,
  pretendApi,
  renderApp,
  RESERVATION,
} from '../../test/render'

// The client's long lists in numbered pages of 25, the page in the address (the owner,
// 2026-11-23): the History of My medicines, and the notifications of both portals.

const NOW = CONFIG.server_now
const p = strings.pager
const m = strings.medicines

const PAST = {
  ...RESERVATION,
  state: 'PICKED_UP',
  status_text: 'Picked up',
  closed_at: NOW,
} satisfies Schemas['Reservation']

const note = (id: number) =>
  ({
    id,
    type: 'CN-3',
    title: `Reserved: notification ${id}`,
    lines: [],
    link: null,
    read: true,
    created_at: '2026-11-16T07:30:00Z',
  }) satisfies Schemas['NotificationOut']

function clientApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/watches': { items: [], server_now: NOW },
    'GET /api/v1/notifications/unread-count': { count: 0 },
    ...more,
  })
}

describe('The History of My medicines', () => {
  it('comes in numbered pages, its tab and page in the address', async () => {
    const api = clientApi({
      'GET /api/v1/reservations': (call: { path: string }) =>
        call.path.includes('view=history')
          ? {
              items: [{ ...PAST, ref: call.path.includes('cursor=25') ? 'R-LATE22' : 'R-NEW111' }],
              next_cursor: call.path.includes('cursor=25') ? null : '25',
              total: 26,
              server_now: NOW,
            }
          : { items: [], next_cursor: null, total: 0, server_now: NOW },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/medicines?view=history' })
    const user = userEvent.setup()

    expect(await screen.findByText('R-NEW111')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: m.history })).toHaveAttribute('aria-selected', 'true')
    const pages = screen.getByRole('navigation', { name: p.label })
    expect(within(pages).getByText(p.summary(1, 2, 26))).toBeInTheDocument()
    await user.click(within(pages).getByRole('button', { name: p.next }))

    expect(await screen.findByText('R-LATE22')).toBeInTheDocument()
    const asked = api.sent('GET', '/api/v1/reservations?view=history').map((call) => call.path)
    expect(asked).toContainEqual(expect.stringContaining('cursor=25&limit=25'))
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('has no pages on Active, which holds a few reservations at most', async () => {
    clientApi({
      'GET /api/v1/reservations': { items: [RESERVATION], next_cursor: null, total: 1, server_now: NOW },
    })
    renderApp(<AppRoutes />, { path: '/medicines' })

    expect(await screen.findByText(RESERVATION.ref)).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: m.active })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('navigation', { name: p.label })).not.toBeInTheDocument()
  })
})

describe('The notifications', () => {
  it('come in numbered pages, asked for with an offset', async () => {
    const api = clientApi({
      'GET /api/v1/notifications': (call: { path: string }) => ({
        items: [note(call.path.includes('offset=25') ? 1 : 26)],
        next_cursor: null,
        total: 26,
        unread: 0,
      }),
    })
    renderApp(<AppRoutes />, { path: '/notifications' })
    const user = userEvent.setup()

    expect(await screen.findByText('Reserved: notification 26')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: p.page(2) }))

    expect(await screen.findByText('Reserved: notification 1')).toBeInTheDocument()
    await waitFor(() =>
      expect(api.sent('GET', '/api/v1/notifications?').map((call) => call.path)).toContainEqual(
        expect.stringContaining('offset=25&limit=25'),
      ),
    )
  })

  it("page the pharmacy's notifications the same way (PS-11)", async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': PHARMACIST,
      'GET /api/v1/pharmacy/me': PROFILE,
      'GET /api/v1/notifications': { items: [note(40)], next_cursor: null, total: 60, unread: 0 },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/notifications?page=3' })

    expect(await screen.findByText('Reserved: notification 40')).toBeInTheDocument()
    expect(screen.getByText(p.summary(3, 3, 60))).toBeInTheDocument()
  })
})
