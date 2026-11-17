import { type FormEvent, type ReactNode, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'

import type { Schemas } from '../../api/client'
import { useSession } from '../../api/session'
import { Banner } from '../../components/layout'
import { clock, dayAndClock } from '../../format'
import { strings } from '../../strings/en'
import { UnverifiedBanner } from '../client/HomePage'
import { NotificationsList } from '../client/NotificationsPage'
import { AskCard } from './AskCard'
import {
  useAsks,
  useDashboard,
  usePharmacy,
  usePharmacyReservations,
  useReservationByNumber,
} from './data'
import { InventoryPage } from './InventoryPage'
import { ListingsPage } from './ListingsPage'
import { RegistrationPanel, SettingsPage } from './ProfilePages'
import { ReservationCard } from './ReservationCard'

const s = strings.pharmacy

type Profile = Schemas['PharmacyProfile']

/**
 * The pharmacy's portal (docs/11 §3.2): a top bar of pill tabs, desktop first, and every
 * page works on a phone. Its code is loaded only for a pharmacist: a client's phone
 * never downloads it (docs/11 §10).
 */
export default function PharmacyPortal() {
  const profile = usePharmacy()
  if (!profile.data) {
    return (
      <main className="screen screen--plain">
        <p className="soft">{strings.common.loading}</p>
      </main>
    )
  }
  const pharmacy = profile.data
  // Approved: everything. Suspended: only the reservations it still holds (docs/06 §2.2).
  const approved = pharmacy.status === 'APPROVED'
  const works = approved || pharmacy.status === 'SUSPENDED'
  return (
    <div className="portal">
      <Bar pharmacy={pharmacy} works={works} approved={approved} />
      <div className="portal__body">
        {/* Until the email is confirmed, the registration hasn't reached our team (R-AU7). */}
        {!pharmacy.email_verified && <UnverifiedBanner text={s.confirmEmail} />}
        {pharmacy.status === 'PENDING' && pharmacy.email_verified && (
          <Banner tone={pharmacy.info_requested ? 'amber' : 'grey'}>
            {pharmacy.info_requested ? s.infoRequested(pharmacy.status_reason) : s.pending}
          </Banner>
        )}
        {pharmacy.status === 'REJECTED' && (
          <Banner tone="red">{s.rejected(pharmacy.status_reason)}</Banner>
        )}
        {pharmacy.status === 'SUSPENDED' && <Banner tone="amber">{s.suspended}</Banner>}
        {works ? (
          <Routes>
            <Route index element={<TodayPage pharmacy={pharmacy} />} />
            <Route path="reservations" element={<ReservationsPage />} />
            {approved && <Route path="inventory" element={<InventoryPage />} />}
            {approved && <Route path="listings" element={<ListingsPage />} />}
            <Route path="settings" element={<SettingsPage pharmacy={pharmacy} />} />
            <Route
              path="notifications"
              element={
                <main className="portal__main">
                  <NotificationsList />
                </main>
              }
            />
          </Routes>
        ) : (
          // Waiting, or rejected: the pharmacy corrects what it typed (PS-2).
          <RegistrationPanel pharmacy={pharmacy} />
        )}
      </div>
    </div>
  )
}

function Bar({
  pharmacy,
  works,
  approved,
}: {
  pharmacy: Profile
  works: boolean
  approved: boolean
}) {
  const { logout } = useSession()
  // The end of the range that is open now: a pharmacy may close at midday and reopen.
  const closes = pharmacy.closes_at ? deadlineClock(pharmacy.closes_at) : ''
  return (
    <header className="bar">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="brand__mark" aria-hidden="true">
          D
        </span>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>{pharmacy.name}</span>
          <span style={{ fontSize: 13, color: pharmacy.status === 'APPROVED' ? 'var(--green)' : 'var(--amber)' }}>
            {pharmacy.email_verified ? s.status[pharmacy.status] : s.notConfirmed}
            {pharmacy.status === 'APPROVED' && ` · ${pharmacy.open_now ? s.open(closes) : s.closed}`}
          </span>
        </div>
      </div>
      <nav className="bar__tabs" aria-label={s.nav}>
        {works && (
          <>
            <NavLink to="/pharmacy" end className="bar__tab">
              {s.today}
            </NavLink>
            <NavLink to="/pharmacy/reservations" className="bar__tab">
              {s.reservations}
            </NavLink>
            {approved && (
              <>
                <NavLink to="/pharmacy/inventory" className="bar__tab">
                  {s.inventory}
                </NavLink>
                <NavLink to="/pharmacy/listings" className="bar__tab">
                  {s.listings}
                </NavLink>
              </>
            )}
            <NavLink to="/pharmacy/notifications" className="bar__tab">
              {strings.notifications.title}
            </NavLink>
            <NavLink to="/pharmacy/settings" className="bar__tab">
              {s.settings}
            </NavLink>
          </>
        )}
        <button type="button" className="bar__tab" onClick={() => void logout()}>
          {s.logOut}
        </button>
      </nav>
    </header>
  )
}

/** PS-3: Today, built around the counter. What needs the pharmacist comes first. */
function TodayPage({ pharmacy }: { pharmacy: Profile }) {
  const [typed, setTyped] = useState('')
  const [asked, setAsked] = useState('')
  const found = useReservationByNumber(asked)
  const active = usePharmacyReservations('active')
  const approved = pharmacy.status === 'APPROVED'
  const numbers = useDashboard(true)
  const asks = useAsks(approved)
  const now = active.data?.server_now ?? pharmacy.server_now
  const isToday = (item: Schemas['PharmacyReservation']) =>
    Boolean(item.deadline && dayAndClock(item.deadline, now).startsWith(strings.common.today))
  const dueToday = (active.data?.items ?? []).filter(isToday)
  // Reserved for a later day: the box must be put aside now all the same (PS-3).
  const later = (active.data?.items ?? []).filter((item) => !isToday(item))

  function find(event: FormEvent) {
    event.preventDefault()
    setAsked(typed.trim())
  }

  return (
    <div className="portal__columns">
      <main className="portal__main">
        {numbers.data?.stale && approved && <Banner tone="amber">{s.stale}</Banner>}
        <section className="panel" aria-labelledby="counter">
          <div>
            <h1 id="counter" className="page-title">
              {s.counter}
            </h1>
            <span className="soft">{s.counterHint}</span>
          </div>
          <form onSubmit={find} style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
            <label htmlFor="order-number" className="sr-only">
              {s.orderNumber}
            </label>
            <input
              id="order-number"
              className="counter-input"
              type="text"
              autoComplete="off"
              autoCapitalize="characters"
              placeholder="R-"
              value={typed}
              onChange={(event) => setTyped(event.currentTarget.value.toUpperCase())}
            />
            <button type="submit" className="pill-button counter-find" disabled={!typed.trim()}>
              {s.find}
            </button>
          </form>
          <div role="status" aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {found.data?.items.map((reservation) => (
              <ReservationCard key={reservation.id} reservation={reservation} />
            ))}
            {asked && found.isSuccess && found.data.items.length === 0 && (
              <Banner tone="amber">{s.noSuchNumber(asked)}</Banner>
            )}
          </div>
        </section>

        <section className="panel" aria-labelledby="due">
          <h2 id="due" className="panel__title">
            {s.dueToday}
          </h2>
          {active.isSuccess && dueToday.length === 0 && <span className="soft">{s.nothingDue}</span>}
          {dueToday.map((item) => (
            <button
              key={item.id}
              type="button"
              className="due-row"
              onClick={() => {
                setTyped(item.ref)
                setAsked(item.ref)
              }}
            >
              {item.is_new && <span className="due-row__new">{s.isNew}</span>}
              <span className="order-ref">{item.ref}</span>
              <span style={{ flex: 1, textAlign: 'start' }}>
                {item.product.name} × {item.qty}
                {item.product.prescription_required && ` · ${s.prescriptionShort}`}
              </span>
              {item.deadline && <span className="soft">{s.by(deadlineClock(item.deadline))}</span>}
            </button>
          ))}
        </section>

        {later.length > 0 && (
          <section className="panel" aria-labelledby="later">
            <h2 id="later" className="panel__title">
              {s.comingNext}
            </h2>
            {later.map((item) => (
              <button
                key={item.id}
                type="button"
                className="due-row"
                onClick={() => {
                  setTyped(item.ref)
                  setAsked(item.ref)
                }}
              >
                {item.is_new && <span className="due-row__new">{s.isNew}</span>}
                <span className="order-ref">{item.ref}</span>
                <span style={{ flex: 1, textAlign: 'start' }}>
                  {item.product.name} × {item.qty}
                </span>
                {item.deadline && <span className="soft">{s.by(dayAndClock(item.deadline, now))}</span>}
              </button>
            ))}
          </section>
        )}
      </main>

      <aside className="portal__aside">
        {(asks.data?.items ?? []).map((ask) => (
          <AskCard key={ask.id} ask={ask} now={asks.data?.server_now ?? now} />
        ))}
        {numbers.data && (
          <section className="panel" aria-label={s.numbers}>
            <h2 className="panel__title">{s.numbers}</h2>
            <dl className="card__lines">
              <Number label={s.newReservations} value={numbers.data.new_reservations} />
              <Number label={s.dueToday} value={numbers.data.due_today} />
              <Number label={s.unitsReserved} value={numbers.data.units_reserved} />
              <Number label={s.liveListings} value={numbers.data.live_listings} />
            </dl>
          </section>
        )}
      </aside>
    </div>
  )
}

function deadlineClock(deadline: string): string {
  const at = clock(deadline)
  return at === '00:00' ? '24:00' : at
}

function Number({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="card__line">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

/** PS-4: every reservation, waiting or over. */
function ReservationsPage() {
  const [view, setView] = useState<'active' | 'history'>('active')
  const found = usePharmacyReservations(view)
  const items = found.data?.items ?? []
  return (
    <main className="portal__main">
      <h1 className="page-title">{s.reservations}</h1>
      <div className="tabs" role="tablist" aria-label={s.reservations}>
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
      {found.isSuccess && items.length === 0 && (
        <span className="soft">{view === 'active' ? s.nothingActive : s.nothingBefore}</span>
      )}
      {items.map((reservation) => (
        <ReservationCard key={reservation.id} reservation={reservation} />
      ))}
    </main>
  )
}
