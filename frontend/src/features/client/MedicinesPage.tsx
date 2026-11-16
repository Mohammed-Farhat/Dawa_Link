import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { Schemas } from '../../api/client'
import { useSession } from '../../api/session'
import { Screen } from '../../components/layout'
import { lbp } from '../../format'
import { strings } from '../../strings/en'
import { useReservations } from './data'

const s = strings.medicines

const TONE: Record<Schemas['Reservation']['state'], string> = {
  RESERVED: 'green',
  PICKED_UP: 'green',
  NOT_AVAILABLE: 'red',
  EXPIRED_NO_SHOW: 'red',
  CANCELLED_BY_CLIENT: 'grey',
  CANCELLED_BY_SYSTEM: 'grey',
}

/** "My medicines": one card per medicine (docs/11 §3.1). Requests and watches join the
 * same list when their screens are built. */
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

/** CS-13, the first part: who is logged in, and logging out. */
export function MePage() {
  const m = strings.me
  const { me, logout } = useSession()
  return (
    <Screen>
      <h1 className="page-title">{m.title}</h1>
      {me && (
        <div className="row-card">
          <span style={{ fontSize: 18, fontWeight: 600 }}>{me.full_name}</span>
          <span className="soft">{me.email}</span>
          {me.client?.district && (
            <span className="soft">
              {m.homeDistrict}: {me.client.district.name}
            </span>
          )}
          {me.client && (
            <span className="soft">
              {m.missedPickups(me.client.missed_pickups_30d, me.client.missed_pickups_before_pause)}
            </span>
          )}
        </div>
      )}
      <button type="button" className="pill-button pill-button--grey" onClick={() => void logout()}>
        {m.logOut}
      </button>
    </Screen>
  )
}
