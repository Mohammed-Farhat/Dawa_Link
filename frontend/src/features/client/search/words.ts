import type { Schemas } from '../../../api/client'
import { clock } from '../../../format'
import { strings } from '../../../strings/en'

const s = strings.search

/** "9 min walk · 4 min by car", or "about 3 km" when no road time is known. */
export function travelWords(travel: Schemas['Travel']): string {
  if (travel.source === 'straight') return s.about(travel.km.toFixed(1))
  return `${s.walk(travel.walk_min)} · ${s.car(travel.car_min)}`
}

/** "open until 21:00", or "closed now". */
export function openWords(pharmacy: Schemas['PharmacyCard']): string {
  if (!pharmacy.open_now || !pharmacy.closes_at) return s.closedNow
  const closes = clock(pharmacy.closes_at)
  return s.openUntil(closes === '00:00' ? '24:00' : closes)
}
