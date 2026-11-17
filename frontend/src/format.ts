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

/** Where OpenStreetMap shows the way to a pharmacy. Only the pharmacy's pin is in the
 * link: never where the client is (docs/11 §11). */
export function directionsUrl(pin: Schemas['Pin']): string {
  return `https://www.openstreetmap.org/directions?to=${pin.lat}%2C${pin.lon}#map=16/${pin.lat}/${pin.lon}`
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
