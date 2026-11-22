import { useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { Banner, Screen } from '../../components/layout'
import { reservationTone } from '../../components/reservationTone'
import { Placeholder } from '../../components/Placeholder'
import { dayClockInSentence, lbp, reservationWords } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { useReservations, useWatches } from './data'

const s = strings.medicines

const TABS = ['active', 'history'] as const
type Tab = (typeof TABS)[number]

/** One medicine DawaLink watches for, with [Stop watching]. */
function WatchCard({ watch, now }: { watch: Schemas['Watch']; now: string }) {
  const queryClient = useQueryClient()
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  // An offer waits for the client's tap: amber, "your tap is needed" (docs/11 §2.1, B#17).
  const offered = watch.state === 'OFFER_PENDING'

  async function stop() {
    setSending(true)
    setFailed(null)
    try {
      await unwrap(api.POST('/api/v1/watches/{watch_id}/cancel', { params: { path: { watch_id: watch.id } } }))
      await queryClient.invalidateQueries({ queryKey: ['watches'] })
    } catch (error) {
      // The row stays, and says why (A#41).
      setFailed(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
    } finally {
      setSending(false)
    }
  }

  return (
    <article className="row-card">
      <div className="row-card__top">
        <span style={{ fontSize: 17, fontWeight: 600 }}>
          {watch.product.name} × {watch.qty}
        </span>
        <span className={`status-pill status-pill--${offered ? 'amber' : 'blue'}`}>
          {offered ? s.watchOffer : s.watchingTitle}
        </span>
      </div>
      <span className="soft" style={{ fontSize: 14 }}>
        {s.watchUntil(dayClockInSentence(watch.ends_at, now), watch.district)}
        {watch.max_price && ` · ${s.watchMax(lbp(watch.max_price.lbp))}`}
      </span>
      {failed && (
        <Banner tone="red" alert>
          {errorMessage(failed)}
        </Banner>
      )}
      {offered ? (
        <Link to="/" className="pill-button">
          {s.seeOffer}
        </Link>
      ) : (
        <button
          type="button"
          className="text-button"
          style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}
          aria-label={s.stopWatchingFor(watch.product.name)}
          disabled={sending}
          onClick={() => void stop()}
        >
          {s.stopWatching}
        </button>
      )}
    </article>
  )
}

/** CS-11: what DawaLink watches for, with [Stop watching]. A watch that got an offer
 * says so: the offer's card is on Home. */
function Watching() {
  const watches = useWatches()
  const items = watches.data?.items ?? []
  if (!watches.data || items.length === 0) return null
  return (
    <section aria-label={s.watchingTitle} className="cols cols--cards">
      {items.map((watch) => (
        <WatchCard key={watch.id} watch={watch} now={watches.data.server_now} />
      ))}
    </section>
  )
}

/** "My medicines": one card per medicine (docs/11 §3.1), the watches first. */
export function MedicinesPage() {
  const [view, setView] = useState<Tab>('active')
  const found = useReservations(view)
  const items = found.data?.items ?? []

  // The tab pattern's keys: the arrows move between the two tabs (WAI-ARIA tabs).
  function onKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const next = TABS[(TABS.indexOf(view) + 1) % TABS.length]
    setView(next)
    document.getElementById(`medicines-tab-${next}`)?.focus()
  }

  return (
    <Screen>
      <h1 className="page-title">{s.title}</h1>
      <div className="tabs" role="tablist" aria-label={s.title}>
        {TABS.map((tab) => (
          <button
            key={tab}
            id={`medicines-tab-${tab}`}
            type="button"
            role="tab"
            aria-selected={view === tab}
            aria-controls="medicines-panel"
            tabIndex={view === tab ? 0 : -1}
            className="tabs__tab"
            onClick={() => setView(tab)}
            onKeyDown={onKey}
          >
            {s[tab]}
          </button>
        ))}
      </div>

      <div id="medicines-panel" role="tabpanel" aria-labelledby={`medicines-tab-${view}`} className="stack">
        {view === 'active' && <Watching />}
        {found.isPending && <Placeholder />}
        {found.isSuccess && items.length === 0 && (
          <div className="empty">
            <span className="soft">{view === 'active' ? s.nothingActive : s.nothingBefore}</span>
            {/* Nothing to pick up: the ways to find something, as on Home. */}
            {view === 'active' && (
              <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                <Link to="/search" className="text-button" style={{ paddingInlineStart: 0 }}>
                  {strings.home.goSearch}
                </Link>
                <Link to="/assistant" className="text-button">
                  {strings.home.goAsk}
                </Link>
              </span>
            )}
          </div>
        )}
        <div className="cols cols--cards">
          {items.map((item) => (
            <article key={item.id} className="row-card">
              <div className="row-card__top">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: 17, fontWeight: 600 }}>
                    {item.product.name} × {item.qty}
                  </span>
                  <span className="soft" style={{ fontSize: 14 }}>
                    {item.pharmacy.name}, {item.pharmacy.district} · {lbp(item.total.lbp)}
                  </span>
                </div>
                <span className="order-ref hint">{item.ref}</span>
              </div>
              <span className={`status-pill status-pill--${reservationTone(item.state)}`}>{reservationWords(item)}</span>
              {item.state === 'RESERVED' ? (
                <Link to={`/reservations/${item.id}`} className="pill-button" aria-label={s.showTicketFor(item.ref)}>
                  {s.showTicket}
                </Link>
              ) : (
                <Link
                  to={`/reservations/${item.id}`}
                  className="text-button"
                  style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}
                  aria-label={`${s.details}: ${item.ref}`}
                >
                  {s.details}
                </Link>
              )}
            </article>
          ))}
        </div>
      </div>
    </Screen>
  )
}
