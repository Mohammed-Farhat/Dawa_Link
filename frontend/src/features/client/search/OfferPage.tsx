import { Modal, NumberInput } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, ApiFailure, newKey, type Schemas, unwrap } from '../../../api/client'
import { BackIcon, MapIcon, PhoneIcon, ShieldIcon } from '../../../components/icons'
import { Banner, Screen } from '../../../components/layout'
import { calendarDate, dayWord, directionsUrl, lbp, plainAmount } from '../../../format'
import { errorMessage, strings } from '../../../strings/en'
import { placeBody, useSearchChoices } from './choices'
import { FitBadge, PrescriptionLine, PriceBlock } from './parts'
import { openWords, travelWords } from './words'

const o = strings.offer
const r = strings.reserve
const s = strings.search
const DAY_CHOICES = [7, 12, 30]

type Listing = Schemas['Listing']

/** CS-7: one pharmacy and its offer. [Reserve] opens the reserve sheet. */
export function OfferPage() {
  const { id = '' } = useParams()
  const choices = useSearchChoices()
  const [reserving, setReserving] = useState(false)
  const found = useQuery({
    queryKey: ['listing', id, choices.place, choices.daysOfUse],
    queryFn: () =>
      unwrap(
        api.POST('/api/v1/listings/{listing_id}/view', {
          params: { path: { listing_id: id } },
          body: { location: placeBody(choices.place), days_of_use: choices.daysOfUse },
        }),
      ),
    placeholderData: (before) => before,
    retry: false,
  })

  if (found.isError) {
    return (
      <Screen plain narrow>
        <Banner tone="amber">{o.gone}</Banner>
        <Link to="/search" className="pill-button pill-button--grey">
          {o.backToSearch}
        </Link>
      </Screen>
    )
  }
  if (!found.data) {
    return (
      <Screen plain narrow>
        <p className="soft">{strings.common.loading}</p>
      </Screen>
    )
  }

  const { listing, week, server_now: now } = found.data
  const { pharmacy, product } = listing
  const canReserve = listing.pickup_days_allowed.length > 0
  return (
    <Screen plain narrow>
      <Link
        // Back to what the client was looking at: the results of the name they typed, or
        // this medicine's own page.
        to={choices.name.trim().length >= 2 ? '/search' : `/search?product=${product.id}`}
        className="round-button"
        aria-label={strings.common.back}
      >
        <BackIcon />
      </Link>

      <section className="row-card" aria-label={pharmacy.name}>
        <h1 className="page-title" style={{ fontSize: 22 }}>
          {pharmacy.name}
        </h1>
        <span className="soft">
          {pharmacy.address}, {pharmacy.district}
        </span>
        <span className="soft">
          {travelWords(listing.travel)} · {openWords(pharmacy)}
        </span>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <a className="pill-button pill-button--grey" href={directionsUrl(pharmacy.pin)} target="_blank" rel="noreferrer">
            <MapIcon small />
            {strings.ticket.directions}
          </a>
          <a className="pill-button pill-button--grey" href={`tel:${pharmacy.phone}`}>
            <PhoneIcon small />
            {strings.ticket.call}
          </a>
        </div>
      </section>

      <section className="row-card" aria-label={product.name}>
        <div className="row-card__top">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 18, fontWeight: 600 }}>{product.name}</span>
            <span className="soft" style={{ fontSize: 15 }}>
              {[product.strength, product.form, product.pack].filter(Boolean).join(' · ')}
            </span>
          </div>
          <PriceBlock price={listing.price} saving={listing.saving} big />
        </div>
        <FitBadge listing={listing} daysOfUse={choices.daysOfUse} />
        {product.prescription_required && <PrescriptionLine />}
        <span className="hint">
          {s.expires(calendarDate(listing.expiry_date))} ·{' '}
          {s.left(listing.available, listing.more_available)} · {s.off(listing.discount_pct)}
        </span>
        <span className="card__note" style={{ color: 'var(--green)' }}>
          <ShieldIcon small />
          {o.sealed}
        </span>
      </section>

      <section className="row-card" aria-label={o.hours}>
        <span style={{ fontWeight: 600 }}>{o.hours}</span>
        <dl className="card__lines">
          {week.map((day) => (
            <div className="card__line" key={day.day}>
              <dt>{dayWord(`${day.day}T12:00:00Z`, now)}</dt>
              <dd>{day.hours}</dd>
            </div>
          ))}
        </dl>
        <span className="hint">{o.holds(pharmacy.pickup_days)}</span>
      </section>

      <div className="pinned-space" aria-hidden="true" />
      <div className="pinned">
        <button type="button" className="pill-button pill-button--wide" onClick={() => setReserving(true)}>
          {o.reserve}
        </button>
      </div>

      <Modal opened={reserving} onClose={() => setReserving(false)} title={r.title} centered radius="xl">
        <ReserveSheet listing={listing} now={now} canReserve={canReserve} />
      </Modal>
    </Screen>
  )
}

/**
 * CS-8: how many, which day, for how long, then [Reserve].
 *
 * Changing the days of use asks the server again which days still work: **the website
 * never works out a date or a fit itself**, and the server checks everything again at
 * the tap (R-F1, R-F3).
 */
