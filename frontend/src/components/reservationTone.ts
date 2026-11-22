import type { Schemas } from '../api/client'

// One colour per state of a reservation, the same for the client, the pharmacy and the
// admin (B#21; docs/11 §2.1: one meaning per colour, and a word always goes with it).

/** Every state a reservation can be in, as any of the three portals reads it. */
export type ReservationState = Schemas['ClientReservation']['state']

export type ReservationTone = 'green' | 'amber' | 'red' | 'grey'

const TONES: Record<ReservationState, ReservationTone> = {
  // Held for the client, waiting for their tap: "your tap is needed".
  OFFERED: 'amber',
  // Waiting at the counter, then handed over: both are the client's box.
  RESERVED: 'green',
  PICKED_UP: 'green',
  // The box was not there, or nobody came for it: failed.
  NOT_AVAILABLE: 'red',
  EXPIRED_NO_SHOW: 'red',
  // Cancelled, by the client or by the system: information only.
  CANCELLED_BY_CLIENT: 'grey',
  CANCELLED_BY_SYSTEM: 'grey',
}

/** The colour of a reservation's state: a `status-pill--…` or a `Banner` tone. */
export function reservationTone(state: ReservationState): ReservationTone {
  return TONES[state]
}
