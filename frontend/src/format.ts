import type { Schemas } from './api/client'
import { strings } from './strings/en'

// How numbers and times are written everywhere (docs/11 §8): LBP first with the USD
// amount beside it, 24-hour Beirut time with a day word, Western digits.

const BEIRUT = 'Asia/Beirut'
const c = strings.common

export function lbp(amount: number): string {
  return c.lbp(amount.toLocaleString('en-US'))
}

export function plainAmount(amount: number): string {
  return amount.toLocaleString('en-US')
}

export function aboutUsd(money: Schemas['Money']): string | null {
  if (money.usd_approx === null || money.usd_approx === undefined) return null
  return c.aboutUsd(money.usd_approx.toFixed(1))
}

/** The Beirut calendar day of a moment, as "2026-11-16". */
function beirutDay(moment: Date): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: BEIRUT }).format(moment)
}

function daysBetween(fromDay: string, toDay: string): number {
  return Math.round((Date.parse(toDay) - Date.parse(fromDay)) / 86_400_000)
}

/** "23:00", in Beirut time. */
export function clock(moment: string | Date): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: BEIRUT,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(moment))
}

/** "Today", "Tomorrow" or "Fri 20 Nov", counted from `now` (the server's clock). */
export function dayWord(moment: string | Date, now: string | Date): string {
  const days = daysBetween(beirutDay(new Date(now)), beirutDay(new Date(moment)))
  if (days === 0) return c.today
  if (days === 1) return c.tomorrow
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: BEIRUT,
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  }).format(new Date(moment))
}

/** "Today 23:00" or "Fri 20 Nov 23:00".
 *
 * A pharmacy open until midnight gives a deadline at 00:00 of the next day. That reads
 * as "Today 24:00", the way its opening hours are written, never "Tomorrow 00:00". */
export function dayAndClock(moment: string | Date, now: string | Date): string {
  const at = new Date(moment)
  // Some browsers write midnight as 24:00 by themselves.
  if (clock(at) === '00:00' || clock(at) === '24:00') {
    return `${dayWord(new Date(at.getTime() - 60_000), now)} 24:00`
  }
  return `${dayWord(at, now)} ${clock(at)}`
}

/** A moment inside a sentence: "16:00" today, "tomorrow 01:30", or "Fri 20 Nov 10:00",
 * counted from `now` (the server's clock: the demo clock may be ahead of the device's).
 * A watch started at 19:30 ends at 01:30 the next day, which "until 01:30" hid (B#39). */
export function clockInSentence(moment: string | Date, now: string | Date): string {
  const words = dayAndClock(moment, now)
  if (words.startsWith(`${c.today} `)) return words.slice(c.today.length + 1)
  if (words.startsWith(`${c.tomorrow} `)) {
    return `${c.tomorrowInSentence} ${words.slice(c.tomorrow.length + 1)}`
  }
  return words
}

/** The same, with today said too: "today 23:30", "tomorrow 01:30", "Fri 20 Nov 10:00".
 * For a watch's end: its six hours often cross midnight, and "until 23:30" left the
 * reader to work out which day it meant (B#39). */
export function dayClockInSentence(moment: string | Date, now: string | Date): string {
  const words = dayAndClock(moment, now)
  if (words.startsWith(`${c.today} `)) return `${c.todayInSentence} ${words.slice(c.today.length + 1)}`
  return clockInSentence(moment, now)
}

/** "45 min", "2 h", "1 h 20 min": a length of time, never "80 min" (A#37). */
export function duration(minutes: number): string {
  const whole = Math.max(0, Math.round(minutes))
  return c.duration(Math.floor(whole / 60), whole % 60)
}

/** A walk longer than this is not a way anyone would go: only the car's time is shown. */
export const LONGEST_WALK_SHOWN_MIN = 60

/**
 * "4 min by car · 21 min on foot": how far a pharmacy is, in the words and the order of
 * the assistant's cards (A#37). The walk is left out above an hour ("1294 min on foot"
 * helped nobody) and a long time is written in hours: the cards don't do these two yet,
 * and this function is exported for them.
 */
export function tripWords(carMin: number, walkMin: number): string {
  const search = strings.search
  const byCar = search.byCar(duration(carMin))
  if (walkMin > LONGEST_WALK_SHOWN_MIN) return byCar
  return `${byCar} · ${search.onFoot(duration(walkMin))}`
}

/** A reservation's state in a sentence. The server's words, except a missed pickup, which
 * is never called "Expired": that word is for a box's date, shown beside it (B#13). */
export function reservationWords(reservation: Schemas['Reservation']): string {
  if (reservation.state === 'EXPIRED_NO_SHOW') return strings.ticket.missedPickup
  return reservation.status_text
}

/** "14 Mar 2027", for a date with no time ("2027-03-14"). */
export function calendarDate(day: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(`${day}T00:00:00Z`))
}

/** The hour in Beirut right now: for "Good morning". */
export function beirutHour(moment: Date = new Date()): number {
  return Number(
    new Intl.DateTimeFormat('en-GB', { timeZone: BEIRUT, hour: '2-digit', hour12: false }).format(
      moment,
    ),
  )
}

/**
 * Where Google Maps shows the way to a pharmacy (the owner, 2026-11-18, BLD-D43).
 *
 * **Only the pharmacy's pin is in the link: never where the client is** (docs/11 §11).
 * Google Maps fills "from" itself with the device's own location, if the client lets it:
 * that is between the client's device and Google, and nothing of it passes through
 * DawaLink. On a phone the link opens the Maps app.
 */
export function directionsUrl(pin: Schemas['Pin']): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${pin.lat}%2C${pin.lon}`
}

/** "Fri 13 Nov 09:30", in Beirut time: a moment said by its date, never "today". For
 * lists of past events, where "today" would depend on which clock is asked. */
export function dateAndClock(moment: string | Date): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: BEIRUT,
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
    .format(new Date(moment))
    .replace(',', '')
}

const ARABIC_LETTER = /[؀-ۿ]/g
const LATIN_LETTER = /[A-Za-z]/g

/**
 * `'ar'` for text a person or the model wrote in Arabic letters, so a screen reader reads
 * it with an Arabic voice (B#10); `undefined` otherwise, so the page's English is kept.
 * Arabizi is Latin letters, and stays English. Put it next to `dir="auto"`, on the element
 * that holds only the written text: never on a label in English beside it.
 */
export function langOf(text: string | null | undefined): 'ar' | undefined {
  if (!text) return undefined
  const arabic = text.match(ARABIC_LETTER)?.length ?? 0
  const latin = text.match(LATIN_LETTER)?.length ?? 0
  return arabic > 0 && arabic >= latin ? 'ar' : undefined
}
