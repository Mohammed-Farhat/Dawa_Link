import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../../api/client'
import { Banner } from '../../../components/layout'
import { calendarDate, dayAndClock, dayWord } from '../../../format'
import { errorMessage, strings } from '../../../strings/en'
import { Fit, PriceBlock } from '../search/parts'
import { useTapKey } from '../search/tapKey'

const o = strings.offers

/**
 * An offer: stock held for this client for two hours (docs/11 §4, the amber card).
 * [Accept and reserve] makes it a reservation; [No thanks] gives the box to the next
 * client who waits. Like every button here, it only asks: the server decides.
 */
export function OfferCard({ offer, now }: { offer: Schemas['Offer']; now: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const days = offer.pickup_days_allowed
  const [picked, setPicked] = useState<string | null>(null)
  // The days allowed are read again every few seconds, and one drops out at closing time
  // (today, after 20:00): the day sent is always one still allowed (A#32). None: no tap.
  const day: string | undefined = picked !== null && days.includes(picked) ? picked : days[0]
  // The pharmacy's hours on the day chosen, as search shows them (B#5).
  const hours = offer.pickup_day_hours?.find((open) => open.day === day)?.hours
  const daysSaid = offer.days_of_use > 1 ? offer.days_of_use : null
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  // The same key until an answer proves nothing was reserved (A#28).
  const key = useTapKey()

  async function answer(accept: boolean) {
    setSending(true)
    setFailed(null)
    try {
      if (accept) {
        if (day === undefined) return
        const reserved = await unwrap(
          api.POST('/api/v1/offers/{offer_id}/accept', {
            params: { path: { offer_id: offer.id }, header: { 'Idempotency-Key': key.current() } },
            body: { pickup_day: day },
          }),
        )
        key.done()
        navigate(`/reservations/${reserved.id}`)
      } else {
        await unwrap(
          api.POST('/api/v1/offers/{offer_id}/decline', { params: { path: { offer_id: offer.id } } }),
        )
      }
    } catch (error) {
      if (accept) key.failed(error)
      setFailed(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
    } finally {
      await Promise.all(
        ['offers', 'request', 'requests', 'reservations'].map((key) =>
          queryClient.invalidateQueries({ queryKey: [key] }),
        ),
      )
      setSending(false)
    }
  }

  return (
    <article className="card card--amber" aria-label={`${o.title}: ${offer.product.name}`}>
      <span className="status-pill status-pill--amber">
        {o.validUntil(dayAndClock(offer.expires_at, now))}
      </span>
      <h2 className="card__title">
        {offer.product.name} × {offer.qty}
      </h2>
      <span className="soft" style={{ fontSize: 15 }}>
        {offer.kind === 'early_release' ? o.released : o.matched} · {offer.pharmacy.name},{' '}
        {offer.pharmacy.district}
      </span>
      {/* The price with its saving, as search shows a box (B#5). */}
      <div className="row-card__top">
        <span className="soft">{strings.reserve.total}</span>
        <PriceBlock price={offer.total} saving={offer.saving} />
      </div>
      {offer.saving.lbp === 0 && (
        // A pharmacy names the price of a box it releases, up to the public price
        // (BLD-D44): an offer with nothing off says so before the client accepts.
        <span className="hint">{o.noSaving}</span>
      )}
      <dl className="card__lines">
        {hours && (
          <div className="card__line">
            <dt>{strings.chat.card.openThatDay}</dt>
            <dd>{hours}</dd>
          </div>
        )}
        {(daysSaid !== null || days.length === 0) && (
          <div className="card__line">
            <dt>{o.expires}</dt>
            <dd>{calendarDate(offer.expiry_date)}</dd>
          </div>
        )}
      </dl>
      {/* Every day offered lasts the client's days (the server checked): the line says
          how long, or the date when no days were said (1 is what is used then, R-F2).
          With no day left, the banner below says why instead. */}
      {days.length > 0 && <Fit fits expiryDate={offer.expiry_date} daysOfUse={daysSaid} />}
      {days.length > 0 ? (
        <fieldset className="choice">
          <legend>{o.pickUpDay}</legend>
          <div className="chips">
            {days.map((allowed) => (
              <button
                key={allowed}
                type="button"
                className="chip"
                aria-pressed={allowed === day}
                onClick={() => setPicked(allowed)}
              >
                {dayWord(`${allowed}T12:00:00Z`, now)}
              </button>
            ))}
          </div>
        </fieldset>
      ) : (
        <Banner tone="amber">{o.noDay}</Banner>
      )}
      {failed && (
        <Banner tone="red" alert>
          {errorMessage(failed)}
        </Banner>
      )}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="pill-button"
          disabled={sending || day === undefined}
          onClick={() => void answer(true)}
        >
          {o.accept}
        </button>
        <button
          type="button"
          className="pill-button pill-button--outline"
          disabled={sending}
          onClick={() => void answer(false)}
        >
          {o.decline}
        </button>
      </div>
    </article>
  )
}
