import { describe, expect, it } from 'vitest'

import { errorMessage, strings } from './en'
import { failureMessage } from './failure'

const l = strings.limits

describe('A refusal worded from what the API said', () => {
  it('says how many minutes to wait under an hour', () => {
    expect(failureMessage({ code: 'RATE_LIMITED', details: { retry_after_s: 25 } })).toBe(l.tryInMinutes(1))
    expect(failureMessage({ code: 'RATE_LIMITED', details: { retry_after_s: 601 } })).toBe(l.tryInMinutes(11))
  })

  it("says the day's limit from an hour on, never \"wait a minute\" (A#34, B#36)", () => {
    const daily = { code: 'RATE_LIMITED', details: { retry_after_s: 3600 } }
    expect(failureMessage(daily)).toBe(l.today)
    // In the chat it is the assistant's messages, and search still works.
    expect(failureMessage(daily, { chat: true })).toBe(l.chatToday)
    expect(failureMessage(daily, { chat: true })).toContain('search still works')
  })

  it('never says "tomorrow" for a limit counted per hour', () => {
    // An hourly limiter may answer 3,601 seconds when it was hit in a burst.
    expect(failureMessage({ code: 'RATE_LIMITED', details: { retry_after_s: 3601 } }, { hourly: true })).toBe(
      l.tryInMinutes(60),
    )
  })

  it('keeps the general sentence when the API said no wait', () => {
    expect(failureMessage({ code: 'RATE_LIMITED' })).toBe(errorMessage('RATE_LIMITED'))
    expect(failureMessage({ code: 'NOT_ENOUGH_STOCK' })).toBe(errorMessage('NOT_ENOUGH_STOCK'))
  })

  it('says "at 08:00" before 08:00, and "tomorrow" after 20:00 (B#37)', () => {
    // 06:00 in Beirut (04:00 UTC): requests open the same morning.
    const early = { code: 'OUTSIDE_REQUEST_HOURS', details: { opens_at: '2026-11-16T06:00:00Z' } }
    expect(failureMessage(early, { now: '2026-11-16T04:00:00Z' })).toBe(l.comeBack(l.comeBackAt('08:00')))
    // 21:00 in Beirut: tomorrow morning.
    const late = { code: 'OUTSIDE_REQUEST_HOURS', details: { opens_at: '2026-11-17T06:00:00Z' } }
    expect(failureMessage(late, { now: '2026-11-16T19:00:00Z' })).toBe(l.comeBack(l.comeBackTomorrow('08:00')))
    // Without the server's clock, the hour alone: still the next opening.
    expect(failureMessage(late)).toBe(l.comeBack(l.comeBackAt('08:00')))
  })

  it('has a general sentence for request hours that is true at any hour', () => {
    expect(failureMessage({ code: 'OUTSIDE_REQUEST_HOURS' })).toBe(strings.errors.OUTSIDE_REQUEST_HOURS)
    expect(strings.errors.OUTSIDE_REQUEST_HOURS).not.toContain('tomorrow')
  })
})

describe('A refusal about an account', () => {
  it("says how long a locked account's lock has left, from the API's retry_after", () => {
    expect(failureMessage({ code: 'ACCOUNT_LOCKED', details: { retry_after: 841 } })).toBe(l.locked(15))
    expect(failureMessage({ code: 'ACCOUNT_LOCKED', details: { retry_after: 30 } })).toBe(l.locked(1))
    expect(failureMessage({ code: 'ACCOUNT_LOCKED' })).toBe(errorMessage('ACCOUNT_LOCKED'))
  })

  it('says "busy" for a 503 with a wait, and keeps the general sentence without one', () => {
    expect(failureMessage({ code: 'SERVICE_UNAVAILABLE', details: { retry_after_s: 1 } })).toBe(l.busy)
    expect(failureMessage({ code: 'SERVICE_UNAVAILABLE' })).toBe(errorMessage('SERVICE_UNAVAILABLE'))
  })
})
