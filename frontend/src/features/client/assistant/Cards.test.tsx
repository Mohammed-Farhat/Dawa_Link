import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '../../../api/client'
import { strings } from '../../../strings/en'
import { accessibilityProblems, renderApp, RESERVATION, RESERVE_CARD } from '../../../test/render'
import { MessageCards, type OffersKnown } from './Cards'

const s = strings.chat
const NOW = '2026-11-16T08:00:00Z' // 10:00 in Beirut

/** A reserve card as the server now sends it: its screen lines, and its boxes as facts. */
const WITH_BOX = {
  ...RESERVE_CARD,
  lines: [
    { label: 'Pharmacy', value: 'Hamra Pharmacy, Beirut' },
    { label: 'Quantity', value: '2 packs' },
    { label: 'Pick up', value: 'Mon 16 Nov' },
  ],
  box: {
    price: { lbp: 1_400_000, usd_approx: 15.64 },
    saving: { lbp: 600_000, usd_approx: 6.7 },
    expiry_date: '2027-03-14',
    days_of_use: 12,
    hours_on_pickup_day: '08:00-13:00, 16:00-21:00',
    travel: { car_min: 75, walk_min: 375, km: 52.1, source: 'road' },
  },
} satisfies Schemas['Card']

function show(cards: Schemas['Card'][], offers: OffersKnown | null = null) {
  return renderApp(<MessageCards cards={cards} busy={false} offers={offers} onAct={() => {}} />)
}

describe("An assistant's card shows its box as search does (B#5, B#31, A#37)", () => {
  it('gives the price with its saving, the fit, the day’s hours and the trip in search’s words', async () => {
    const { container } = show([WITH_BOX])

    const card = screen.getByRole('article', { name: WITH_BOX.title })
    expect(within(card).getByText(s.card.atTheCounter)).toBeInTheDocument()
    expect(within(card).getByText('1,400,000 LBP')).toBeInTheDocument()
    // The dollars as everywhere on the website: one decimal.
    expect(within(card).getByText(strings.common.aboutUsd('15.6'))).toBeInTheDocument()
    expect(within(card).getByText(strings.common.save_('600,000'))).toBeInTheDocument()
    expect(within(card).getByText(strings.offer.lastsYour(12))).toBeInTheDocument()
    expect(within(card).getByText('08:00-13:00, 16:00-21:00')).toBeInTheDocument()
    expect(within(card).getByText('14 Mar 2027')).toBeInTheDocument()
    // An hour and a quarter by car; a six-hour walk is no way to go, so it isn't shown.
    expect(within(card).getByText(strings.search.byCar(strings.common.duration(1, 15)))).toBeInTheDocument()
    expect(within(card).queryByText(/on foot/)).not.toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('says the expiry date to check when no days of use were said', () => {
    show([{ ...WITH_BOX, box: { ...WITH_BOX.box, days_of_use: 1 } }])

    const card = screen.getByRole('article', { name: WITH_BOX.title })
    expect(within(card).getByText(strings.offer.makeSure('14 Mar 2027'))).toBeInTheDocument()
    // Said once: the line of the fit holds the date.
    expect(within(card).queryByText(s.card.expires)).not.toBeInTheDocument()
  })

  it('on a plan for different days, says each box lasts its own, and the soonest expiry', () => {
    const plan = {
      ...WITH_BOX,
      type: 'reserve_group',
      action_label: 'Reserve these',
      selectable_items: [
        { item_key: 'a', label: 'AUGMENTIN 1G x 2', price: { lbp: 1_400_000, usd_approx: 15.64 } },
        { item_key: 'b', label: 'CONCOR 5MG x 1', price: { lbp: 500_000, usd_approx: 5.59 } },
      ],
      box: { ...WITH_BOX.box, days_of_use: null, travel: null },
    } satisfies Schemas['Card']

    show([plan])

    expect(screen.getByText(s.card.lastsEach)).toBeInTheDocument()
    expect(screen.getByText(s.card.soonestExpiry)).toBeInTheDocument()
  })

  it('shows a card made before its box was stored as it always did', () => {
    show([RESERVE_CARD])

    const card = screen.getByRole('article', { name: RESERVE_CARD.title })
    expect(within(card).getByText('600,000 LBP (about $6.70)')).toBeInTheDocument()
    // Its own line says the price: no second one beside it.
    expect(within(card).queryByText(strings.common.aboutUsd('6.7'))).not.toBeInTheDocument()
  })
})

describe('A box held for the client, in the chat (B#15)', () => {
  const HELD = {
    ...RESERVE_CARD,
    card_id: '3:0',
    origin: 'system',
    type: 'offer',
    title: '',
    lines: [],
    recommended: false,
    action_label: null,
    data: { order_id: RESERVATION.id, product: 'CONCOR 5MG', offer_expires_at: '2026-11-16T10:00:00Z' },
  } satisfies Schemas['Card']

  it('names the medicine and until when, and leads to the offer', () => {
    show([HELD], { open: new Set([RESERVATION.id]), now: NOW, here: false })

    expect(screen.getByText(s.system.offerHeld('CONCOR 5MG', '12:00'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: s.system.seeOffer })).toHaveAttribute('href', '/')
  })

  it("on a request's page, where the offer is shown above, leads nowhere else", () => {
    show([HELD], { open: new Set([RESERVATION.id]), now: NOW, here: true })

    expect(screen.getByText(s.system.offerHeld('CONCOR 5MG', '12:00'))).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('once it no longer waits, says only that it was held', () => {
    show([HELD], { open: new Set(), now: NOW, here: false })

    expect(screen.getByText(s.system.offerWas('CONCOR 5MG'))).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('after its time, even before the list of offers is read again', () => {
    show([HELD], { open: new Set([RESERVATION.id]), now: '2026-11-16T10:30:00Z', here: false })

    expect(screen.getByText(s.system.offerWas('CONCOR 5MG'))).toBeInTheDocument()
  })
})
