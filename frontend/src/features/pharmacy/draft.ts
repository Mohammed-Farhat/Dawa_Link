import type { Schemas } from '../../api/client'
import { strings } from '../../strings/en'

// What a pharmacy types about itself, as the form holds it, and what is wrong with it
// before anything is sent (docs/03 PS-1). The API checks everything again.

const d = strings.pharmacy.details
const h = strings.pharmacy.hours

export type Pin = { lat: number; lon: number }
export type Range = { open: string; close: string }
/** Seven days, Monday first. A day with no range is a closed day. */
export type Week = Range[][]

export type Draft = {
  name: string
  license: string
  phone: string
  address: string
  district: string
  pin: Pin | null
  pickupDays: number
  week: Week
}

/** Where the map opens before a district is chosen: Beirut. */
export const START: Pin = { lat: 33.8938, lon: 35.5018 }
export const USUAL: Range = { open: '08:00', close: '20:00' }

export function emptyDraft(): Draft {
  return {
    name: '',
    license: '',
    phone: '',
    address: '',
    district: '',
    pin: null,
    pickupDays: 1,
    // Monday to Saturday, as most pharmacies open; Sunday closed. The pharmacy corrects it.
    week: [0, 1, 2, 3, 4, 5, 6].map((day) => (day < 6 ? [{ ...USUAL }] : [])),
  }
}

export function weekOf(hours: Schemas['OpeningRange'][]): Week {
  const week: Week = [[], [], [], [], [], [], []]
  for (const range of hours) {
    week[range.weekday]?.push({
      open: range.open,
      // A time field has no 24:00: midnight is shown as 00:00.
      close: range.close === '24:00' ? '00:00' : range.close,
    })
  }
  return week
}

export function draftOf(profile: Schemas['PharmacyProfile']): Draft {
  return {
    name: profile.name,
    license: profile.license_number,
    phone: profile.phone,
    address: profile.address,
    district: String(profile.district_id),
    pin: profile.location,
    pickupDays: profile.pickup_days,
    week: weekOf(profile.hours),
  }
}

/** A closing time of 00:00 means midnight at the end of the day. */
export function closing(range: Range): string {
  return range.close === '00:00' ? '24:00' : range.close
}

export function hoursOf(week: Week): Schemas['OpeningRange'][] {
  return week.flatMap((ranges, weekday) =>
    ranges.map((range) => ({ weekday, open: range.open, close: closing(range) })),
  )
}

export function weekProblem(week: Week): string | null {
  if (week.every((ranges) => ranges.length === 0)) return h.none
  for (const ranges of week) {
    let before = ''
    for (const range of ranges) {
      // "08:00" < "13:00" as text too: the times are always two digits each.
      if (!range.open || !range.close || range.open >= closing(range) || range.open < before) {
        return h.order
      }
      before = closing(range)
    }
  }
  return null
}

/** What is wrong, by the API's own field names, so its refusals land on the same field. */
export function problemsOf(draft: Draft): Record<string, string | null> {
  const p = d.problems
  const digits = draft.phone.replace(/\D/g, '')
  return {
    name: draft.name.trim().length >= 2 && draft.name.trim().length <= 60 ? null : p.name,
    license_number: draft.license.trim().length >= 2 ? null : p.license_number,
    phone: digits.length >= 7 && digits.length <= 13 ? null : p.phone,
    address: draft.address.trim().length >= 5 ? null : p.address,
    district_id: draft.district ? null : p.district_id,
    location: draft.pin ? null : p.location,
    hours: weekProblem(draft.week),
  }
}

export function bodyOf(draft: Draft): Schemas['PharmacyDetails'] {
  return {
    name: draft.name.trim(),
    license_number: draft.license.trim(),
    phone: draft.phone.trim(),
    address: draft.address.trim(),
    district_id: Number(draft.district),
    location: draft.pin ?? START,
    pickup_days: draft.pickupDays,
    hours: hoursOf(draft.week),
  }
}
