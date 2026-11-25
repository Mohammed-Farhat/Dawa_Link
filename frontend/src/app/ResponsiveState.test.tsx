import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { strings } from '../strings/en'
import { CHAT_ID, CLIENT, CONFIG, DISTRICTS, loggedIn, page, pretendApi, renderApp } from '../test/render'
import { AppRoutes } from './App'

// Change the media-query subscription without re-rendering the app root.
function viewport() {
  let wide = false
  const listeners = new Set<(event: MediaQueryListEvent) => void>()
  vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
    matches: query === '(min-width: 992px)' && wide,
    media: query,
    addEventListener: (_event: string, callback: (event: MediaQueryListEvent) => void) => { listeners.add(callback) },
    removeEventListener: (_event: string, callback: (event: MediaQueryListEvent) => void) => { listeners.delete(callback) },
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(), onchange: null,
  }) as MediaQueryList)
  return (next: boolean) => act(() => { wide = next; listeners.forEach((listener) => listener({ matches: wide } as MediaQueryListEvent)) })
}
function client() {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': CLIENT,
    'GET /api/v1/districts': DISTRICTS,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/notifications/unread-count': { count: 0 },
    'GET /api/v1/conversations/active-chat': { conversation_id: CHAT_ID, kind: 'chat' },
    [`GET /api/v1/conversations/${CHAT_ID}/messages`]: page([]),
    'GET /api/v1/conversations/chats': { items: [] },
  })
}
afterEach(() => vi.restoreAllMocks())

describe('Responsive drafts (F-02)', () => {
  it('preserves profile and deletion form drafts, focus and a single main', async () => {
    const resize = viewport()
    const api = client()
    renderApp(<AppRoutes />, { path: '/me' })
    const user = userEvent.setup()
    const name = await screen.findByLabelText(strings.signUp.firstName)
    await user.clear(name)
    await user.type(name, 'Unsaved Synthetic Name')
    await user.click(screen.getByRole('button', { name: strings.me.deleteOpen }))
    const password = screen.getByLabelText(new RegExp(strings.me.deletePassword))
    await user.type(password, 'unsaved-password')
    for (const wide of [true, false, true, false]) {
      resize(wide)
      expect(screen.getByLabelText(strings.signUp.firstName)).toBe(name)
      expect(name).toHaveValue('Unsaved Synthetic Name')
      expect(password).toHaveValue('unsaved-password')
      expect(password).toHaveFocus()
      expect(screen.getAllByRole('main')).toHaveLength(1)
    }
    expect(api.calls.filter((call) => call.method !== 'GET')).toHaveLength(0)
  })

  it('preserves the assistant draft while changing its frame', async () => {
    const resize = viewport()
    const api = client()
    renderApp(<AppRoutes />, { path: '/assistant' })
    const draft = await screen.findByLabelText(strings.chat.messageLabel)
    await userEvent.type(draft, 'Keep this unsent draft')
    for (const wide of [true, false]) {
      resize(wide)
      expect(screen.getByLabelText(strings.chat.messageLabel)).toBe(draft)
      expect(draft).toHaveValue('Keep this unsent draft')
      expect(draft).toHaveFocus()
      expect(screen.getAllByRole('main')).toHaveLength(1)
    }
    expect(api.calls.filter((call) => call.method !== 'GET')).toHaveLength(0)
  })
})
