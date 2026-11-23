import { describe, expect, it } from 'vitest'

import { clockInSentence, dayClockInSentence, duration, reservationWords, tripWords } from './format'
import { strings } from './strings/en'
import { RESERVATION } from './test/render'

const NOW = '2026-11-16T08:00:00Z' // 10:00 in Beirut

describe('How a length of time is written (A#37)', () => {
  it('says hours and minutes, never "80 min"', () => {
    expect(duration(4)).toBe('4 min')
    expect(duration(59)).toBe('59 min')
    expect(duration(60)).toBe('1 h')
    expect(duration(80)).toBe('1 h 20 min')
    expect(duration(1294)).toBe('21 h 34 min')
  })

  it('puts the car first, then the walk, and leaves out a walk of more than an hour', () => {
    expect(tripWords(4, 21)).toBe('4 min by car · 21 min on foot')
    expect(tripWords(12, 60)).toBe('12 min by car · 1 h on foot')
    // "57 min by car · 1294 min on foot" helped nobody.
    expect(tripWords(57, 1294)).toBe('57 min by car')
    expect(tripWords(80, 61)).toBe('1 h 20 min by car')
  })
})

describe('A moment inside a sentence (B#39)', () => {
  it('says the day when it is not today, by the server clock', () => {
    // 14:00 UTC is 16:00 in Beirut, the same day.
    expect(clockInSentence('2026-11-16T14:00:00Z', NOW)).toBe('16:00')
    // A watch started at 19:30 ends at 01:30 the next day.
    expect(clockInSentence('2026-11-16T23:30:00Z', NOW)).toBe('tomorrow 01:30')
    expect(clockInSentence('2026-11-20T08:00:00Z', NOW)).toBe('Fri 20 Nov 10:00')
    // Midnight is the end of the day it closes, as everywhere else.
    expect(clockInSentence('2026-11-16T22:00:00Z', NOW)).toBe('24:00')
  })

  it("names today too, for a watch's end", () => {
    expect(dayClockInSentence('2026-11-16T21:30:00Z', NOW)).toBe('today 23:30')
    expect(dayClockInSentence('2026-11-16T23:30:00Z', NOW)).toBe('tomorrow 01:30')
    expect(dayClockInSentence('2026-11-20T08:00:00Z', NOW)).toBe('Fri 20 Nov 10:00')
    expect(dayClockInSentence('2026-11-16T22:00:00Z', NOW)).toBe('today 24:00')
  })
})

describe("A reservation's state in words (B#13)", () => {
  it('calls a reservation nobody came for a missed pickup, whatever the server said', () => {
    const missed = { ...RESERVATION, state: 'EXPIRED_NO_SHOW' as const }
    expect(reservationWords({ ...missed, status_text: "Expired: it wasn't picked up in time" })).toBe(
      strings.ticket.missedPickup,
    )
    expect(reservationWords({ ...missed, status_text: "Missed pickup: it wasn't picked up in time" })).toBe(
      strings.ticket.missedPickup,
    )
    expect(reservationWords({ ...RESERVATION, state: 'CANCELLED_BY_CLIENT', status_text: 'Cancelled by you' })).toBe(
      'Cancelled by you',
    )
    expect(strings.ticket.missedPickup).not.toMatch(/expired/i)
  })
})
