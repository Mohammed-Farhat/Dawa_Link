import { createContext, useContext } from 'react'

import type { Schemas } from './client'

// Who is logged in. Every screen reads it from here; `SessionProvider` fills it.

export type Me = Schemas['Me']

export type Session = {
  /** The logged-in user, or null. `undefined` while we are still asking the API. */
  me: Me | null | undefined
  /**
   * While `me` is still `undefined`: the API couldn't be reached (or failed) and is asked
   * again after a pause. Not a log out: the screen says so and waits (docs/11 §7).
   */
  unreachable: boolean
  /** Keeps the token a login gave, and who it belongs to. */
  start: (loggedIn: Schemas['LoggedIn']) => void
  logout: () => Promise<void>
  /** Asks the API again who we are (after the profile changed, or an email was confirmed). */
  refresh: () => Promise<void>
  /**
   * The account was just deleted (R-AU10): every session of it already ended on the
   * server, so there is no log out to ask for. Forgets the token and the person, and the
   * welcome page says once that the account is deleted.
   */
  accountDeleted: () => void
}

export const SessionContext = createContext<Session | null>(null)

export function useSession(): Session {
  const session = useContext(SessionContext)
  if (!session) throw new Error('useSession needs a SessionProvider above it')
  return session
}

// The welcome page's one-time line after a deletion. Kept in this tab's storage, not in
// the router: whichever page the client's portal sends a logged-out person to first, the
// line waits for the welcome page and is shown there once.
const DELETED_NOTE = 'dawalink.accountDeleted'

export function noteAccountDeleted(): void {
  try {
    window.sessionStorage.setItem(DELETED_NOTE, '1')
  } catch {
    // Storage refused (a private window): the deletion stands, the line is not shown.
  }
}

/** Whether a deletion's line is waiting: the client's portal then goes to the welcome page. */
export function accountDeletedNoted(): boolean {
  try {
    return window.sessionStorage.getItem(DELETED_NOTE) === '1'
  } catch {
    return false
  }
}

/** The line was shown: a reload doesn't say it again. */
export function forgetAccountDeletedNote(): void {
  try {
    window.sessionStorage.removeItem(DELETED_NOTE)
  } catch {
    // Nothing to forget.
  }
}
