import { NativeSelect, NumberInput } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../../api/client'
import { BackIcon, ChatIcon, PinIcon, PrescriptionIcon } from '../../../components/icons'
import { Banner } from '../../../components/layout'
import { calendarDate, dayWord } from '../../../format'
import { errorMessage, strings } from '../../../strings/en'
import { LocationSheet } from '../assistant/LocationSheet'
import { placeBody, useSearchChoices } from './choices'
import { NotifyMe } from './NotifyMe'
import { PriceBlock } from './parts'
import { openWords, travelWords } from './words'

const s = strings.search
const DAY_CHOICES = [7, 12, 30]
const PAGE = 20

/**
 * CS-6: the search page. **No part of it involves the assistant**: with the assistant
 * switched off it works the same (C15).
 *
 * The medicine is chosen by its ID in the address (`?product=…`), which says nothing
 * about the client. Where they are stays in memory and travels in a request's body.
 */
export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const productId = params.get('product')
  const [text, setText] = useState('')
  const [typed] = useDebouncedValue(text.trim(), 250)
  const looking = typed.length >= 2 && !productId
  const names = useQuery({
    queryKey: ['products', typed],
    queryFn: () => unwrap(api.GET('/api/v1/catalog/products', { params: { query: { q: typed } } })),
    enabled: looking,
  })

  return (
    <main className="screen screen--plain">
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Link to="/" className="round-button" aria-label={strings.common.back}>
          <BackIcon />
        </Link>
        <label htmlFor="medicine-name" className="sr-only">
          {s.label}
        </label>
        <input
          id="medicine-name"
          className="chat__input"
          type="search"
          autoComplete="off"
          placeholder={s.placeholder}
          value={text}
          onChange={(event) => {
            setText(event.currentTarget.value)
            // Typing a new name leaves the medicine that was chosen.
            if (productId) setParams({}, { replace: true })
          }}
        />
      </div>

      {!productId && !looking && <p className="soft">{s.typeMore}</p>}
      {looking && names.data && (
        <Suggestions
          found={names.data}
          typed={typed}
          onChoose={(id) => setParams({ product: id })}
          onRetype={setText}
        />
      )}
      {productId && <Results key={productId} productId={productId} />}
    </main>
  )
}

