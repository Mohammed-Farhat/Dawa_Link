import { useRef } from 'react'

import { ApiFailure, newKey } from '../../../api/client'

/**
 * Whether a failed tap surely made nothing, so that the next tap may be a new one.
 *
 * Only a refusal of the API (a 4xx) says so. The connection lost, or a 5xx, leaves the
 * outcome unknown: a gateway's 504 can come after a slow reserve that did commit (A#28).
 * A 5xx the API wrote itself did roll back, but it reads like a gateway's to the page,
 * and keeping the key then costs nothing: `POST /reservations` keeps a key only with a
 * reservation it made, so a retry either finds that reservation or makes the first one.
 * (Accepting an offer ignores the key on the server today: a second accept after one that
 * committed is refused as OFFER_NOT_OPEN, and nothing is reserved twice.)
 */
export function madeNothing(error: unknown): boolean {
  return error instanceof ApiFailure && error.status >= 400 && error.status < 500
}

/**
 * The `Idempotency-Key` of a creating tap (docs/06 §1): the same key until an answer
 * proves that nothing was made, so a retry after a lost answer never reserves twice.
 */
export function useTapKey() {
  const key = useRef<string | null>(null)
  return {
    /** The key to send now. */
    current(): string {
      key.current ??= newKey()
      return key.current
    },
    /** After a tap failed: a new key next time only if this one surely made nothing. */
    failed(error: unknown): void {
      if (madeNothing(error)) key.current = null
    },
    /** After a tap succeeded: the next tap is a new one. */
    done(): void {
      key.current = null
    },
  }
}