function ReserveSheet({ listing, now, canReserve }: { listing: Listing; now: string; canReserve: boolean }) {
  const choices = useSearchChoices()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [qty, setQty] = useState(1)
  const [otherDays, setOtherDays] = useState(
    choices.daysOfUse !== null && !DAY_CHOICES.includes(choices.daysOfUse),
  )
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<ApiFailure | null>(null)
  // One key per tap: kept for a retry after a lost connection, so nothing is reserved
  // twice; replaced once the server has answered (docs/06 §1).
  const key = useRef(newKey())

  const days = listing.pickup_days_allowed
  const day = choices.pickupDay && days.includes(choices.pickupDay) ? choices.pickupDay : days[0]
  const most = Math.min(3, listing.available)

  async function reserve() {
    setSending(true)
    setFailed(null)
    try {
      const reserved = await unwrap(
        api.POST('/api/v1/reservations', {
          params: { header: { 'Idempotency-Key': key.current } },
          body: {
            listing_id: listing.id,
            qty,
            expected_price_lbp: listing.price.lbp,
            pickup_day: day,
            days_of_use: choices.daysOfUse ?? 1,
          },
        }),
      )
      await queryClient.invalidateQueries({ queryKey: ['reservations'] })
      navigate(`/reservations/${reserved.id}`, { replace: true })
    } catch (error) {
      const failure = error instanceof ApiFailure ? error : new ApiFailure('INTERNAL_ERROR', 500)
      if (failure.code !== 'UNREACHABLE') key.current = newKey()
      setFailed(failure)
      // What the page shows may be out of date: read the offer again.
      await queryClient.invalidateQueries({ queryKey: ['listing'] })
    } finally {
      setSending(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <div style={{ fontWeight: 600 }}>{listing.product.name}</div>
        <div className="soft" style={{ fontSize: 15 }}>
          {listing.pharmacy.name}, {listing.pharmacy.district}
        </div>
      </div>

      <fieldset className="choice">
        <legend>{r.howMany}</legend>
        <div className="stepper">
          <button type="button" className="round-button round-button--grey" aria-label={r.fewer} disabled={qty <= 1} onClick={() => setQty(qty - 1)}>
            −
          </button>
          <span className="stepper__value" aria-live="polite">
            {strings.common.packs(qty)}
          </span>
          <button type="button" className="round-button round-button--grey" aria-label={r.more} disabled={qty >= most} onClick={() => setQty(qty + 1)}>
            +
          </button>
        </div>
      </fieldset>

      <fieldset className="choice">
        <legend>{s.forDays}</legend>
        <div className="chips">
          {DAY_CHOICES.map((count) => (
            <button
              key={count}
              type="button"
              className="chip"
              aria-pressed={!otherDays && choices.daysOfUse === count}
              onClick={() => {
                setOtherDays(false)
                choices.set({ daysOfUse: count })
              }}
            >
              {s.days(count)}
            </button>
          ))}
          <button type="button" className="chip" aria-pressed={otherDays} onClick={() => setOtherDays(true)}>
            {s.other}
          </button>
          <button
            type="button"
            className="chip"
            aria-pressed={!otherDays && choices.daysOfUse === null}
            onClick={() => {
              setOtherDays(false)
              choices.set({ daysOfUse: null })
            }}
          >
            {s.notSure}
          </button>
        </div>
        {otherDays && (
          <NumberInput
            label={s.otherDays}
            size="md"
            min={1}
            max={365}
            allowDecimal={false}
            value={choices.daysOfUse ?? ''}
            onChange={(value) => choices.set({ daysOfUse: typeof value === 'number' && value >= 1 ? value : null })}
          />
        )}
        <FitBadge listing={listing} daysOfUse={choices.daysOfUse} />
      </fieldset>

      {canReserve && (
        <fieldset className="choice">
          <legend>{r.pickUpDay}</legend>
          <div className="chips">
            {days.map((allowed) => (
              <button
                key={allowed}
                type="button"
                className="chip"
                aria-pressed={allowed === day}
                onClick={() => choices.set({ pickupDay: allowed })}
              >
                {dayWord(`${allowed}T12:00:00Z`, now)}
              </button>
            ))}
          </div>
          {listing.expiry_limits_pickup && (
            <span className="hint">{r.pickUpBy(dayWord(`${days[days.length - 1]}T12:00:00Z`, now))}</span>
          )}
        </fieldset>
      )}
      {!canReserve && <Banner tone="amber">{r.noDay}</Banner>}

      {listing.product.prescription_required && <PrescriptionLine />}
      <span className="hint">{r.payThere}</span>

      {failed && (
        <Banner tone="red" alert>
          {errorMessage(failed.code)}
        </Banner>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span className="hint">{r.total}</span>
          <span style={{ fontSize: 20, fontWeight: 600 }}>{lbp(listing.price.lbp * qty)}</span>
          {listing.saving.lbp > 0 && (
            <span className="saving">{strings.common.save_(plainAmount(listing.saving.lbp * qty))}</span>
          )}
        </div>
        <button type="button" className="pill-button" disabled={!canReserve || sending} onClick={() => void reserve()}>
          {r.submit(qty)}
        </button>
      </div>
    </div>
  )
}
