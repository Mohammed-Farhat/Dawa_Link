import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, type Schemas } from '../../api/client'
import { Screen } from '../../components/layout'
import { clock, lbp } from '../../format'
import { strings } from '../../strings/en'
import { useReservations, useWatches } from './data'

const s = strings.medicines

const TONE: Record<Schemas['Reservation']['state'], string> = {
  RESERVED: 'green',
  PICKED_UP: 'green',
  NOT_AVAILABLE: 'red',
  EXPIRED_NO_SHOW: 'red',
  CANCELLED_BY_CLIENT: 'grey',
  CANCELLED_BY_SYSTEM: 'grey',
}

/** CS-11: what DawaLink watches for, with [Stop watching]. A watch that got an offer
 * says so: the offer's card is on Home. */
function Watching() {
  const queryClient = useQueryClient()
  const watches = useWatches()
  const items = watches.data?.items ?? []
  if (items.length === 0) return null

  async function stop(id: string) {
    await api.POST('/api/v1/watches/{watch_id}/cancel', { params: { path: { watch_id: id } } })
    await queryClient.invalidateQueries({ queryKey: ['watches'] })
  }

  return (
    <section aria-label={s.watchingTitle} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {items.map((watch) => (
        <article key={watch.id} className="row-card">
          <div className="row-card__top">
            <span style={{ fontSize: 17, fontWeight: 600 }}>
              {watch.product.name} × {watch.qty}
            </span>
            <span className={`status-pill status-pill--${watch.state === 'OFFER_PENDING' ? 'green' : 'blue'}`}>
              {watch.state === 'OFFER_PENDING' ? s.watchOffer : s.watchingTitle}
            </span>
          </div>
          <span className="soft" style={{ fontSize: 14 }}>
            {s.watchUntil(clock(watch.ends_at), watch.district)}
            {watch.max_price && ` · ${s.watchMax(lbp(watch.max_price.lbp))}`}
          </span>
          {watch.state === 'OFFER_PENDING' ? (
            <Link to="/" className="pill-button">
              {s.seeOffer}
            </Link>
          ) : (
            <button
              type="button"
              className="text-button"
              style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}
              onClick={() => void stop(watch.id)}
            >
              {s.stopWatching}
            </button>
          )}
        </article>
      ))}
    </section>
  )
}

/** "My medicines": one card per medicine (docs/11 §3.1), the watches first. */
export function MedicinesPage() {
  const [view, setView] = useState<'active' | 'history'>('active')
  const found = useReservations(view)
  const items = found.data?.items ?? []

  return (
    <Screen>
      <h1 className="page-title">{s.title}</h1>
      <div className="tabs" role="tablist" aria-label={s.title}>
        {(['active', 'history'] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={view === tab}
            className="tabs__tab"
            onClick={() => setView(tab)}
          >
            {s[tab]}
          </button>
        ))}
      </div>

      {view === 'active' && <Watching />}
      {found.isPending && <p className="soft">{strings.common.loading}</p>}
      {found.isSuccess && items.length === 0 && (
        <div className="empty">
          <span className="soft">{view === 'active' ? s.nothingActive : s.nothingBefore}</span>
        </div>
      )}
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
          <span className={`status-pill status-pill--${TONE[item.state]}`}>{item.status_text}</span>
          {item.state === 'RESERVED' && (
            <Link to={`/reservations/${item.id}`} className="pill-button">
              {s.showTicket}
            </Link>
          )}
        </article>
      ))}
    </Screen>
  )
}
