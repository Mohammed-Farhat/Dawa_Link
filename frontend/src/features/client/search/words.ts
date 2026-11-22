import type { Schemas } from '../../../api/client'
import { clock, tripWords } from '../../../format'
import { strings } from '../../../strings/en'

const s = strings.search

/** "4 min by car · 21 min on foot", or "about 3 km" when no road time is known. */
export function travelWords(travel: Schemas['Travel']): string {
  if (travel.source === 'straight') return s.about(travel.km.toFixed(1))
  return tripWords(travel.car_min, travel.walk_min)
}

/** True when the fit line (FitBadge) says "Lasts your N days" alone, without the box's
 * expiry date: only then does the offer's page write the date a second time. */
export function lastsKnown(listing: Schemas['Listing'], daysOfUse: number | null): boolean {
  return daysOfUse !== null && listing.fits === true
}

/** "open until 21:00", or "closed now". */
export function openWords(pharmacy: Schemas['PharmacyCard']): string {
  if (!pharmacy.open_now || !pharmacy.closes_at) return s.closedNow
  const closes = clock(pharmacy.closes_at)
  return s.openUntil(closes === '00:00' ? '24:00' : closes)
}
