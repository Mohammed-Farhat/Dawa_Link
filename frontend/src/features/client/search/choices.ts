import { createContext, useContext } from 'react'

import type { Schemas } from '../../../api/client'

// What the client chose for this search: where they are, for how long they need the
// medicine, when they'll come. It lives in memory only: **the location is never put in
// an address, in the browser's history or in its storage** (docs/11 §11).

export type Place =
  | { kind: 'profile' }
  | { kind: 'point'; lat: number; lon: number }
  | { kind: 'district'; id: number; name: string }

export type SearchChoices = {
  /** What the client typed in the search box: kept while they open an offer and come
   * back. Never in an address. */
  name: string
  place: Place
  /** null: "not sure". The page then warns with the expiry date instead of promising. */
  daysOfUse: number | null
  /** null: any day the pharmacy allows. */
  pickupDay: string | null
  sort: 'best' | 'nearest' | 'cheapest' | 'latest_expiry'
  /** The most the client wants to pay for a pack, in LBP. null: no limit. */
  maxPriceLbp: number | null
  /** Only pharmacies that are open at this moment. */
  openNow: boolean
}

export type ChoicesStore = SearchChoices & { set: (change: Partial<SearchChoices>) => void }

/** The most the API takes (its schemas say the same): a longer treatment is a year. */
export const MAX_DAYS_OF_USE = 365
/** Eleven digits: under the API's own limit for a price in LBP. */
export const MAX_PRICE_LBP = 99_999_999_999

/**
 * What the client chose, made safe to send. These choices go with **every** search and
 * every offer the client opens, so one number the API refuses (999 days of use) would
 * make each of them fail until the page is loaded again: the owner found exactly that on
 * 2026-11-18. Whatever a form hands over, the store keeps only what can be sent.
 */
export function tidy(change: Partial<SearchChoices>): Partial<SearchChoices> {
  const safe = { ...change }
  if ('daysOfUse' in safe) safe.daysOfUse = within(safe.daysOfUse, MAX_DAYS_OF_USE)
  if ('maxPriceLbp' in safe) safe.maxPriceLbp = within(safe.maxPriceLbp, MAX_PRICE_LBP)
  return safe
}

/** A whole number from 1 to `most`; more than that is `most`; anything else is "not said". */
function within(value: number | null | undefined, most: number): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 1) return null
  return Math.min(Math.floor(value), most)
}

export const ChoicesContext = createContext<ChoicesStore | null>(null)

export function useSearchChoices(): ChoicesStore {
  const store = useContext(ChoicesContext)
  if (!store) throw new Error('useSearchChoices needs a SearchChoicesProvider above it')
  return store
}

/** The place as the API takes it, in a request's body. */
export function placeBody(place: Place): Schemas['LocationIn'] | null {
  if (place.kind === 'point') return { lat: place.lat, lon: place.lon }
  if (place.kind === 'district') return { district_id: place.id }
  return null
}
