import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '../../../api/client'
import { AppRoutes } from '../../../app/App'
import { strings } from '../../../strings/en'
import {
  accessibilityProblems,
  answer,
  CARD_ID,
  CHAT_ID,
  CLIENT,
  CONFIG,
  DISTRICTS,
  loggedIn,
  message,
  page,
  pretendApi,
  refusal,
  renderApp,
  RESERVATION,
  RESERVE_CARD,
} from '../../../test/render'

const r = strings.request
const NOW = CONFIG.server_now
const REQUEST_ID = '99999999-9999-4999-8999-999999999999'
const THREAD_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const OFFER_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

function item(name: string, more: Partial<Schemas['RequestItem']> = {}): Schemas['RequestItem'] {
  return {
    id: `item-${name}`,
    position: 1,
    product: { ...RESERVATION.product, name },
    qty: 1,
    qty_secured: 0,
    days_of_use: 1,
    max_price: null,
    state: 'SEARCHING',
    status_text: 'Searching',
    reservations: [],
    waiting: null,
    ...more,
  }
}

const REQUEST = {
  id: REQUEST_ID,
  ref: 'Q-4HX9TM',
  state: 'OPEN',
  outcome: null,
  alternatives_ok: false,
  ends_at: '2026-11-16T12:25:00Z',
  items: [
    item('AUGMENTIN 1G', {
      state: 'SECURED',
      status_text: 'Reserved',
      qty_secured: 1,
      reservations: [{ id: RESERVATION.id, ref: 'R-7K3Q2F', pharmacy_name: 'Hamra Pharmacy', qty: 1 }],
    }),
    item('CONCOR 5MG', {
      state: 'WAITING',
      status_text: 'Not listed yet: still looking',
      waiting: { watching_new_stock: true, asked_pharmacies: 2, answers_by: null, open_offer_ids: [OFFER_ID] },
    }),
  ],
  units_wanted: 2,
  units_secured: 1,
  conversation_id: THREAD_ID,
  created_at: NOW,
  closed_at: null,
  server_now: NOW,
} satisfies Schemas['SourcingRequest']

const OFFER = {
  id: OFFER_ID,
  kind: 'early_release',
  product: { ...RESERVATION.product, name: 'CONCOR 5MG' },
  pharmacy: RESERVATION.pharmacy,
  qty: 1,
  price_each: { lbp: 600_000, usd_approx: 6.7 },
  total: { lbp: 600_000, usd_approx: 6.7 },
  saving: { lbp: 200_000, usd_approx: 2.2 },
  expiry_date: '2027-06-03',
  days_of_use: 1,
  expires_at: '2026-11-16T10:00:00Z',
  pickup_days_allowed: ['2026-11-16', '2026-11-17'],
  request_id: REQUEST_ID,
} satisfies Schemas['Offer']

const MESSAGES = `/api/v1/conversations/${THREAD_ID}/messages`
const none = { items: [], next_cursor: null, server_now: NOW }

function requestApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/districts': DISTRICTS,
    [`GET /api/v1/requests/${REQUEST_ID}`]: REQUEST,
    'GET /api/v1/requests': { items: [REQUEST], server_now: NOW },
    'GET /api/v1/offers': { items: [OFFER], server_now: NOW },
    'GET /api/v1/reservations': none,
    [`GET ${MESSAGES}`]: page([message(1, 'agent', 'I found Augmentin. Still looking for Concor.')], {
      conversation_id: THREAD_ID,
      kind: 'request',
      request_id: REQUEST_ID,
    }),
    ...more,
  })
}

