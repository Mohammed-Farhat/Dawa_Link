import type { HomeAreaValue } from './HomeArea'

// Where a client lives, as the sign-up form and the profile hold it while it is typed.

export type Pin = { lat: number; lon: number }

export type WhereValue = {
  /** One way or the other (the owner, 2026-11-18): a place on a map, or an area. */
  mode: 'map' | 'area'
  pin: Pin | null
  area: HomeAreaValue
}

export const emptyWhere: WhereValue = {
  mode: 'map',
  pin: null,
  area: { governorate: '', district: '', town: '' },
}

/** Whether the value says where the client lives, in the mode they chose. */
export function whereIsSaid(value: WhereValue): boolean {
  return value.mode === 'map' ? value.pin !== null : value.area.district !== ''
}
