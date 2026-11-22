import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { sendMessage } from '../../../api/chatStream'
import { getToken } from '../../../api/client'
import { AppRoutes } from '../../../app/App'
import { errorMessage, strings } from '../../../strings/en'
import {
  accessibilityProblems,
  answer,
  brokenStream,
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
    // A reason is needed; the words are not. The page says so, under its question.
    expect(send).toBeDisabled()
    expect(screen.getByRole('group', { name: r.title })).toBeInTheDocument()
    expect(screen.getByText(r.chooseReason)).toBeInTheDocument()
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
      // The reservation is waiting: its card gets the big [Show at the counter].
      'GET /api/v1/reservations': { items: [RESERVATION], next_cursor: null, server_now: CONFIG.server_now },
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
    expect(await screen.findByRole('link', { name: strings.home.showAtCounter })).toHaveAttribute(
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
    const api = chatApi(
      { now: [] },
      { [`POST ${MESSAGES}`]: refusal(503, 'ASSISTANT_UNAVAILABLE', { fallback: 'search' }) },
    )
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'I need Augmentin')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByText(strings.banner.degraded)).toBeInTheDocument()
    expect(screen.getByLabelText(s.messageLabel)).toHaveValue('I need Augmentin')

    // Sent again unchanged, it is the same message: the API keeps it once (A#12).
    await user.click(screen.getByRole('button', { name: s.send }))
    await waitFor(() => expect(api.sent('POST', MESSAGES)).toHaveLength(2))
    const [first, second] = api.sent('POST', MESSAGES).map((call) => call.body as { client_message_id: string })
    expect(second.client_message_id).toBe(first.client_message_id)
  })

  it('keeps a message the API stored out of the box when the assistant fails after it (A#12)', async () => {
    const messages = { now: [] as ReturnType<typeof message>[] }
    chatApi(messages, {
      [`POST ${MESSAGES}`]: () => {
        // The API stores the message, then the turn fails inside the stream.
        messages.now = [QUESTION]
        return stream(
          ['turn_started', { client_message_seq: 1 }],
          ['error', { error: { code: 'ASSISTANT_UNAVAILABLE', details: { fallback: 'search' } }, status: 503 }],
        )
      },
    })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'I need Augmentin')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByText(strings.banner.degraded)).toBeInTheDocument()
    // The message is in the thread once, and not in the box: a resend would store it twice.
    expect(screen.getByLabelText(s.messageLabel)).toHaveValue('')
    expect(screen.getAllByText('I need Augmentin')).toHaveLength(1)
  })

  it('says the reply will come when the stream drops after the message was kept (A#12)', async () => {
    const messages = { now: [] as ReturnType<typeof message>[] }
    chatApi(messages, {
      'GET /api/v1/config/public': { ...CONFIG, poll_every_s: 1 },
      [`POST ${MESSAGES}`]: () => {
        messages.now = [QUESTION]
        return brokenStream(['turn_started', { client_message_seq: 1 }], ['progress', { label: 'Searching…' }])
      },
    })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'I need Augmentin')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByText(s.replyComing)).toBeInTheDocument()
    // Nothing failed for the client: no red error, and nothing back in the box.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByLabelText(s.messageLabel)).toHaveValue('')
    expect(screen.getByText(s.working)).toBeInTheDocument()

    // The turn went on: its reply arrives by polling, and the waiting line goes.
    messages.now = [QUESTION, message(2, 'agent', 'Which strength?')]
    expect(await screen.findByText('Which strength?', {}, { timeout: 4000 })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText(s.replyComing)).not.toBeInTheDocument())
  })

  it("says the day's limit of messages, not \"wait a minute\" (A#34, B#36)", async () => {
    chatApi({ now: [] }, { [`POST ${MESSAGES}`]: refusal(429, 'RATE_LIMITED', { retry_after_s: 3600 }) })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'I need Augmentin')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByRole('alert')).toHaveTextContent(strings.limits.chatToday)
    expect(screen.getByLabelText(s.messageLabel)).toHaveValue('I need Augmentin')
  })

  it('keeps a red notice until it is closed, with a way to close it (B#35)', async () => {
    chatApi(
      { now: [QUESTION, REPLY] },
      { [`POST /api/v1/proposals/${CARD_ID}/execute`]: refusal(409, 'PRICE_CHANGED') },
    )
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Reserve' }))
    const notice = await screen.findByRole('alert')
    expect(notice).toHaveTextContent(errorMessage('PRICE_CHANGED'))

    await user.click(within(notice).getByRole('button', { name: strings.common.close }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says when requests open again, by the server clock, for [Start sourcing] at night (B#37)', async () => {
    chatApi(
      // 06:00 in Beirut: requests open the same morning, not "tomorrow".
      { now: [QUESTION, REPLY] },
      {
        [`GET ${MESSAGES}`]: () => page([QUESTION, REPLY], { server_now: '2026-11-16T04:00:00Z' }),
        [`POST /api/v1/proposals/${CARD_ID}/execute`]: refusal(409, 'OUTSIDE_REQUEST_HOURS', {
          opens_at: '2026-11-16T06:00:00Z',
        }),
      },
    )
    renderApp(<AppRoutes />, { path: '/assistant' })

    await userEvent.click(await screen.findByRole('button', { name: 'Reserve' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      strings.limits.comeBack(strings.limits.comeBackAt('08:00')),
    )
  })

  it('says who speaks in each bubble, and reads Arabic with an Arabic voice (B#9, B#10)', async () => {
    chatApi({
      now: [
        message(1, 'client', 'بدّي أوغمنتين'),
        message(2, 'agent', 'Here it is.'),
        message(3, 'admin', 'For an emergency, call 140.'),
      ],
    })
    const { container } = renderApp(<AppRoutes />, { path: '/assistant' })

    const arabic = await screen.findByText('بدّي أوغمنتين')
    expect(arabic).toHaveAttribute('lang', 'ar')
    const bubble = arabic.closest('p')
    expect(bubble).toHaveAttribute('dir', 'auto')
    // The English label keeps its own direction, so it can't turn the bubble left to right.
    expect(within(bubble as HTMLElement).getByText(s.speaker.client)).toHaveAttribute('dir', 'ltr')
    expect(screen.getByText('Here it is.')).not.toHaveAttribute('lang')
    expect(screen.getByText('Here it is.').closest('p')).toHaveTextContent(`${s.speaker.agent} Here it is.`)
    expect(screen.getByText('For an emergency, call 140.').closest('p')).toHaveTextContent(s.speaker.admin)
    // The visible "DawaLink team" is not said twice.
    expect(screen.getByText(s.team)).toHaveAttribute('aria-hidden', 'true')
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('reads out only the list of messages, and the history is in it from the start (B#11)', async () => {
    chatApi({ now: [QUESTION, REPLY] })
    renderApp(<AppRoutes />, { path: '/assistant' })

    const log = await screen.findByRole('log')
    expect(within(log).getByText('I need Augmentin')).toBeInTheDocument()
    expect(within(log).getByText('Here it is.')).toBeInTheDocument()
    // The quick replies and the box to write in are outside it.
    expect(within(log).queryByRole('button', { name: 'Thanks' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thanks' })).toBeInTheDocument()
    expect(screen.getByRole('main').querySelector('[aria-live="polite"].chat__messages')).toBeNull()
  })

  it("keeps the client's message out of the list while it is sent, so it is announced once (B#11)", async () => {
    chatApi({ now: [QUESTION, REPLY] }, { [`POST ${MESSAGES}`]: () => new Promise(() => {}) })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'And Panadol')
    await user.click(screen.getByRole('button', { name: s.send }))

    const sending = await screen.findByText('And Panadol')
    expect(within(screen.getByRole('log')).queryByText('And Panadol')).not.toBeInTheDocument()
    expect(sending.closest('p')).toHaveTextContent(`${s.speaker.client} And Panadol`)
  })

  it('stops offering the counter when a card says the reservation ended (A#36)', async () => {
    const reserved = {
      ...RESERVE_CARD,
      card_id: '3:0',
      origin: 'system',
      type: 'reserved',
      title: '',
      lines: [],
      recommended: false,
      action_label: null,
      data: { order_id: RESERVATION.id, order_ref: RESERVATION.ref },
    }
    const messages = { now: [QUESTION, message(2, 'system', null, { cards: [reserved] })] }
    const waiting = { items: [RESERVATION] }
    chatApi(messages, {
      'GET /api/v1/config/public': { ...CONFIG, poll_every_s: 1 },
      'GET /api/v1/reservations': () => ({ ...waiting, next_cursor: null, server_now: CONFIG.server_now }),
    })
    renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByRole('link', { name: strings.home.showAtCounter })).toBeInTheDocument()

    // The pharmacy marked it picked up: its card arrives by polling.
    waiting.items = []
    messages.now = [
      ...messages.now,
      message(3, 'system', null, { cards: [{ ...reserved, card_id: '4:0', type: 'picked_up' }] }),
    ]
    expect(await screen.findByText(s.system.picked_up(RESERVATION.ref), {}, { timeout: 4000 })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: s.system.seeReservation })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: strings.home.showAtCounter })).not.toBeInTheDocument()
  })

  it('marks the quick replies as words to send, apart from the cards (B#8)', async () => {
    chatApi({ now: [QUESTION, REPLY] })
    renderApp(<AppRoutes />, { path: '/assistant' })

    const replies = await screen.findByRole('group', { name: s.quickRepliesIntro })
    const chip = within(replies).getByRole('button', { name: 'Thanks' })
    expect(chip).toHaveClass('chip--reply')
    expect(chip).not.toHaveClass('pill-button')
    expect(screen.getByText(s.quickRepliesIntro)).toBeVisible()
  })

  it('links a reservation that is no longer waiting in plain words (A#36)', async () => {
    const reserved = {
      ...RESERVE_CARD,
      card_id: '3:0',
      origin: 'system',
      type: 'reserved',
      title: '',
      lines: [],
      recommended: false,
      action_label: null,
      data: { order_id: RESERVATION.id, order_ref: RESERVATION.ref },
    }
    chatApi(
      { now: [QUESTION, message(2, 'system', null, { cards: [reserved] })] },
      // It was cancelled since: it is not among the reservations waiting.
      { 'GET /api/v1/reservations': { items: [], next_cursor: null, server_now: CONFIG.server_now } },
    )
    renderApp(<AppRoutes />, { path: '/assistant' })

    const link = await screen.findByRole('link', { name: s.system.seeReservation })
    expect(link).toHaveAttribute('href', `/reservations/${RESERVATION.id}`)
    expect(screen.queryByRole('link', { name: strings.home.showAtCounter })).not.toBeInTheDocument()
  })

  it('leads a box held for the client to its offer while it waits (B#15)', async () => {
    const held = {
      ...RESERVE_CARD,
      card_id: '3:0',
      origin: 'system',
      type: 'offer',
      title: '',
      lines: [],
      recommended: false,
      action_label: null,
      data: { order_id: RESERVATION.id, product: 'CONCOR 5MG', offer_expires_at: '2026-11-16T10:00:00Z' },
    }
    const api = chatApi(
      { now: [QUESTION, message(2, 'system', null, { cards: [held] })] },
      { 'GET /api/v1/offers': { items: [{ id: RESERVATION.id }], server_now: CONFIG.server_now } },
    )
    renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByRole('link', { name: s.system.seeOffer })).toHaveAttribute('href', '/')
    expect(screen.getByText(s.system.offerHeld('CONCOR 5MG', '12:00'))).toBeInTheDocument()
    expect(api.sent('GET', '/api/v1/offers').length).toBeGreaterThan(0)
  })

  it('says so when a new chat could not be started', async () => {
    chatApi({ now: [QUESTION, REPLY] }, { 'POST /api/v1/conversations/new-chat': refusal(503, 'SERVICE_UNAVAILABLE') })
    renderApp(<AppRoutes />, { path: '/assistant' })

    await userEvent.click(await screen.findByRole('button', { name: s.newChat }))

    expect(await screen.findByRole('alert')).toHaveTextContent(s.newChatFailed)
    expect(screen.getByText('Here it is.')).toBeInTheDocument()
  })

  it('logs out when the API says the session ended, on the chat stream too', async () => {
    chatApi({ now: [] }, { [`POST ${MESSAGES}`]: refusal(401, 'UNAUTHENTICATED') })

    await expect(sendMessage(CHAT_ID, 'I need Augmentin', 'an-id', () => {})).rejects.toMatchObject({
      code: 'UNAUTHENTICATED',
    })
    expect(getToken()).toBeNull()
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

  it('keeps trying for about 30 seconds, as long as every turn of the server may be taken', async () => {
    const messages = { now: [] as ReturnType<typeof message>[] }
    let tries = 0
    const api = chatApi(messages, {
      [`POST ${MESSAGES}`]: () => {
        tries += 1
        // Busy 14 times: at the API's 2 s, 28 seconds.
        if (tries < 15) return refusal(409, 'CONVERSATION_BUSY', { retry_after_ms: 1 })
        messages.now = [QUESTION, message(2, 'agent', 'Which strength?')]
        return stream(['turn_completed', { agent_message_seq: 2, outcome: 'ok' }])
      },
    })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'I need Augmentin')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByText('Which strength?')).toBeInTheDocument()
    expect(api.sent('POST', MESSAGES)).toHaveLength(15)
  })

  it('stops after its last try, and gives the message back to send again', async () => {
    const api = chatApi({ now: [] }, { [`POST ${MESSAGES}`]: refusal(409, 'CONVERSATION_BUSY', { retry_after_ms: 1 }) })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'I need Augmentin')
    await user.click(screen.getByRole('button', { name: s.send }))

    await waitFor(() => expect(screen.getByLabelText(s.messageLabel)).toHaveValue('I need Augmentin'))
    expect(api.sent('POST', MESSAGES)).toHaveLength(15)
    // Not "One moment…", which would promise an answer that isn't coming.
    expect(await screen.findByText(strings.limits.busy)).toBeInTheDocument()
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

  it('names the empty choice of districts, and says the wait of the hourly limit in minutes', async () => {
    chatApi(
      { now: [] },
      { [`PUT /api/v1/conversations/${CHAT_ID}/location`]: refusal(429, 'RATE_LIMITED', { retry_after_s: 3601 }) },
    )
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition: (done: (position: unknown) => void) => done({ coords: { latitude: 33.9, longitude: 35.5 } }) },
    })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: s.location.button(s.location.home('Beirut')) }))
    expect(await screen.findByRole('option', { name: s.location.chooseDistrict })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: s.location.useMine }))

    // Ten places an hour (N-47): never "tomorrow", never "a minute" for most of an hour.
    expect(await screen.findByRole('alert')).toHaveTextContent(strings.limits.tryInMinutes(60))
  })

  it('says only that an option expired in an earlier chat, where nothing can be asked (B#32)', async () => {
    const OLD_CHAT = 'cccccccc-1111-4111-8111-cccccccccccc'
    chatApi(
      { now: [QUESTION, REPLY] },
      {
        [`GET /api/v1/conversations/${OLD_CHAT}/messages`]: {
          ...page([QUESTION, { ...REPLY, cards: [{ ...RESERVE_CARD, state: 'expired' }] }]),
          conversation_id: OLD_CHAT,
          archived: true,
        },
        'GET /api/v1/conversations/chats': {
          items: [
            { conversation_id: CHAT_ID, active: true, started_at: CONFIG.server_now, last_activity_at: CONFIG.server_now, title: null },
            {
              conversation_id: OLD_CHAT,
              active: false,
              started_at: '2026-11-14T08:00:00Z',
              last_activity_at: '2026-11-14T08:05:00Z',
              title: 'بدّي أوغمنتين',
            },
          ],
          server_now: CONFIG.server_now,
        },
      },
    )
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: s.history }))
    const title = await screen.findByText('بدّي أوغمنتين')
    expect(title).toHaveAttribute('lang', 'ar')
    await user.click(title)

    expect(await screen.findByText(s.expiredEarlier)).toBeInTheDocument()
    expect(screen.queryByText(s.expired)).not.toBeInTheDocument()
    // An earlier chat is only read: nothing in it is read out as news.
    expect(screen.queryByRole('log')).not.toBeInTheDocument()
  })
})
