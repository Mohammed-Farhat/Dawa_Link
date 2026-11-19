import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, ApiFailure, newKey, type Schemas, unwrap } from '../../../api/client'
import { Banner } from '../../../components/layout'
import { calendarDate, dayAndClock, dayWord, lbp, plainAmount } from '../../../format'
import { errorMessage, strings } from '../../../strings/en'

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
  const [day, setDay] = useState(days[0])
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  async function answer(accept: boolean) {
    setSending(true)
    setFailed(null)
    try {
      if (accept) {
        const reserved = await unwrap(
          api.POST('/api/v1/offers/{offer_id}/accept', {
            params: { path: { offer_id: offer.id }, header: { 'Idempotency-Key': newKey() } },
            body: { pickup_day: day },
          }),
        )
        navigate(`/reservations/${reserved.id}`)
      } else {
        await unwrap(
          api.POST('/api/v1/offers/{offer_id}/decline', { params: { path: { offer_id: offer.id } } }),
        )
      }
    } catch (error) {
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
      <dl className="card__lines">
        <div className="card__line">
          <dt>{strings.reserve.total}</dt>
          <dd>{lbp(offer.total.lbp)}</dd>
        </div>
        <div className="card__line">
          <dt>{o.expires}</dt>
          <dd>{calendarDate(offer.expiry_date)}</dd>
        </div>
      </dl>
      {offer.saving.lbp > 0 ? (
        <span className="saving">{strings.common.save_(plainAmount(offer.saving.lbp))}</span>
      ) : (
        // A pharmacy names the price of a box it releases, up to the public price
        // (BLD-D44): an offer with nothing off says so before the client accepts.
        <span className="hint">{o.noSaving}</span>
      )}
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
                onClick={() => setDay(allowed)}
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
          disabled={sending || days.length === 0}
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
