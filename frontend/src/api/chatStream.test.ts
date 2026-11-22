import { describe, expect, it, vi } from 'vitest'

import { CHAT_ID, loggedIn, pretendApi, refusal } from '../test/render'
import { sendMessage } from './chatStream'
import { getToken, LOGGED_OUT_EVENT, setToken } from './client'

// The chat's stream is read with fetch, not through the API client: it must end a session
// exactly as the client's own check does (api/client.ts, A#11).

const MESSAGES = `POST /api/v1/conversations/${CHAT_ID}/messages`

function listen() {
  const ended = vi.fn()
  window.addEventListener(LOGGED_OUT_EVENT, ended)
  return { ended, stop: () => window.removeEventListener(LOGGED_OUT_EVENT, ended) }
}

describe("A session that ended while the chat's message was sent", () => {
  it('logs out, once, and tells the page', async () => {
    loggedIn()
    pretendApi({ [MESSAGES]: refusal(401, 'UNAUTHENTICATED') })
    const { ended, stop } = listen()

    await expect(sendMessage(CHAT_ID, 'I need Augmentin', 'an-id', () => {})).rejects.toMatchObject({
      code: 'UNAUTHENTICATED',
    })

    expect(getToken()).toBeNull()
    expect(ended).toHaveBeenCalledTimes(1)
    stop()
  })

  it("keeps a new login's token: the refusal was for the one before it", async () => {
    loggedIn()
    pretendApi({
      [MESSAGES]: () => {
        // Another tab logged someone in while this message was on its way.
        setToken('the-next-token')
        return refusal(401, 'UNAUTHENTICATED')
      },
    })
    const { ended, stop } = listen()

    await expect(sendMessage(CHAT_ID, 'I need Augmentin', 'an-id', () => {})).rejects.toBeTruthy()

    expect(getToken()).toBe('the-next-token')
    expect(ended).not.toHaveBeenCalled()
    stop()
  })

  it('stays logged in for a refusal that is not "your session ended"', async () => {
    loggedIn()
    pretendApi({ [MESSAGES]: refusal(403, 'FORBIDDEN') })
    const { ended, stop } = listen()

    await expect(sendMessage(CHAT_ID, 'I need Augmentin', 'an-id', () => {})).rejects.toMatchObject({
      code: 'FORBIDDEN',
    })

    expect(getToken()).toBe('a-test-token')
    expect(ended).not.toHaveBeenCalled()
    stop()
  })
})
