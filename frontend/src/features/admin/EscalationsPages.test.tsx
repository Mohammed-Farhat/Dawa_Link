import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
import { ADMIN, ESCALATION, ESCALATION_DETAIL, ESCALATION_ID, OVERVIEW, REPORT } from '../../test/admin'
import { accessibilityProblems, CONFIG, DISTRICTS, loggedIn, pretendApi, renderApp } from '../../test/render'
import { when } from './data'

// A new ask on an open case is seen as a new ask; a client who writes to the team is seen;
// the lists are numbered pages (the owner, 2026-11-22 and 2026-11-23).

const s = strings.admin
const e = s.escalations
const r = s.reports
const ESCALATED = `/api/v1/admin/escalations/${ESCALATION_ID}`

function adminApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': ADMIN,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/admin/overview': OVERVIEW,
    ...more,
  })
}

const ASKED_AGAIN = {
  ...ESCALATION,
  id: 'eeeeeeee-5555-4555-8555-eeeeeeeeeeee',
  reason: 'complaint',
  state: 'IN_PROGRESS',
  summary: 'The client says they collected order R-7K3Q2F.',
  reasons: ['complaint', 'client_asked_human'],
  last_summary: 'Client asks for a person about the missed pickup.',
  last_replied_at: '2026-11-16T07:45:00Z',
  new_ask_since_reply: true,
  client_wrote_at: '2026-11-16T07:50:00Z',
  hold_ends_at: '2026-11-16T19:45:00Z',
} as const

describe('The list of escalations', () => {
  it('shows every reason of a case, its newest ask, and what waits for the team', async () => {
    adminApi({ 'GET /api/v1/admin/escalations': { items: [ASKED_AGAIN], next_cursor: null, total: 1 } })
    const { container } = renderApp(<AppRoutes />, { path: '/admin/escalations' })

    const row = (await screen.findByText(ASKED_AGAIN.last_summary)).closest('article') as HTMLElement
    expect(within(row).getByText(e.reasons.complaint)).toBeInTheDocument()
    expect(within(row).getByText(e.reasons.client_asked_human)).toBeInTheDocument()
    expect(within(row).getByText(e.newAsk)).toBeInTheDocument()
    expect(within(row).getByText(e.clientWrote(when(ASKED_AGAIN.client_wrote_at)))).toBeInTheDocument()
    // The first ask's words are on the case's page, not in the list.
    expect(within(row).queryByText(ASKED_AGAIN.summary)).not.toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('is numbered pages: page 2 asks the API for the rows after the first 25', async () => {
    const api = adminApi({ 'GET /api/v1/admin/escalations': { items: [ESCALATION], next_cursor: '25', total: 26 } })
    renderApp(<AppRoutes />, { path: '/admin/escalations?closed=1' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: strings.pager.page(2) }))

    const asked = api.sent('GET', '/api/v1/admin/escalations').map((call) => call.path)
    expect(asked[0]).toContain('state=RESOLVED')
    expect(asked[0]).toContain('cursor=0')
    expect(asked.at(-1)).toContain('cursor=25')
    expect(screen.getByText(strings.pager.summary(2, 2, 26))).toBeInTheDocument()
  })
})

describe("An escalation's page", () => {
  it('marks where another chat of the client starts, and says the chat is with the team', async () => {
    adminApi({
      [`GET ${ESCALATED}`]: {
        ...ESCALATION_DETAIL,
        escalation: ASKED_AGAIN,
        thread: [
          ...ESCALATION_DETAIL.thread,
          {
            seq: 1,
            author: 'client',
            text: 'talk to a person asap',
            cards: [],
            created_at: '2026-11-16T07:42:00Z',
            starts_another_chat: true,
          },
        ],
      },
    })
    const { container } = renderApp(<AppRoutes />, { path: `/admin/escalations/${ESCALATION_ID}` })

    expect(await screen.findByText('talk to a person asap')).toBeInTheDocument()
    expect(screen.getAllByText(e.anotherChat)).toHaveLength(1)
    expect(screen.getByText(e.withTeam(when(ASKED_AGAIN.hold_ends_at)))).toBeInTheDocument()
    expect(screen.getByText(e.newAsk)).toBeInTheDocument()
    // One reply box and [Close this case], as the owner set them: nothing more.
    expect(screen.getByRole('button', { name: e.send })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: e.close })).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })
})

describe('The reported answers', () => {
  it('are numbered pages, and a tab is kept in the address', async () => {
    const api = adminApi({ 'GET /api/v1/admin/answer-reports': { items: [REPORT], next_cursor: '25', total: 30 } })
    renderApp(<AppRoutes />, { path: '/admin/reports' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: strings.pager.page(2) }))
    await user.click(screen.getByRole('tab', { name: r.states.CONFIRMED }))

    const asked = api.sent('GET', '/api/v1/admin/answer-reports').map((call) => call.path)
    expect(asked).toContainEqual(expect.stringContaining('cursor=25'))
    // A new tab starts on its first page.
    expect(asked.at(-1)).toContain('state=CONFIRMED')
    expect(asked.at(-1)).toContain('cursor=0')
  })
})
