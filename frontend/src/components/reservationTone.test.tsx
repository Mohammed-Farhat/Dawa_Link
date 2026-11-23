import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '../api/client'
import { ReservationCard } from '../features/pharmacy/ReservationCard'
import { strings } from '../strings/en'
import { RESERVATION, renderApp } from '../test/render'
import { reservationTone } from './reservationTone'

// One meaning per colour (docs/11 §2.1, B#21): a reservation's state is the same colour
// for the client, the pharmacy and the admin.

const AT_THE_COUNTER = {
  id: RESERVATION.id,
  ref: 'R-7K3Q2F',
  state: 'RESERVED',
  status_text: 'Hand over by today 21:00',
  product: RESERVATION.product,
  batch: 'A123',
  expiry_date: '2027-01-15',
  qty: 1,
  qty_requested: 1,
  price_each: { lbp: 600_000, usd_approx: 6.7 },
  total: { lbp: 600_000, usd_approx: 6.7 },
  pickup_day: '2026-11-16',
  deadline: '2026-11-16T19:00:00Z',
  is_new: false,
  created_at: '2026-11-16T08:00:00Z',
  closed_at: null,
} satisfies Schemas['PharmacyReservation']

describe('The colour of a reservation (B#21)', () => {
  it('is green while it waits and once it is picked up, red when it failed, grey when cancelled', () => {
    expect(reservationTone('RESERVED')).toBe('green')
    expect(reservationTone('PICKED_UP')).toBe('green')
    expect(reservationTone('NOT_AVAILABLE')).toBe('red')
    expect(reservationTone('EXPIRED_NO_SHOW')).toBe('red')
    expect(reservationTone('CANCELLED_BY_CLIENT')).toBe('grey')
    expect(reservationTone('CANCELLED_BY_SYSTEM')).toBe('grey')
    // An offer waits for the client's tap.
    expect(reservationTone('OFFERED')).toBe('amber')
  })

  it("is the same on the pharmacy's card", () => {
    const states = [
      ['RESERVED', 'status-pill--green'],
      ['NOT_AVAILABLE', 'status-pill--red'],
      ['CANCELLED_BY_CLIENT', 'status-pill--grey'],
    ] as const
    for (const [state, colour] of states) {
      const text = `${state} words`
      const { unmount } = renderApp(
        <ReservationCard reservation={{ ...AT_THE_COUNTER, state, status_text: text }} notice={null} onNotice={() => {}} />,
      )
      expect(screen.getByRole('article', { name: strings.pharmacy.reservation('R-7K3Q2F') })).toBeInTheDocument()
      expect(screen.getByText(text)).toHaveClass(colour)
      unmount()
    }
  })
})
