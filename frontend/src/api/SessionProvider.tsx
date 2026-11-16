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

  // The API said the session ended (docs/11 §7, "Session expired").
  useEffect(() => {
    const forget = () => queryClient.setQueryData(ME, null)
    window.addEventListener(LOGGED_OUT_EVENT, forget)
    return () => window.removeEventListener(LOGGED_OUT_EVENT, forget)
  }, [queryClient])

  const start = useCallback(
    (loggedIn: Schemas['LoggedIn']) => {
      setToken(loggedIn.token)
      queryClient.setQueryData(ME, loggedIn.me)
    },
    [queryClient],
  )
  const logout = useCallback(async () => {
    await api.POST('/api/v1/auth/logout').catch(() => undefined)
    clearToken()
    // Nothing of the previous user stays on the screen or in memory.
    queryClient.clear()
    queryClient.setQueryData(ME, null)
  }, [queryClient])
  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME })
  }, [queryClient])

  const session = useMemo(
    () => ({ me: query.isPending ? undefined : (query.data ?? null), start, logout, refresh }),
    [query.isPending, query.data, start, logout, refresh],
  )
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
}
