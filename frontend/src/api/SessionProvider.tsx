import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useCallback, useEffect, useMemo } from 'react'

import { api, clearToken, getToken, LOGGED_OUT_EVENT, type Schemas, setToken, unwrap } from './client'
import { type Me, SessionContext } from './session'

const ME = ['me']

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ME,
    queryFn: async (): Promise<Me | null> => {
      if (!getToken()) return null
      try {
        return await unwrap(api.GET('/api/v1/auth/me'))
      } catch {
        // No session any more, or the API can't be reached: treated as logged out.
        return null
      }
    },
    staleTime: 60_000,
    retry: false,
  })

  /**
   * Whoever is logged in changes: a log out, a session that ended, a new login. **Nothing
   * of the person before is shown to the next one** (docs/09 FS-34): the lists the pages
   * keep in memory (reservations, offers, the chat) carry no name of their own, so they
   * are all dropped.
   *
   * The screen is told first who is there now. Emptying the whole memory first left the
   * page holding on to the person who had just logged out (found 2026-11-18).
   */
  const becomes = useCallback(
    (me: Me | null) => {
      queryClient.setQueryData(ME, me)
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
    await queryClient.cancelQueries()
    becomes(null)
  }, [becomes, queryClient])
  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME })
  }, [queryClient])

  const session = useMemo(
    () => ({ me: query.isPending ? undefined : (query.data ?? null), start, logout, refresh }),
    [query.isPending, query.data, start, logout, refresh],
  )
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
}
