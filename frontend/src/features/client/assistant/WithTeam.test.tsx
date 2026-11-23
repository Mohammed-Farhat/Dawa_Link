import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { AppRoutes } from '../../../app/App'
import { strings } from '../../../strings/en'
import {
  accessibilityProblems,
  answer,
  CHAT_ID,
  CLIENT,
  CONFIG,
  DISTRICTS,
  loggedIn,
  message,
  page,
  pretendApi,
  renderApp,
} from '../../../test/render'
import { Conversation } from './AssistantPage'

// The owner, 2026-11-22: once DawaLink's team has replied to the client's case, the chat
// is between the client and the team until the team closes the case.

const s = strings.chat
const MESSAGES = `/api/v1/conversations/${CHAT_ID}/messages`

const ASKED = message(1, 'client', 'I want to talk to a person')
const AGENT = message(2, 'agent', 'I passed this to the DawaLink team.', { quick_replies: ['Thanks'] })
const TEAM = message(3, 'admin', 'Hello, we are looking at it.')

function chatApi(state: { now: ReturnType<typeof message>[]; withTeam: boolean }, more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
    [`GET ${MESSAGES}`]: () => page(state.now, { with_team: state.withTeam }),
    ...more,
  })
}

describe('A chat DawaLink’s team has', () => {
  it('says the client writes to the team, keeps the box and the AI notice, and offers no quick replies', async () => {
    chatApi({ now: [ASKED, AGENT, TEAM], withTeam: true })

    const { container } = renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText(s.withTeam)).toBeInTheDocument()
    expect(screen.getByText(s.aiNotice)).toBeInTheDocument()
    expect(screen.getByLabelText(s.messageLabel)).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Thanks' })).not.toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('sends a message to the team and never says the assistant is working', async () => {
    const state = { now: [ASKED, AGENT, TEAM], withTeam: true }
    const api = chatApi(state, {
      [`POST ${MESSAGES}`]: () => {
        state.now = [...state.now, message(4, 'client', 'Thank you')]
        return answer(202, { message_seq: 4, with_team: true })
      },
    })
    renderApp(<AppRoutes />, { path: '/assistant' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'Thank you')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByText('Thank you')).toBeInTheDocument()
    expect(api.sent('POST', MESSAGES)).toHaveLength(1)
    expect(screen.queryByText(s.working)).not.toBeInTheDocument()
    expect(screen.queryByText(s.oneMoment)).not.toBeInTheDocument()
    expect(screen.getByLabelText(s.messageLabel)).toHaveValue('')
  })

  it('shows the closed case as a line of DawaLink, and the quick replies come back', async () => {
    const closed = message(4, 'system', null, {
      cards: [
        {
          card_id: '4:0',
          origin: 'system',
          type: 'team_closed',
          title: '',
          lines: [],
          prescription_notice: false,
          recommended: false,
          state: 'open',
          expires_at: null,
          action_label: null,
          selectable_items: [],
          call_number: null,
          data: {},
        },
      ],
    })
    chatApi({ now: [ASKED, AGENT, TEAM, closed, message(5, 'agent', 'Back again.', { quick_replies: ['Thanks'] })], withTeam: false })

    renderApp(<AppRoutes />, { path: '/assistant' })

    expect(await screen.findByText(s.system.team_closed)).toBeInTheDocument()
    expect(screen.queryByText(s.withTeam)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thanks' })).toBeInTheDocument()
  })
})

describe('A request’s thread the team has', () => {
  it('waits for no reply of the assistant after a message to the team', async () => {
    // The page's reading of the thread lags behind (it says nothing of the team): only
    // the answer to the message says that it went to the team.
    const state = { now: [message(1, 'agent', 'Planning your request.')], withTeam: false }
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      'GET /api/v1/config/public': CONFIG,
      [`GET ${MESSAGES}`]: () => page(state.now, { with_team: state.withTeam, kind: 'request' }),
      [`POST ${MESSAGES}`]: () => {
        state.now = [...state.now, message(2, 'admin', 'Hello from the team.'), message(3, 'client', 'Thanks!')]
        return answer(202, { message_seq: 3, with_team: true })
      },
    })
    loggedIn()
    renderApp(
      <Conversation
        conversationId={CHAT_ID}
        thread={{ title: 'Request Q-6BN2RA', subtitle: '', backTo: '/requests', above: null, canWrite: true }}
      />,
    )
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(s.messageLabel), 'Thanks!')
    await user.click(screen.getByRole('button', { name: s.send }))

    expect(await screen.findByText('Thanks!')).toBeInTheDocument()
    // Waiting for an assistant's answer would say "Working on it…" until one came.
    await waitFor(() => expect(screen.getByLabelText(s.messageLabel)).toHaveValue(''))
    expect(screen.queryByText(s.working)).not.toBeInTheDocument()
  })
})
