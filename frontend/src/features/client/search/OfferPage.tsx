import { Modal, NumberInput } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../../api/client'
import { BackIcon, MapIcon, PhoneIcon, ShieldIcon } from '../../../components/icons'
import { Banner, Screen } from '../../../components/layout'
import { aboutUsd, calendarDate, dayWord, directionsUrl, lbp, plainAmount } from '../../../format'
import { errorMessage, strings } from '../../../strings/en'
import { MAX_DAYS_OF_USE, placeBody, useSearchChoices } from './choices'
import { FitBadge, PrescriptionLine, PriceBlock } from './parts'
import { useTapKey } from './tapKey'
import { lastsKnown, openWords, travelWords } from './words'

const o = strings.offer
const r = strings.reserve
const s = strings.search
const DAY_CHOICES = [7, 12, 30]
/** The packs of one medicine a client may hold at a time (`MAX_UNITS_PER_GROUP` in the
 * API, which checks again). */
const MOST_PACKS = 3

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
    // Only "not found" means the box is gone. Anything else (the connection, a value the
    // server refused) is said as what it is, with a way to try again that starts from
    // clean choices: no error stays with the client from one offer to the next.
    const code = found.error instanceof ApiFailure ? found.error.code : 'INTERNAL_ERROR'
    const gone = code === 'NOT_FOUND'
    return (
      <Screen plain narrow>
        <Banner tone="amber" alert>
          {gone ? o.gone : errorMessage(code)}
        </Banner>
        {!gone && (
          <button
            type="button"
            className="pill-button"
            onClick={() => {
              choices.set({ daysOfUse: null, pickupDay: null })
              void found.refetch()
            }}
          >
            {strings.common.tryAgain}
          </button>
        )}
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
            {strings.ticket.directions}{' '}
            <span className="sr-only">{strings.common.opensNewTab}</span>
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
          {/* The expiry date once: the line above says it unless the box is known to last. */}
          {lastsKnown(listing, choices.daysOfUse) && `${s.expires(calendarDate(listing.expiry_date))} · `}
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

/** Refusals after which this box can't be had here: the sheet points to the others. */
const GONE_HERE = new Set(['NOT_ENOUGH_STOCK', 'LISTING_NOT_AVAILABLE'])

/**
 * What the reserve sheet says when the server refused. Two refusals have the sheet's own
 * words (docs/11 §7): the general ones are written for the chat's cards, where "ask for
 * fresh options" makes sense and the limit's words hide that what is held counts too.
 */
function refusalWords(failed: ApiFailure, listing: Listing): string {
  if (failed.code === 'PRICE_CHANGED') {
    // The server says the new price; the offer, read again, says it too.
    const said = Number(failed.details.new_price)
    return r.priceChanged(lbp(Number.isFinite(said) && said > 0 ? said : listing.price.lbp))
  }
  if (failed.code === 'LIMIT_GROUP_UNITS') return r.tooManyPacks
  return errorMessage(failed.code)
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
  // One key per tap: kept for a retry while the outcome is unknown, so nothing is
  // reserved twice; replaced only after an answer that proves nothing was (A#28).
  const key = useTapKey()

  const days = listing.pickup_days_allowed
  const day = choices.pickupDay && days.includes(choices.pickupDay) ? choices.pickupDay : days[0]
  const most = Math.min(MOST_PACKS, listing.available)
  // The total in dollars too, as every other price (docs/11 §8).
  const totalUsd = aboutUsd({
    lbp: listing.price.lbp * qty,
    usd_approx: listing.price.usd_approx == null ? null : listing.price.usd_approx * qty,
  })

  async function reserve() {
    setSending(true)
    setFailed(null)
    try {
      const reserved = await unwrap(
        api.POST('/api/v1/reservations', {
          params: { header: { 'Idempotency-Key': key.current() } },
          body: {
            listing_id: listing.id,
            qty,
            expected_price_lbp: listing.price.lbp,
            pickup_day: day,
            days_of_use: choices.daysOfUse ?? 1,
          },
        }),
      )
      key.done()
      await queryClient.invalidateQueries({ queryKey: ['reservations'] })
      navigate(`/reservations/${reserved.id}`, { replace: true })
    } catch (error) {
      const failure = error instanceof ApiFailure ? error : new ApiFailure('INTERNAL_ERROR', 500)
      key.failed(failure)
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
        {/* [+] stopped: say why, the limit or what is left here (B section 7). */}
        {qty >= most && (
          <span className="hint">{listing.available < MOST_PACKS ? r.onlyLeft(listing.available) : r.mostPacks}</span>
        )}
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
            max={MAX_DAYS_OF_USE}
            // A number over the most can't be typed at all, and the store would cut it
            // down anyway (`tidy`).
            clampBehavior="strict"
            allowDecimal={false}
            allowNegative={false}
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
          {refusalWords(failed, listing)}
        </Banner>
      )}
      {failed && GONE_HERE.has(failed.code) && (
        // The box went: the same medicine may still be at another pharmacy.
        <Link to={`/search?product=${listing.product.id}`} className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
          {r.otherPharmacies}
        </Link>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span className="hint">{r.total}</span>
          <span style={{ fontSize: 20, fontWeight: 600 }}>{lbp(listing.price.lbp * qty)}</span>
          {totalUsd && <span className="hint">{totalUsd}</span>}
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
