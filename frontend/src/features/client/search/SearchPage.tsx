import { NativeSelect } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../../api/client'
import { BackIcon, ChatIcon, HistoryIcon, PinIcon, PrescriptionIcon } from '../../../components/icons'
import { Banner, Screen } from '../../../components/layout'
import { useWide } from '../../../components/wide'
import { calendarDate } from '../../../format'
import { errorMessage, strings } from '../../../strings/en'
import { LocationSheet } from '../assistant/LocationSheet'
import { placeBody, useSearchChoices } from './choices'
import { NotifyMe } from './NotifyMe'
import { PriceBlock } from './parts'
import { openWords, travelWords } from './words'

const s = strings.search
const PAGE = 20

type Listing = Schemas['Listing']
type Where = Schemas['LocationSummary']

/** The client's last searches (kept in their account, BLD-D42), and the two ways to
 * change them: a name searched again goes to the top, [Clear] empties the list. */
function useLastSearches() {
  const queryClient = useQueryClient()
  const list = useQuery({
    queryKey: ['searches'],
    queryFn: () => unwrap(api.GET('/api/v1/me/searches')),
    staleTime: 60_000,
  })
  const put = (answer: Schemas['Searches'] | null) => {
    if (answer) queryClient.setQueryData(['searches'], answer)
  }
  return {
    items: list.data?.items ?? [],
    /** Called when a search led somewhere, never for each letter typed. */
    keep: (name: string) => {
      if (name.trim().length < 2) return
      void unwrap(api.POST('/api/v1/me/searches', { body: { q: name.trim() } }))
        .then(put)
        .catch(() => null)
    },
    clear: () =>
      void unwrap(api.DELETE('/api/v1/me/searches'))
        .then(put)
        .catch(() => null),
  }
}

/**
 * CS-6: the search page. **No part of it involves the assistant**: with the assistant
 * switched off it works the same (C15).
 *
 * It is a search of what is in stock (the owner, 2026-11-18, BLD-D42): from the first
 * letter typed it shows the medicines a pharmacy lists now, each under its own name,
 * strength and form. A medicine nobody has is not shown. With nothing typed, the page
 * shows the client's last searches. One medicine's own page (`?product=…`) lists all its
 * pharmacies. Where the client is stays in memory and travels in a request's body, never
 * in an address.
 */
export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const { state } = useLocation() as { state: { q?: string } | null }
  const productId = params.get('product')
  const choices = useSearchChoices()
  const history = useLastSearches()
  // What was typed here before an offer was opened, or a name passed by another page.
  const [text, setTextHere] = useState(state?.q ?? choices.name)
  const setText = (value: string) => {
    setTextHere(value)
    choices.set({ name: value })
  }
  const [typed] = useDebouncedValue(text.trim(), 250)
  const looking = typed.length >= 1 && !productId

  function submit(event: FormEvent) {
    event.preventDefault()
    history.keep(text)
  }

  return (
    // Search is an entry of the menu (BLD-D42), so the page keeps the menu and has no way
    // "back" of its own. One medicine's page, opened from somewhere else, goes back to
    // the search.
    <Screen>
      <form className="search-form" role="search" onSubmit={submit}>
        {productId && typed.length === 0 && (
          <Link to="/search" className="round-button" aria-label={strings.common.back}>
            <BackIcon />
          </Link>
        )}
        <label htmlFor="medicine-name" className="sr-only">
          {s.label}
        </label>
        <input
          id="medicine-name"
          className="chat__input"
          type="search"
          autoComplete="off"
          // The page is for typing a name: the box is ready when it opens.
          autoFocus={!productId}
          placeholder={s.placeholder}
          value={text}
          onChange={(event) => {
            setText(event.currentTarget.value)
            // Typing a new name leaves the medicine that was chosen.
            if (productId) setParams({}, { replace: true })
          }}
        />
      </form>

      {!productId && !looking && (
        <LastSearches items={history.items} onPick={setText} onClear={history.clear} />
      )}
      {looking && (
        <ByName
          typed={typed}
          onRetype={setText}
          onOpen={() => history.keep(typed)}
          onChoose={(id) => {
            history.keep(typed)
            setParams({ product: id })
          }}
        />
      )}
      {productId && (
        <>
          {typed.length >= 1 && (
            <button
              type="button"
              className="text-button"
              style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}
              onClick={() => setParams({}, { replace: true })}
            >
              ← {s.backToResults(typed)}
            </button>
          )}
          <OneMedicine key={productId} productId={productId} />
        </>
      )}
    </Screen>
  )
}

