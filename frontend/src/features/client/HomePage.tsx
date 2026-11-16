import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiFailure, unwrap } from '../../api/client'
import { useSession } from '../../api/session'
import { ChatIcon, SearchIcon, TicketIcon } from '../../components/icons'
import { Banner, Screen } from '../../components/layout'
import { beirutHour, dayAndClock } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { useOffers, useRequests, useReservations } from './data'
import { OfferCard } from './requests/OfferCard'

const s = strings.home

/** "Confirm your email", with [Send the link again] (docs/11 §4, Banner). */
export function UnverifiedBanner() {
  const b = strings.banner
  const [state, setState] = useState<'idle' | 'sent' | string>('idle')

  async function resend() {
    try {
      await unwrap(api.POST('/api/v1/auth/verify-email/resend'))
      setState('sent')
    } catch (error) {
      setState(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
    }
  }

  if (state === 'sent') return <Banner tone="green">{b.resent}</Banner>
  return (
    <Banner
      tone="grey"
      action={
        <button type="button" className="text-button" onClick={resend}>
          {b.resend}
        </button>
      }
    >
      {state === 'idle' ? b.unverified : errorMessage(state)}
    </Banner>
  )
}

/** CS-5: Home. What is due comes first, then the way to the assistant (docs/11 §3.1). */
export function HomePage() {
  const { me } = useSession()
  const active = useReservations('active')
  const reservations = active.data?.items ?? []
  const next = reservations[0]
  const [opened] = useState(() => new Date().toISOString())
  // The server's clock when it answers: the demo clock may be ahead of this device's.
  const now = active.data?.server_now ?? opened
  const client = me?.client
  const verified = Boolean(me?.email_verified)
  const offers = useOffers()
  const requests = useRequests('open')

  return (
    <Screen>
      <header style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span className="soft" style={{ fontSize: 15 }}>
          {s.greeting(beirutHour())}
        </span>
        <h1 className="page-title">{s.title}</h1>
      </header>

      {me && !me.email_verified && <UnverifiedBanner />}
      {client?.status === 'PAUSED' && client.paused_until && (
        <Banner tone="amber">{strings.banner.paused(dayAndClock(client.paused_until, now))}</Banner>
      )}

      {next && next.deadline && (
        <section className="today" aria-label={s.pickUp}>
          <div className="today__top">
            <span className="today__label">{s.pickUp}</span>
            <span className="order-ref today__ref">{next.ref}</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span className="today__when">{s.pickUpBy(dayAndClock(next.deadline, now))}</span>
            <span className="today__what">
              {next.product.name} ×{next.qty} · {next.pharmacy.name}, {next.pharmacy.district}
            </span>
          </div>
          <Link to={`/reservations/${next.id}`} className="pill-button pill-button--white">
            <TicketIcon small />
            {s.showAtCounter}
          </Link>
          {reservations.length > 1 && (
            <Link to="/medicines" className="text-button" style={{ color: 'var(--ink-on-dark)' }}>
              {s.moreReservations(reservations.length - 1)}
            </Link>
          )}
        </section>
      )}

      {/* What needs the client's tap comes before everything else (docs/11 §1). */}
      {verified &&
        (offers.data?.items ?? []).map((offer) => (
          <OfferCard key={offer.id} offer={offer} now={offers.data?.server_now ?? now} />
        ))}

      <Link to="/search" className="search-pill">
        <span style={{ color: 'var(--blue)', display: 'flex' }}>
          <SearchIcon />
        </span>
        {strings.search.homePill}
      </Link>

      <Link to="/assistant" className="tile">
        <span className="tile__icon">
          <ChatIcon />
        </span>
        <span style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span className="tile__title">{s.askTitle}</span>
          <span className="tile__hint">{s.askHint}</span>
        </span>
      </Link>

      {(requests.data?.items ?? []).map((request) => (
        <Link key={request.id} to={`/requests/${request.id}`} className="tile tile--blue">
          <span style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span className="tile__title">
              {strings.request.homeLine(request.ref, request.units_secured, request.units_wanted)}
            </span>
            <span className="tile__hint">
              {strings.request.searchingUntil(dayAndClock(request.ends_at, request.server_now))}
            </span>
          </span>
        </Link>
      ))}

      {active.isSuccess && !next && (requests.data?.items.length ?? 0) === 0 && (
        <div className="empty">
          <span style={{ fontWeight: 600 }}>{s.nothingReserved}</span>
          <span className="soft" style={{ fontSize: 15 }}>
            {s.nothingReservedHint}
          </span>
        </div>
      )}
    </Screen>
  )
}
