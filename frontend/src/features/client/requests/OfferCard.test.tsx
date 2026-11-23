import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '../../../api/client'
import { strings } from '../../../strings/en'
import { answer, CONFIG, pretendApi, refusal, renderApp, RESERVATION } from '../../../test/render'
import { OfferCard } from './OfferCard'

const o = strings.offers
const NOW = CONFIG.server_now
const OFFER_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

const OFFER = {
  id: OFFER_ID,
  kind: 'matching',
  product: RESERVATION.product,
  pharmacy: RESERVATION.pharmacy,
  qty: 1,
  price_each: { lbp: 600_000, usd_approx: 6.7 },
  total: { lbp: 600_000, usd_approx: 6.7 },
  saving: { lbp: 400_000, usd_approx: 4.47 },
  expiry_date: '2027-06-03',
  days_of_use: 1,
  expires_at: '2026-11-16T10:00:00Z',
  pickup_days_allowed: ['2026-11-16', '2026-11-17'],
  request_id: null,
} satisfies Schemas['Offer']

/** The card as the page shows it, with a way to read the offer again with other days. */
function Reread({ later }: { later: string[] }) {
  const [offer, setOffer] = useState<Schemas['Offer']>(OFFER)
  return (
    <>
      <button type="button" onClick={() => setOffer({ ...OFFER, pickup_days_allowed: later })}>
        read again
      </button>
      <OfferCard offer={offer} now={NOW} />
    </>
  )
}

const accepts = () => pretendApi({ [`POST /api/v1/offers/${OFFER_ID}/accept`]: answer(201, RESERVATION) })

describe('An offer card (A#32)', () => {
  it('sends a day that is still allowed when the chosen one dropped out', async () => {
    const api = accepts()
    renderApp(<Reread later={['2026-11-17']} />)
    const user = userEvent.setup()

    // Today was chosen; after closing time the offer read again has tomorrow only.
    expect(screen.getByRole('button', { name: strings.common.today })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'read again' }))
    expect(screen.getByRole('button', { name: strings.common.tomorrow })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: o.accept }))

    await waitFor(() => expect(api.sent('POST', `/api/v1/offers/${OFFER_ID}/accept`)).toHaveLength(1))
    expect(api.sent('POST', `/api/v1/offers/${OFFER_ID}/accept`)[0].body).toEqual({ pickup_day: '2026-11-17' })
  })

  it('keeps [Accept] off while no day is allowed', async () => {
    accepts()
    renderApp(<Reread later={[]} />)

    await userEvent.click(screen.getByRole('button', { name: 'read again' }))

    expect(screen.getByText(o.noDay)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: o.accept })).toBeDisabled()
  })
})

describe('One reservation per [Accept and reserve] (A#28)', () => {
  async function acceptTwice() {
    const user = userEvent.setup()
    const accept = screen.getByRole('button', { name: o.accept })
    await user.click(accept)
    await screen.findByRole('alert')
    await waitFor(() => expect(accept).toBeEnabled())
    await user.click(accept)
  }
  const keys = (api: ReturnType<typeof pretendApi>) =>
    api.sent('POST', `/api/v1/offers/${OFFER_ID}/accept`).map((call) => call.headers.get('Idempotency-Key'))

  it('keeps the key while the outcome is unknown', async () => {
    const api = pretendApi({ [`POST /api/v1/offers/${OFFER_ID}/accept`]: answer(504, '<html>Gateway Timeout</html>') })
    renderApp(<OfferCard offer={OFFER} now={NOW} />)

    await acceptTwice()

    await waitFor(() => expect(keys(api)).toHaveLength(2))
    expect(keys(api)[1]).toBe(keys(api)[0])
  })

  it('takes a new key after a refusal', async () => {
    const api = pretendApi({ [`POST /api/v1/offers/${OFFER_ID}/accept`]: refusal(409, 'PICKUP_DAY_INVALID') })
    renderApp(<OfferCard offer={OFFER} now={NOW} />)

    await acceptTwice()

    await waitFor(() => expect(keys(api)).toHaveLength(2))
    expect(keys(api)[1]).not.toBe(keys(api)[0])
  })
})

describe('An offer shows its box as search does (B#5)', () => {
  const HOURS = [
    { day: '2026-11-16', hours: '08:00-21:00' },
    { day: '2026-11-17', hours: '09:00-13:00' },
  ]

  it('gives the price with its saving, and the hours of the day chosen', async () => {
    renderApp(<OfferCard offer={{ ...OFFER, pickup_day_hours: HOURS }} now={NOW} />)

    expect(screen.getByText(strings.common.save_('400,000'))).toBeInTheDocument()
    expect(screen.getByText('08:00-21:00')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: strings.common.tomorrow }))
    expect(screen.getByText('09:00-13:00')).toBeInTheDocument()
    expect(screen.queryByText('08:00-21:00')).not.toBeInTheDocument()
  })

  it('says how long it lasts when the days were said, and the date when they were not', () => {
    const { unmount } = renderApp(<OfferCard offer={{ ...OFFER, days_of_use: 12 }} now={NOW} />)
    expect(screen.getByText(strings.offer.lastsYour(12))).toBeInTheDocument()
    unmount()

    renderApp(<OfferCard offer={OFFER} now={NOW} />)
    expect(screen.getByText(strings.offer.makeSure('3 Jun 2027'))).toBeInTheDocument()
  })

  it('with no day left to pick, says why and the expiry once, and no fit', () => {
    renderApp(<OfferCard offer={{ ...OFFER, days_of_use: 12, pickup_days_allowed: [] }} now={NOW} />)

    expect(screen.getByText(o.noDay)).toBeInTheDocument()
    expect(screen.getAllByText('3 Jun 2027')).toHaveLength(1)
    expect(screen.queryByText(strings.offer.lastsYour(12))).not.toBeInTheDocument()
  })
})