/** With nothing typed: the names searched lately, one tap to search one again. */
function LastSearches({
  items,
  onPick,
  onClear,
}: {
  items: string[]
  onPick: (name: string) => void
  onClear: () => void
}) {
  if (items.length === 0) return <p className="soft">{s.typeMore}</p>
  return (
    <section className="filters" aria-label={s.lastSearches}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <span style={{ fontWeight: 600 }}>{s.lastSearches}</span>
        <button type="button" className="text-button" onClick={onClear}>
          {s.clearSearches}
        </button>
      </div>
      <ul className="chat-list">
        {items.map((name) => (
          <li key={name}>
            <button
              type="button"
              className="chat-list__item"
              style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}
              onClick={() => onPick(name)}
            >
              <span className="soft" style={{ display: 'flex' }}>
                <HistoryIcon small />
              </span>
              <span className="chat-list__title" dir="auto">
                {name}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** What the client chose, as the two search requests take it. The days of use and the
 * pickup day are asked when a box is reserved, not here (BLD-D42). */
function useChoiceBody() {
  const choices = useSearchChoices()
  return {
    choices,
    body: {
      location: placeBody(choices.place),
      days_of_use: null,
      pickup_day: null,
      max_price: choices.maxPriceLbp
        ? { amount: String(choices.maxPriceLbp), currency: 'LBP' as const }
        : null,
      sort: choices.sort,
      on_foot: false,
      open_now: choices.openNow,
    },
    key: [choices.place, choices.sort, choices.maxPriceLbp, choices.openNow],
  }
}

function placeWords(location: Where): string {
  if (location.source === 'shared') return strings.chat.location.yours
  if (location.source === 'place') return strings.chat.location.savedPlace
  if (location.source === 'profile' && location.label) return strings.chat.location.home(location.label)
  return location.label ?? strings.chat.location.button(null)
}

/** Every medicine in stock that a typed name stands for, with its best boxes. */
function ByName({
  typed,
  onRetype,
  onOpen,
  onChoose,
}: {
  typed: string
  onRetype: (name: string) => void
  /** A box was opened: the name is worth keeping in the last searches. */
  onOpen: () => void
  onChoose: (productId: string) => void
}) {
  const navigate = useNavigate()
  const { body, key } = useChoiceBody()
  const wide = useWide()
  const result = useQuery({
    queryKey: ['by-name', typed, ...key],
    queryFn: () =>
      unwrap(api.POST('/api/v1/listings/search-by-name', { body: { q: typed, ...body, per_medicine: 3 } })),
    placeholderData: (before) => before,
    retry: false,
  })

  if (result.isError) {
    const code = result.error instanceof ApiFailure ? result.error.code : 'INTERNAL_ERROR'
    return (
      <Banner tone="red" alert>
        {errorMessage(code)}
      </Banner>
    )
  }
  if (!result.data) return <p className="soft">{strings.common.loading}</p>

  const found = result.data
  const ask = () => navigate('/assistant', { state: { draft: s.askDraft(typed) } })
  const suggestions = found.did_you_mean.length > 0 && (
    <div className="chips" role="group" aria-label={s.didYouMean}>
      <span className="hint" style={{ alignSelf: 'center' }}>
        {s.didYouMean}
      </span>
      {found.did_you_mean.map((name) => (
        <button key={name} type="button" className="chip" onClick={() => onRetype(name)}>
          {name}
        </button>
      ))}
    </div>
  )

  return (
    <div className={wide ? 'cols cols--side' : 'cols'}>
      <Filters location={found.location} />
      <div className="stack" role="status" aria-live="polite">
        {found.closest && found.groups.length > 0 && <Banner tone="amber">{s.closest(typed)}</Banner>}
        {suggestions}
        {found.groups.length === 0 && (
          <div className="empty">
            <span style={{ fontWeight: 600 }}>{s.nothingInStock(typed)}</span>
            <span className="soft" style={{ fontSize: 15 }}>
              {s.askToFindHint}
            </span>
            <button type="button" className="pill-button" style={{ alignSelf: 'flex-start' }} onClick={ask}>
              <ChatIcon small />
              {s.askToFind}
            </button>
          </div>
        )}
        {found.groups.map((group) => (
          <section key={group.product.id} className="medicine-group" aria-label={group.product.name}>
            <div className="medicine-group__head">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <h2 className="medicine-group__name">{group.product.name}</h2>
                <span className="soft" style={{ fontSize: 15 }}>
                  {[group.product.strength, group.product.form, group.product.pack].filter(Boolean).join(' · ')}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {group.by_ingredient && <span className="status-pill status-pill--grey">{s.contains}</span>}
                {group.product.prescription_required && (
                  <span className="status-pill status-pill--grey">
                    <PrescriptionIcon small />
                    {s.prescription}
                  </span>
                )}
              </div>
            </div>
            <div className="medicine-group__rows stack" style={{ gap: 10 }}>
              {group.items.map((listing) => (
                <ListingRow key={listing.id} listing={listing} onOpen={onOpen} />
              ))}
            </div>
            {group.items.length === 0 && (
              <span className="soft" style={{ fontSize: 15 }}>
                {s.noneForChoices}
              </span>
            )}
            {group.total_found > group.items.length && (
              <button
                type="button"
                className="text-button"
                style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}
                onClick={() => onChoose(group.product.id)}
              >
                {s.seeAll(group.total_found)}
              </button>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}

/** One box at one pharmacy, as a row that opens its page (docs/11 §4). */
function ListingRow({ listing, onOpen }: { listing: Listing; onOpen?: () => void }) {
  return (
    <Link to={`/listings/${listing.id}`} className="search-row" onClick={onOpen}>
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
          {s.expires(calendarDate(listing.expiry_date))} · {s.left(listing.available, listing.more_available)}
        </span>
      </span>
      <PriceBlock price={listing.price} saving={listing.saving} />
    </Link>
  )
}

/**
 * The filters of a search, as on any shop's search (the owner, 2026-11-18, BLD-D42): the
 * order, a price limit, only pharmacies open now, and where the client is. **The days of
 * use and the pickup day are not asked here:** they are asked when a box is reserved,
 * where the page says whether the box lasts.
 *
 * On a computer they stand beside the results. On a phone they are folded behind one
 * button, so that the results are what the first screen shows.
 */
function Filters({ location, children }: { location: Where; children?: ReactNode }) {
  const choices = useSearchChoices()
  const wide = useWide()
  const [unfolded, setUnfolded] = useState(false)
  const [choosingPlace, setChoosingPlace] = useState(false)
  const shown = wide || unfolded
  return (
    <section className="filters" aria-label={s.filters}>
      {children}
      {!wide && (
        <button
          type="button"
          className="filters__fold"
          aria-expanded={unfolded}
          onClick={() => setUnfolded(!unfolded)}
        >
          <span style={{ fontWeight: 600 }}>{s.filters}</span>
          <span className="hint">
            {[
              s.sorts[choices.sort],
              choices.maxPriceLbp ? s.upTo(choices.maxPriceLbp.toLocaleString('en')) : null,
              choices.openNow ? s.openNow : null,
              placeWords(location),
            ]
              .filter(Boolean)
              .join(' · ')}
          </span>
        </button>
      )}
      {shown && (
        <>
          {wide && <span style={{ fontWeight: 600 }}>{s.filters}</span>}
          <NativeSelect
            label={s.sort}
            size="md"
            value={choices.sort}
            onChange={(event) => choices.set({ sort: event.currentTarget.value as typeof choices.sort })}
            data={Object.entries(s.sorts).map(([value, label]) => ({ value, label }))}
          />
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 15, fontWeight: 500 }}>
            {s.maxPrice}
            <input
              className="quantity-input quantity-input--wide"
              style={{ width: '100%' }}
              type="text"
              inputMode="numeric"
              value={choices.maxPriceLbp ?? ''}
              onChange={(event) => {
                const digits = event.currentTarget.value.replace(/\D/g, '')
                choices.set({ maxPriceLbp: digits ? Number(digits) : null })
              }}
            />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 44 }}>
            <input
              type="checkbox"
              checked={choices.openNow}
              onChange={(event) => choices.set({ openNow: event.currentTarget.checked })}
            />
            {s.openNow}
          </label>
          <button type="button" className="chat__location" onClick={() => setChoosingPlace(true)}>
            <PinIcon small />
            {s.near}: {placeWords(location)}
          </button>
        </>
      )}

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
    </section>
  )
}

/** One medicine and every pharmacy that has it. */
function OneMedicine({ productId }: { productId: string }) {
  const navigate = useNavigate()
  const { body, key } = useChoiceBody()
  const wide = useWide()
  const [limit, setLimit] = useState(PAGE)
  const result = useQuery({
    queryKey: ['listings', productId, ...key, limit],
    queryFn: () =>
      unwrap(api.POST('/api/v1/listings/search', { body: { product_id: productId, ...body, cursor: 0, limit } })),
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

  const { product, items, location } = result.data
  const askToFind = () => navigate('/assistant', { state: { draft: s.askDraft(product.name) } })

  return (
    <div className={wide ? 'cols cols--side' : 'cols'}>
      <Filters location={location}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
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
        </div>
      </Filters>

      <div className="stack" role="status" aria-live="polite" style={{ gap: 12 }}>
        {items.length > 0 && (
          <span className="soft" style={{ fontSize: 15 }}>
            {s.found(result.data.total_found)}
          </span>
        )}

        {items.map((listing) => (
          <ListingRow key={listing.id} listing={listing} />
        ))}

        {items.length === 0 && (
          <div className="empty">
            <span style={{ fontWeight: 600 }}>{s.empty(product.name)}</span>
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
    </div>
  )
}
