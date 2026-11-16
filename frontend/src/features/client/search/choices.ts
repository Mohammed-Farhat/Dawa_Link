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
  place: Place
  /** null: "not sure". The page then warns with the expiry date instead of promising. */
  daysOfUse: number | null
  /** null: any day the pharmacy allows. */
  pickupDay: string | null
  sort: 'best' | 'nearest' | 'cheapest' | 'latest_expiry'
}

export type ChoicesStore = SearchChoices & { set: (change: Partial<SearchChoices>) => void }

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
