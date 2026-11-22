import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CLIENT, pretendApi, refusal, renderApp } from '../test/render'
import { getToken, setToken } from './client'
import { useSession } from './session'

// "Who is logged in?" is asked with the token kept in this browser. An answer that comes
// back after that token was replaced (a login logged someone in, another tab logged in)
// is about the person before, and is never what the page shows.

function Who() {
  const { me } = useSession()
  return <output aria-label="who">{me === undefined ? 'asking' : me === null ? 'nobody' : me.role}</output>
}

describe('A late answer about the token before', () => {
  it('never shows the person who just logged in as logged out', async () => {
    setToken('the-one-before')
    const asked: (string | null)[] = []
    pretendApi({
      'GET /api/v1/auth/me': (call: { headers: Headers }) => {
        asked.push(call.headers.get('Authorization'))
        if (asked.length > 1) return CLIENT
        // While the first question was on its way, a login in another tab logged someone in.
        setToken('the-new-one')
        return refusal(401, 'UNAUTHENTICATED')
      },
    })
    renderApp(<Who />)

    expect(await screen.findByText('client')).toBeInTheDocument()
    expect(getToken()).toBe('the-new-one')
    expect(asked).toEqual(['Bearer the-one-before', 'Bearer the-new-one'])
  })

  it('still logs out on "your session ended" for the token that is there', async () => {
    setToken('a-test-token')
    pretendApi({ 'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED') })
    renderApp(<Who />)

    expect(await screen.findByText('nobody')).toBeInTheDocument()
    expect(getToken()).toBeNull()
  })
})
