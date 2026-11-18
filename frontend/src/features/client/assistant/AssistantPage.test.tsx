import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { AppRoutes } from '../../../app/App'
import { errorMessage, strings } from '../../../strings/en'
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
  stream,
} from '../../../test/render'

const s = strings.chat
const MESSAGES = `/api/v1/conversations/${CHAT_ID}/messages`

/** The routes every chat test needs. `messages` is read again on each poll. */
function chatApi(messages: { now: ReturnType<typeof message>[] }, more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
    [`GET ${MESSAGES}`]: () => page(messages.now),
    ...more,
  })
}

const QUESTION = message(1, 'client', 'I need Augmentin')
const REPLY = message(2, 'agent', 'Here it is.', { cards: [RESERVE_CARD], quick_replies: ['Thanks'] })

describe('The assistant', () => {
  it('always says it is an AI, and has no accessibility problems', async () => {
    chatApi({ now: [] })

    const { container } = renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText(s.aiNotice)).toBeInTheDocument()
    expect(await screen.findByText(s.empty)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: s.location.button(s.location.home('Beirut')) })).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('sends a message and shows the whole reply with its card', async () => {
    const messages = { now: [] as ReturnType<typeof message>[] }
    const api = chatApi(messages, {
      [`POST ${MESSAGES}`]: () => {
        messages.now = [QUESTION, REPLY]
        return stream(
          ['turn_started', { client_message_seq: 1 }],
          ['progress', { label: 'Searching…' }],
          ['message', REPLY],
          ['turn_completed', { agent_message_seq: 2, outcome: 'ok' }],
        )
      },
    })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'I need Augmentin')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByText('Here it is.')).toBeInTheDocument()
    const card = screen.getByRole('article', { name: RESERVE_CARD.title })
    expect(within(card).getByText(s.recommended)).toBeInTheDocument()
    expect(within(card).getByText(s.prescription)).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Reserve' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Thanks' })).toBeInTheDocument()
    const sent = api.sent('POST', MESSAGES)[0]
    expect(sent.body).toMatchObject({ text: 'I need Augmentin' })
    expect(sent.headers.get('Authorization')).toBe('Bearer a-test-token')
    expect(screen.getByLabelText(s.messageLabel)).toHaveValue('')
  })

  it("shows the agent's text as plain text, never as a page", async () => {
    const evil = '<img src=x onerror="alert(1)"> see https://evil.example'
    chatApi({ now: [QUESTION, message(2, 'agent', evil)] })

    const { container } = renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText(evil)).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('.chat__messages a')).toBeNull()
  })

  it('shows as plain text whatever a client, the team or a card holds (FS-8)', async () => {
    // The login token is kept where a script could read it (docs/10 RR-13), so nothing
    // anyone typed may ever become part of the page.
    const evil = '<script>alert(1)</script><img src=x onerror="alert(2)"><a href="javascript:alert(3)">x</a>'
    const card = {
      ...RESERVE_CARD,
      title: `Title ${evil}`,
      lines: [{ label: `Label ${evil}`, value: `Value ${evil}` }],
    }
    chatApi({
      now: [
        message(1, 'client', `Mine ${evil}`),
        message(2, 'admin', `Team ${evil}`),
        message(3, 'agent', 'Here it is.', { cards: [card], quick_replies: [`Chip ${evil}`] }),
      ],
    })

    const { container } = renderApp(<AppRoutes />, { path: '/assistant' })

    for (const said of ['Mine', 'Team', 'Title', 'Label', 'Value']) {
      expect(await screen.findByText(`${said} ${evil}`)).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: `Chip ${evil}` })).toBeInTheDocument()
    expect(container.querySelector('script, img, iframe, object, embed')).toBeNull()
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
    expect(container.querySelector('.chat__messages a')).toBeNull()
    expect(container.querySelector('[onerror], [onclick], [onload]')).toBeNull()
  })

  it('reports an answer once, with a reason and a few words', async () => {
    const api = chatApi(
      { now: [QUESTION, REPLY] },
      { [`POST ${MESSAGES}/2/report`]: answer(201, { id: 'report-1' }) },
    )
    const { container } = renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()
    const r = s.report

    // Under the assistant's reply, not under the client's own message.
    expect(await screen.findAllByRole('button', { name: r.open })).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: r.open }))
    expect(await accessibilityProblems(container)).toEqual([])
    const send = screen.getByRole('button', { name: r.send })
    // A reason is needed; the words are not.
    expect(send).toBeDisabled()
    await user.click(screen.getByRole('button', { name: r.reasons.wrong_information }))
    await user.type(screen.getByLabelText(r.comment), 'The price was wrong')
    await user.click(send)

    expect(await screen.findByText(r.thanks)).toBeInTheDocument()
    expect(api.sent('POST', `${MESSAGES}/2/report`)[0].body).toEqual({
      reason: 'wrong_information',
      comment: 'The price was wrong',
    })
    expect(screen.queryByRole('button', { name: r.open })).not.toBeInTheDocument()
  })

  it('shows an answer that was already reported as reported', async () => {
    chatApi({ now: [QUESTION, message(2, 'agent', 'Here it is.', { reported: true })] })
    renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText(s.report.thanks)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: s.report.open })).not.toBeInTheDocument()
  })

  it("signs a person's reply as DawaLink's team, with nothing to report on it", async () => {
    chatApi({ now: [QUESTION, message(2, 'admin', 'For an emergency, call 140.')] })
    renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText('For an emergency, call 140.')).toBeInTheDocument()
    expect(screen.getByText(s.team)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: s.report.open })).not.toBeInTheDocument()
  })

  it('reserves with a tap, sending only the card and a key of its own', async () => {
    const messages = { now: [QUESTION, REPLY] }
    const api = chatApi(messages, {
      [`POST /api/v1/proposals/${CARD_ID}/execute`]: () => {
        messages.now = [
          QUESTION,
          { ...REPLY, cards: [{ ...RESERVE_CARD, state: 'used' }] },
          message(3, 'system', null, {
            cards: [
              {
                ...RESERVE_CARD,
                card_id: '3:0',
                origin: 'system',
                type: 'reserved',
                title: '',
                lines: [],
                recommended: false,
                action_label: null,
                data: { order_id: RESERVATION.id, order_ref: RESERVATION.ref },
              },
            ],
          }),
        ]
        return {
          proposal_id: CARD_ID,
          kind: 'reserve',
          reservations: [RESERVATION],
          request_id: null,
          request_ref: null,
          message: 'Reserved: R-7K3Q2F. Show this number at the counter.',
        }
      },
    })
    renderApp(<AppRoutes />, { path: '/assistant' })

    await userEvent.click(await screen.findByRole('button', { name: 'Reserve' }))

    expect(await screen.findByText(s.system.reserved('R-7K3Q2F'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: strings.home.showAtCounter })).toHaveAttribute(
      'href',
      `/reservations/${RESERVATION.id}`,
    )
    // The used card stays, and says so; its button is gone.
    expect(screen.getByText(s.reserved)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reserve' })).not.toBeInTheDocument()
    const tap = api.sent('POST', '/api/v1/proposals')[0]
    expect(tap.body).toEqual({ selected_item_keys: null })
    expect(tap.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('says in plain words why a tap failed, and keeps the card', async () => {
    chatApi(
      { now: [QUESTION, REPLY] },
      { [`POST /api/v1/proposals/${CARD_ID}/execute`]: refusal(409, 'NOT_ENOUGH_STOCK', { available: 0 }) },
    )
    renderApp(<AppRoutes />, { path: '/assistant' })

    await userEvent.click(await screen.findByRole('button', { name: 'Reserve' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(errorMessage('NOT_ENOUGH_STOCK'))
    expect(screen.getByRole('button', { name: 'Reserve' })).toBeInTheDocument()
  })

  it('folds the other options under the recommended one', async () => {
    const other = { ...RESERVE_CARD, card_id: 'other-card', recommended: false, title: 'AUGMENTIN 1G at Matn Pharmacy' }
    chatApi({ now: [QUESTION, { ...REPLY, cards: [RESERVE_CARD, other] }] })
    renderApp(<AppRoutes />, { path: '/assistant' })

    const more = await screen.findByRole('button', { name: s.otherOptions(1) })
    expect(screen.queryByRole('article', { name: other.title })).not.toBeInTheDocument()
    await userEvent.click(more)

    expect(screen.getByRole('article', { name: other.title })).toBeInTheDocument()
  })

  it('shows another brand with a phone number and no way to reserve it', async () => {
    const brand = {
      ...RESERVE_CARD,
      type: 'other_brand',
      title: 'CLAVOX 1G at Hamra Pharmacy',
      recommended: false,
      action_label: null,
      call_number: '+961 1 000 000',
    }
    chatApi({ now: [QUESTION, { ...REPLY, cards: [brand] }] })
    renderApp(<AppRoutes />, { path: '/assistant' })

    const card = await screen.findByRole('article', { name: brand.title })

    expect(within(card).getByText(s.askPharmacistFirst)).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: s.call })).toHaveAttribute('href', 'tel:+961 1 000 000')
    expect(within(card).queryByRole('button')).not.toBeInTheDocument()
  })

  it('puts the message back and says so when the assistant is switched off', async () => {
    chatApi(
      { now: [] },
      { [`POST ${MESSAGES}`]: refusal(503, 'ASSISTANT_UNAVAILABLE', { fallback: 'search' }) },
    )
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'I need Augmentin')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByText(strings.banner.degraded)).toBeInTheDocument()
    expect(screen.getByLabelText(s.messageLabel)).toHaveValue('I need Augmentin')
  })

  it('waits and sends again by itself while the agent is busy', async () => {
    const messages = { now: [] as ReturnType<typeof message>[] }
    let tries = 0
    const api = chatApi(messages, {
      [`POST ${MESSAGES}`]: () => {
        tries += 1
        if (tries === 1) return refusal(409, 'CONVERSATION_BUSY', { retry_after_ms: 10 })
        messages.now = [QUESTION, message(2, 'agent', 'Which strength?')]
        return stream(['turn_completed', { agent_message_seq: 2, outcome: 'ok' }])
      },
    })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'I need Augmentin')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByText('Which strength?')).toBeInTheDocument()
    const [first, second] = api.sent('POST', MESSAGES)
    // The same ID both times: the server stores the message once.
    expect((second.body as { client_message_id: string }).client_message_id).toBe(
      (first.body as { client_message_id: string }).client_message_id,
    )
  })

  it('sets a district as the place travel times are counted from', async () => {
    const api = chatApi(
      { now: [] },
      { [`PUT /api/v1/conversations/${CHAT_ID}/location`]: answer(204) },
    )
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: s.location.button(s.location.home('Beirut')) }))
    expect(await screen.findByText(s.location.why)).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(s.location.orDistrict), 'Matn')
    await user.click(screen.getByRole('button', { name: s.location.useDistrict }))

    await waitFor(() => expect(api.sent('PUT', '/api/v1/conversations')).toHaveLength(1))
    expect(api.sent('PUT', '/api/v1/conversations')[0].body).toEqual({ district_id: 2 })
  })
})
