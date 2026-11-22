import { clock, dayWord } from '../format'
import { errorMessage, strings } from './en'

// A refusal worded from what the API said about it, not from its code alone (A#34, B#36,
// B#37): "Please wait a minute" for a limit that lasts until tomorrow, or "come back
// tomorrow" at 06:00, sent people away for the wrong time.

const l = strings.limits

/** From this wait on, a limit is the day's: the API's daily limits answer 3,600 seconds. */
const DAY_LIMIT_S = 3600

export type Failure = { code: string; details?: Record<string, unknown> }

/** A wait in whole minutes, at least one: "about 3 minutes". */
export function minutesToWait(seconds: number): number {
  return Math.max(1, Math.ceil(seconds / 60))
}

/**
 * What to say for a refusal.
 *
 * - `RATE_LIMITED`: under an hour, how many minutes to wait; from an hour, the day's
 *   limit. `hourly` is for a limit counted per hour (where a client is, N-47): its wait
 *   may reach the hour itself, and it is never "tomorrow". `chat`: the day's limit is the
 *   assistant's messages, and search still works.
 * - `OUTSIDE_REQUEST_HOURS`: when requests open again, from the API's `opens_at`; `now`
 *   is the server's clock (the demo clock may be ahead of the device's), to say "tomorrow".
 * - `ACCOUNT_LOCKED`: how many minutes the account's lock has left.
 * - `SERVICE_UNAVAILABLE` with a wait: DawaLink is busy for a moment.
 * - Anything else, or a detail missing: the code's own sentence.
 */
export function failureMessage(
  failure: Failure,
  { now, chat = false, hourly = false }: { now?: string | Date; chat?: boolean; hourly?: boolean } = {},
): string {
  const details = failure.details ?? {}
  if (failure.code === 'RATE_LIMITED') {
    const wait = Number(details.retry_after_s)
    if (Number.isFinite(wait) && wait > 0) {
      if (hourly || wait < DAY_LIMIT_S) return l.tryInMinutes(Math.min(minutesToWait(wait), 60))
      return chat ? l.chatToday : l.today
    }
  }
  if (failure.code === 'ACCOUNT_LOCKED') {
    // The account's own lock (R-AU2): the API says how long it has left, as `retry_after`.
    const wait = Number(details.retry_after ?? details.retry_after_s)
    if (Number.isFinite(wait) && wait > 0) return l.locked(minutesToWait(wait))
  }
  // A 503 with a wait is a busy moment (every password slot taken), not DawaLink down.
  if (failure.code === 'SERVICE_UNAVAILABLE' && details.retry_after_s !== undefined) return l.busy
  if (failure.code === 'OUTSIDE_REQUEST_HOURS' && typeof details.opens_at === 'string') {
    const opens = new Date(details.opens_at)
    if (!Number.isNaN(opens.getTime())) return l.comeBack(whenItOpens(opens, now))
  }
  return errorMessage(failure.code)
}

function whenItOpens(opens: Date, now: string | Date | undefined): string {
  const at = clock(opens)
  // Without the server's clock the hour alone is still right: it is the next opening.
  if (now === undefined) return l.comeBackAt(at)
  const day = dayWord(opens, now)
  if (day === strings.common.today) return l.comeBackAt(at)
  if (day === strings.common.tomorrow) return l.comeBackTomorrow(at)
  return l.comeBackOn(day, at)
}
