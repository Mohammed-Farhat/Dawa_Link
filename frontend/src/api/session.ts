import { createContext, useContext } from 'react'

import type { Schemas } from './client'

// Who is logged in. Every screen reads it from here; `SessionProvider` fills it.

export type Me = Schemas['Me']

export type Session = {
  /** The logged-in user, or null. `undefined` while we are still asking the API. */
  me: Me | null | undefined
  /** Keeps the token a login or a confirmation link gave, and who it belongs to. */
  start: (loggedIn: Schemas['LoggedIn']) => void
  logout: () => Promise<void>
  /** Asks the API again who we are (after the profile changed, or an email was confirmed). */
  refresh: () => Promise<void>
}

export const SessionContext = createContext<Session | null>(null)

export function useSession(): Session {
  const session = useContext(SessionContext)
  if (!session) throw new Error('useSession needs a SessionProvider above it')
  return session
}
