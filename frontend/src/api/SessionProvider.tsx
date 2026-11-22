import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useCallback, useEffect, useMemo } from 'react'

import {
  api,
  ApiFailure,
  clearToken,
  getToken,
  LOGGED_OUT_EVENT,
  type Schemas,
  setToken,
  TOKEN_KEY,
  UNAUTHENTICATED,
  unwrap,
} from './client'
import { type Me, noteAccountDeleted, SessionContext } from './session'

const ME = ['me']

/**
 * Who the token kept in this browser belongs to, or null for nobody.
 *
 * An answer about a token that was replaced while it was on its way (a login logged
 * someone in, another tab logged in or out) is about the person before:
 * the question is asked again for the token there now. Otherwise a late "your session
 * ended" for the old token would show the new person as logged out, or a late answer
 * would show the person before.
 */
async function whoIsLoggedIn(): Promise<Me | null> {
  const asked = getToken()
  if (!asked) return null
  let me: Me | null
  try {
    me = await unwrap(api.GET('/api/v1/auth/me'))
  } catch (error) {
    // Only the API saying so means there is no session any more. The API out of
    // reach, or failing, is not a log out: the person is asked about again (A#8).
    if (!(error instanceof ApiFailure && error.code === UNAUTHENTICATED)) throw error
    me = null
  }
  return getToken() === asked ? me : whoIsLoggedIn()
}

/** The pause before asking again who we are: 1 s, 2 s, 4 s… never more than 15 s. */
function pauseBeforeRetry(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 15_000)
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ME,
    queryFn: async (): Promise<Me | null> => {
      return whoIsLoggedIn()
    },
    staleTime: 60_000,
    retry: true,
    retryDelay: pauseBeforeRetry,
    // Asked even when the browser says it is offline: its guess is often wrong, and a
    // paused question would show "Loading…" for ever instead of the offline line.
    networkMode: 'always',
  })

  /**
   * Whoever is logged in changes: a log out, a session that ended, a new login. **Nothing
   * of the person before is shown to the next one** (docs/09 FS-34): the lists the pages
   * keep in memory (reservations, offers, the chat) carry no name of their own, so they
   * are all dropped.
   *
   * The screen is told first who is there now. Emptying the whole memory first left the
   * page holding on to the person who had just logged out (found 2026-11-18).
   *
   * `undefined`: someone is logged in, but who is not known yet (another tab logged in):
   * the screen waits while the API is asked.
   */
  const becomes = useCallback(
    (me: Me | null | undefined) => {
      if (me === undefined) {
        void queryClient.resetQueries({ queryKey: ME, exact: true })
      } else {
        queryClient.setQueryData(ME, me)
      }
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME[0] })
    },
    [queryClient],
  )

  // The API said the session ended (docs/11 §7, "Session expired").
  useEffect(() => {
    const forget = () => becomes(null)
    window.addEventListener(LOGGED_OUT_EVENT, forget)
    return () => window.removeEventListener(LOGGED_OUT_EVENT, forget)
  }, [becomes])

  // Another tab of this browser logged out, or logged in as someone else: this tab
  // follows, so it never shows one person's pages under another's session (A#33).
  // `key === null` is the whole storage cleared.
  useEffect(() => {
    const follow = (event: StorageEvent) => {
      if (event.key !== null && event.key !== TOKEN_KEY) return
      if (event.key !== null && event.oldValue === event.newValue) return
      becomes(getToken() ? undefined : null)
    }
    window.addEventListener('storage', follow)
    return () => window.removeEventListener('storage', follow)
  }, [becomes])

  const start = useCallback(
    (loggedIn: Schemas['LoggedIn']) => {
      setToken(loggedIn.token)
      becomes(loggedIn.me)
    },
    [becomes],
  )
  const logout = useCallback(async () => {
    await api.POST('/api/v1/auth/logout').catch(() => undefined)
    clearToken()
    becomes(null)
  }, [becomes])
  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME })
  }, [queryClient])
  // The note first, so that the page the portal sends a logged-out person to already
  // knows where to go: the welcome page, which says it once.
  const accountDeleted = useCallback(() => {
    noteAccountDeleted()
    clearToken()
    becomes(null)
  }, [becomes])

  // Not known yet, and the last question failed: the API can't be reached (or answers
  // with an error) and is being asked again after a pause.
  const unreachable = query.data === undefined && (query.failureCount > 0 || query.isError)
  const session = useMemo(
    () => ({ me: query.data, unreachable, start, logout, refresh, accountDeleted }),
    [query.data, unreachable, start, logout, refresh, accountDeleted],
  )
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
}
