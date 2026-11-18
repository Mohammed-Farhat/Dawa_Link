import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiFailure, unwrap } from '../../api/client'
import { useSession } from '../../api/session'
import { TicketIcon } from '../../components/icons'
import { Banner, Screen } from '../../components/layout'
import { beirutHour, clock, dayAndClock } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { useOffers, useRequests, useReservations, useWatches } from './data'
import { OfferCard } from './requests/OfferCard'

const s = strings.home

/** "Confirm your email", with [Send the link again] (docs/11 §4, Banner). */
export function UnverifiedBanner({ text }: { text?: string }) {
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
      {state === 'idle' ? (text ?? b.unverified) : errorMessage(state)}
    </Banner>
  )
}

/**
 * CS-5: Home is what needs the client now (the owner, 2026-11-18, BLD-D42): the
 * reservations to pick up, with their deadline; the offers waiting for a tap; the open
 * requests with their progress; what DawaLink watches for. Searching and asking have
 * their own entries in the menu, so Home has no search box.
 */
export function HomePage() {
  const { me } = useSession()
  const active = useReservations('active')
  const reservations = active.data?.items ?? []
  const [next, ...others] = reservations
  const [opened] = useState(() => new Date().toISOString())
  // The server's clock when it answers: the demo clock may be ahead of this device's.
  const now = active.data?.server_now ?? opened
  const client = me?.client
  const verified = Boolean(me?.email_verified)
  const offers = useOffers()
  const requests = useRequests('open')
  const watches = useWatches()
  const open = requests.data?.items ?? []
  const watched = watches.data?.items ?? []
  // Said only when every list has answered: never for the moment a list is still loading.
  const nothing =
    active.isSuccess &&
    !requests.isPending &&
    !watches.isPending &&
    reservations.length === 0 &&
    open.length === 0 &&
    watched.length === 0

  return (
    <Screen>
      <header className="page-head">
        <span className="soft" style={{ fontSize: 15 }}>
          {s.greeting(beirutHour())}
          {client?.first_name ? `, ${client.first_name}` : ''}
        </span>
        <h1 className="page-title">{s.title}</h1>
      </header>

      {me && !me.email_verified && <UnverifiedBanner />}
      {client?.status === 'PAUSED' && client.paused_until && (
        <Banner tone="amber">{strings.banner.paused(dayAndClock(client.paused_until, now))}</Banner>
      )}

      <div className="cols cols--cards">
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
          </section>
        )}
        {others.map((order) => (
          <Link key={order.id} to={`/reservations/${order.id}`} className="tile">
            <span className="tile__icon">
              <TicketIcon />
            </span>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span className="tile__title">
                {order.product.name} ×{order.qty}
              </span>
              <span className="tile__hint">
                {order.deadline ? s.pickUpBy(dayAndClock(order.deadline, now)) : order.status_text} ·{' '}
                {order.pharmacy.name}
              </span>
            </span>
          </Link>
        ))}

        {/* What needs the client's tap comes before everything else (docs/11 §1). */}
        {verified &&
          (offers.data?.items ?? []).map((offer) => (
            <OfferCard key={offer.id} offer={offer} now={offers.data?.server_now ?? now} />
          ))}

        {open.map((request) => (
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

        {watched.map((watch) => (
          <Link key={watch.id} to="/medicines" className="tile">
            <span style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span className="tile__title">
                {watch.product.name} ×{watch.qty}
              </span>
              <span className="tile__hint">
                {watch.state === 'OFFER_PENDING'
                  ? strings.medicines.watchOffer
                  : strings.medicines.watchUntil(clock(watch.ends_at), watch.district)}
              </span>
            </span>
          </Link>
        ))}

        {nothing && (
          <div className="empty">
            <span style={{ fontWeight: 600 }}>{s.nothingReserved}</span>
            <span className="soft" style={{ fontSize: 15 }}>
              {s.nothingReservedHint}
            </span>
            <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              <Link to="/search" className="text-button" style={{ paddingInlineStart: 0 }}>
                {s.goSearch}
              </Link>
              <Link to="/assistant" className="text-button">
                {s.goAsk}
              </Link>
            </span>
          </div>
        )}
      </div>
    </Screen>
  )
}