describe("A request's page", () => {
  it('shows where each medicine stands, the offer and the thread', async () => {
    requestApi()

    const { container } = renderApp(<AppRoutes />, { path: `/requests/${REQUEST_ID}` })

    expect(await screen.findByRole('heading', { name: r.title('Q-4HX9TM') })).toBeInTheDocument()
    expect(screen.getByText(r.reserved(1, 2))).toBeInTheDocument()
    expect(screen.getByText(r.asked(2))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Ticket R-7K3Q2F/ })).toHaveAttribute(
      'href',
      `/reservations/${RESERVATION.id}`,
    )
    expect(await screen.findByText('I found Augmentin. Still looking for Concor.')).toBeInTheDocument()
    // It is a thread, not the chat: no new chat, no place to change (R-RQ4).
    expect(screen.queryByRole('button', { name: strings.chat.newChat })).not.toBeInTheDocument()
    expect(screen.getByText(strings.chat.aiNotice)).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('accepts an offer for the day the client chose, and opens the ticket', async () => {
    const api = requestApi({
      [`POST /api/v1/offers/${OFFER_ID}/accept`]: answer(201, RESERVATION),
      [`GET /api/v1/reservations/${RESERVATION.id}`]: RESERVATION,
    })
    renderApp(<AppRoutes />, { path: `/requests/${REQUEST_ID}` })
    const user = userEvent.setup()

    const offer = await screen.findByRole('article', { name: /CONCOR 5MG/ })
    expect(within(offer).getByText('Save 200,000')).toBeInTheDocument()
    await user.click(within(offer).getByRole('button', { name: strings.common.tomorrow }))
    await user.click(within(offer).getByRole('button', { name: strings.offers.accept }))

    expect(await screen.findByText('R-7K3Q2F')).toBeInTheDocument()
    const sent = api.sent('POST', '/api/v1/offers')[0]
    expect(sent.body).toEqual({ pickup_day: '2026-11-17' })
    expect(sent.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('declines an offer with one tap', async () => {
    const api = requestApi({ [`POST /api/v1/offers/${OFFER_ID}/decline`]: answer(204) })
    renderApp(<AppRoutes />, { path: `/requests/${REQUEST_ID}` })

    const offer = await screen.findByRole('article', { name: /CONCOR 5MG/ })
    await userEvent.click(within(offer).getByRole('button', { name: strings.offers.decline }))

    await waitFor(() => expect(api.sent('POST', '/api/v1/offers')).toHaveLength(1))
  })

  it('writes in the thread and waits for the worker to answer', async () => {
    const api = requestApi({ [`POST ${MESSAGES}`]: answer(202, { message_seq: 2 }) })
    renderApp(<AppRoutes />, { path: `/requests/${REQUEST_ID}` })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(strings.chat.messageLabel), 'any news?')
    await user.click(screen.getByRole('button', { name: strings.chat.send }))

    await waitFor(() => expect(api.sent('POST', MESSAGES)).toHaveLength(1))
    // No stream in a thread: the page keeps saying the agent is on it until it answers.
    expect(await screen.findByText(strings.chat.working)).toBeInTheDocument()
  })

  it('stops the search after asking', async () => {
    const api = requestApi({
      [`POST /api/v1/requests/${REQUEST_ID}/cancel`]: { ...REQUEST, state: 'CLOSED', outcome: 'CANCELLED' },
    })
    renderApp(<AppRoutes />, { path: `/requests/${REQUEST_ID}` })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: r.cancel }))
    expect(api.sent('POST', '/api/v1/requests')).toEqual([])
    await user.click(await screen.findByRole('button', { name: r.cancelConfirm }))

    expect((await screen.findAllByText(r.closed.CANCELLED)).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: r.cancel })).not.toBeInTheDocument()
  })

  it("says so when the request isn't the client's", async () => {
    requestApi({ [`GET /api/v1/requests/${REQUEST_ID}`]: refusal(404, 'NOT_FOUND') })

    renderApp(<AppRoutes />, { path: `/requests/${REQUEST_ID}` })

    expect(await screen.findByRole('alert')).toHaveTextContent(r.notFound)
  })
})

describe('Where a request starts and shows', () => {
  it('opens the request page after [Start sourcing] in the chat', async () => {
    const summary = { ...RESERVE_CARD, type: 'request_summary', action_label: 'Start sourcing', title: 'Find 2 medicines' }
    requestApi({
      'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
      [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([
        message(1, 'client', 'find me both'),
        message(2, 'agent', 'Shall I keep looking?', { cards: [summary] }),
      ]),
      [`POST /api/v1/proposals/${CARD_ID}/execute`]: {
        proposal_id: CARD_ID,
        kind: 'request_summary',
        reservations: [],
        request_id: REQUEST_ID,
        request_ref: 'Q-4HX9TM',
        message: 'Request Q-4HX9TM: DawaLink is on it.',
      },
    })
    renderApp(<AppRoutes />, { path: '/assistant' })

    await userEvent.click(await screen.findByRole('button', { name: 'Start sourcing' }))

    expect(await screen.findByRole('heading', { name: r.title('Q-4HX9TM') })).toBeInTheDocument()
  })

  it('puts an open request and a waiting offer on Home', async () => {
    requestApi()

    renderApp(<AppRoutes />, { path: '/' })

    expect(await screen.findByRole('link', { name: new RegExp(r.homeLine('Q-4HX9TM', 1, 2)) })).toHaveAttribute(
      'href',
      `/requests/${REQUEST_ID}`,
    )
    expect(await screen.findByRole('button', { name: strings.offers.accept })).toBeInTheDocument()
  })
})