function Suggestions({
  found,
  typed,
  onChoose,
  onRetype,
}: {
  found: Schemas['Products']
  typed: string
  onChoose: (productId: string) => void
  onRetype: (name: string) => void
}) {
  if (found.items.length === 0) {
    return (
      <div className="empty">
        <span>{s.nothingNamed(typed)}</span>
        {found.did_you_mean.length > 0 && (
          <div className="chips" role="group" aria-label={s.didYouMean}>
            {found.did_you_mean.map((name) => (
              <button key={name} type="button" className="chip" onClick={() => onRetype(name)}>
                {name}
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }
  return (
    <ul className="plain-list">
      {found.items.map((product) => (
        <li key={product.id}>
          <button type="button" className="suggestion" onClick={() => onChoose(product.id)}>
            <span style={{ fontWeight: 600 }}>{product.name}</span>
            <span className="hint">{[product.form, product.pack].filter(Boolean).join(' · ')}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

function Results({ productId }: { productId: string }) {
  const choices = useSearchChoices()
  const navigate = useNavigate()
  const [limit, setLimit] = useState(PAGE)
  const [otherDays, setOtherDays] = useState(false)
  const [choosingPlace, setChoosingPlace] = useState(false)
  const result = useQuery({
    queryKey: [
      'listings',
      productId,
      choices.place,
      choices.daysOfUse,
      choices.pickupDay,
      choices.sort,
      choices.maxPriceLbp,
      limit,
    ],
    queryFn: () =>
      unwrap(
        api.POST('/api/v1/listings/search', {
          body: {
            product_id: productId,
            location: placeBody(choices.place),
            days_of_use: choices.daysOfUse,
            pickup_day: choices.pickupDay,
            max_price: choices.maxPriceLbp ? { amount: String(choices.maxPriceLbp), currency: 'LBP' } : null,
            sort: choices.sort,
            on_foot: false,
            cursor: 0,
            limit,
          },
        }),
      ),
    placeholderData: (before) => before,
    retry: false,
  })

  if (result.isError) {
    const code = result.error instanceof ApiFailure ? result.error.code : 'INTERNAL_ERROR'
    return (
      <Banner tone="red" alert>
        {code === 'PRODUCT_NOT_ALLOWED' ? errorMessage('NOT_FOUND') : errorMessage(code)}
      </Banner>
    )
  }
  if (!result.data) return <p className="soft">{strings.common.loading}</p>

  const { product, items, no_match: noMatch, location, server_now: now } = result.data
  const placeLabel =
    location.source === 'shared'
      ? strings.chat.location.yours
      : location.source === 'profile' && location.label
        ? strings.chat.location.home(location.label)
        : (location.label ?? strings.chat.location.button(null))
  const askToFind = () =>
    navigate('/assistant', { state: { draft: s.askDraft(product.name) } })

  return (
    <>
      <section className="row-card" aria-label={product.name}>
        <h1 className="page-title" style={{ fontSize: 22 }}>
          {product.name}
        </h1>
        <span className="soft" style={{ fontSize: 15 }}>
          {[product.strength, product.form, product.pack].filter(Boolean).join(' · ')}
        </span>
        {product.prescription_required && (
          <span className="card__note">
            <PrescriptionIcon small />
            {s.prescription}
          </span>
        )}

        <fieldset className="choice">
          <legend>{s.pickUp}</legend>
          <div className="chips">
            <Chip chosen={choices.pickupDay === null} onClick={() => choices.set({ pickupDay: null })}>
              {s.anyDay}
            </Chip>
            {result.data.upcoming_days.slice(0, 4).map((day) => (
              <Chip key={day} chosen={choices.pickupDay === day} onClick={() => choices.set({ pickupDay: day })}>
                {dayWord(`${day}T12:00:00Z`, now)}
              </Chip>
            ))}
          </div>
        </fieldset>

        <fieldset className="choice">
          <legend>{s.forDays}</legend>
          <div className="chips">
            {DAY_CHOICES.map((days) => (
              <Chip
                key={days}
                chosen={!otherDays && choices.daysOfUse === days}
                onClick={() => {
                  setOtherDays(false)
                  choices.set({ daysOfUse: days })
                }}
              >
                {s.days(days)}
              </Chip>
            ))}
            <Chip chosen={otherDays} onClick={() => setOtherDays(true)}>
              {s.other}
            </Chip>
            <Chip
              chosen={!otherDays && choices.daysOfUse === null}
              onClick={() => {
                setOtherDays(false)
                choices.set({ daysOfUse: null })
              }}
            >
              {s.notSure}
            </Chip>
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
        </fieldset>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <button type="button" className="chat__location" onClick={() => setChoosingPlace(true)}>
            <PinIcon small />
            {s.near}: {placeLabel}
          </button>
          <NativeSelect
            aria-label={s.sort}
            size="sm"
            value={choices.sort}
            onChange={(event) => choices.set({ sort: event.currentTarget.value as typeof choices.sort })}
            data={Object.entries(s.sorts).map(([value, label]) => ({ value, label }))}
          />
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 14 }}>
            {s.maxPrice}
            <input
              className="quantity-input quantity-input--wide"
              type="text"
              inputMode="numeric"
              value={choices.maxPriceLbp ?? ''}
              onChange={(event) => {
                const digits = event.currentTarget.value.replace(/\D/g, '')
                choices.set({ maxPriceLbp: digits ? Number(digits) : null })
              }}
            />
          </label>
        </div>
      </section>

      <div role="status" aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {items.length > 0 && (
          <span className="soft" style={{ fontSize: 15 }}>
            {s.found(result.data.total_found)}
            {choices.daysOfUse !== null && ` · ${s.allLast(choices.daysOfUse)}`}
          </span>
        )}
        {items.length > 0 && result.data.left_out_by_pickup_day > 0 && (
          <span className="hint">{s.earlierShowsMore(result.data.left_out_by_pickup_day)}</span>
        )}

        {items.map((listing) => (
          <Link key={listing.id} to={`/listings/${listing.id}`} className="search-row">
            <span className="search-row__initial" aria-hidden="true">
              {listing.pharmacy.name.charAt(0)}
            </span>
            <span className="search-row__facts">
              <span style={{ fontWeight: 600 }}>
                {listing.pharmacy.name}
                <span className="soft" style={{ fontWeight: 400 }}> · {listing.pharmacy.district}</span>
              </span>
              <span className="soft">
                {travelWords(listing.travel)} · {openWords(listing.pharmacy)}
              </span>
              <span className="hint">
                {s.expires(calendarDate(listing.expiry_date))} ·{' '}
                {s.left(listing.available, listing.more_available)}
              </span>
            </span>
            <PriceBlock price={listing.price} saving={listing.saving} />
          </Link>
        ))}

        {items.length === 0 && (
          <div className="empty">
            <span style={{ fontWeight: 600 }}>
              {noMatch && choices.daysOfUse !== null
                ? s.tooEarly(choices.daysOfUse, calendarDate(noMatch.latest_expiry))
                : noMatch
                  ? s.notThatDay
                  : s.empty(product.name)}
            </span>
            <span className="soft" style={{ fontSize: 15 }}>
              {s.askToFindHint}
            </span>
            <button type="button" className="pill-button" onClick={askToFind}>
              <ChatIcon small />
              {s.askToFind}
            </button>
            <NotifyMe productId={productId} />
          </div>
        )}
        {result.data.next_cursor !== null && limit < 50 && (
          <button type="button" className="text-button" onClick={() => setLimit(50)}>
            {s.more}
          </button>
        )}
      </div>

      <LocationSheet
        opened={choosingPlace}
        onClose={() => setChoosingPlace(false)}
        onChoose={(place) =>
          choices.set({
            place:
              'lat' in place
                ? { kind: 'point', lat: place.lat, lon: place.lon }
                : { kind: 'district', id: place.district_id, name: place.name },
          })
        }
      />
    </>
  )
}

function Chip({ chosen, onClick, children }: { chosen: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" className="chip" aria-pressed={chosen} onClick={onClick}>
      {children}
    </button>
  )
}
