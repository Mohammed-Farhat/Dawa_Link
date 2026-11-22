import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { NavLink, Route, Routes, useSearchParams } from 'react-router-dom'

import { ApiFailure, type Schemas } from '../../api/client'
import { useSession } from '../../api/session'
import { NotFoundPage } from '../../app/NotFoundPage'
import { Banner } from '../../components/layout'
import { Placeholder } from '../../components/Placeholder'
import { clock, dayAndClock } from '../../format'
import { errorMessage, strings } from '../../strings/en'
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
import { type CardNotice, noticeFor } from './notice'
import { RegistrationPanel, SettingsPage } from './ProfilePages'
import { ReservationCard } from './ReservationCard'

const s = strings.pharmacy

type Profile = Schemas['PharmacyProfile']

// One meaning per colour (docs/11 §2): approved is done, waiting needs a step, a
// rejected or suspended pharmacy is stopped.
const STATUS_COLOUR: Record<string, string> = {
  APPROVED: 'var(--green)',
  PENDING: 'var(--amber)',
  REJECTED: 'var(--red)',
  SUSPENDED: 'var(--red)',
}

/** The order number's longest form the API reads (`GET /pharmacy/reservations?q=`). */
const ORDER_NUMBER_MAX = 20

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
        {pharmacy.status === 'SUSPENDED' && <Banner tone="red">{s.suspended}</Banner>}
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
            {/* An address of the portal that isn't a page, or one this pharmacy can't open
                now (the stock of a suspended one): a page that says so, with its main
                area and its heading, as in the admin's console (B#34). */}
            <Route
              path="*"
              element={
                <main className="portal__main">
                  <NotFoundPage />
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
          <span style={{ fontSize: 13 }}>
            <span
              style={{
                color: pharmacy.email_verified
                  ? (STATUS_COLOUR[pharmacy.status] ?? 'var(--amber)')
                  : 'var(--amber)',
              }}
            >
              {pharmacy.email_verified ? s.status[pharmacy.status] : s.notConfirmed}
            </span>
            {/* Open or closed is a fact, not a status: it isn't green. */}
            {pharmacy.status === 'APPROVED' && (
              <span className="soft"> · {pharmacy.open_now ? s.open(closes) : s.closed}</span>
            )}
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
  // Each Find, or tap on a row, counts once: the card it finds gets the focus once,
  // never again when the lists refresh (the focus would jump under the pharmacist).
  const [finds, setFinds] = useState(0)
  const focusedFor = useRef(0)
  const results = useRef<HTMLDivElement>(null)
  const [notice, setNotice] = useState<CardNotice | null>(null)
  const found = useReservationByNumber(asked)
  const active = usePharmacyReservations('active')
  const approved = pharmacy.status === 'APPROVED'
  const numbers = useDashboard(true)
  const asks = useAsks(approved)
  const openAsks = asks.data?.items ?? []
  const now = active.data?.server_now ?? pharmacy.server_now
  const isToday = (item: Schemas['PharmacyReservation']) =>
    Boolean(item.deadline && dayAndClock(item.deadline, now).startsWith(strings.common.today))
  const dueToday = (active.data?.items ?? []).filter(isToday)
  // Reserved for a later day: the box must be put aside now all the same (PS-3).
  const later = (active.data?.items ?? []).filter((item) => !isToday(item))
  const shown = new Set([
    ...openAsks.map((ask) => ask.id),
    ...(found.data?.items ?? []).map((reservation) => reservation.id),
  ])
  // An answered ask leaves its list: what the server said stays on the page.
  const leftOver = notice && !shown.has(notice.key) ? notice : null

  function look(number: string) {
    setTyped(number)
    setAsked(number)
    setFinds((count) => count + 1)
    // The next client: what was said about the last one is over.
    setNotice(null)
  }

  function find(event: FormEvent) {
    event.preventDefault()
    look(typed.trim())
  }

  // The card found appears in the counter panel, which may be far above a row tapped
  // on a phone: it is brought into view and takes the focus, and the keyboard closes.
  useEffect(() => {
    if (finds === focusedFor.current || !found.isSuccess || found.isFetching) return
    focusedFor.current = finds
    const card = results.current?.querySelector<HTMLElement>('.counter-card')
    if (!card) return
    card.scrollIntoView?.({ block: 'nearest' })
    card.focus()
  }, [finds, found.isSuccess, found.isFetching, found.data])

  const lookupFailed =
    asked && found.isError ? (found.error instanceof ApiFailure ? found.error.code : 'INTERNAL_ERROR') : null
  const row = (item: Schemas['PharmacyReservation'], when: string) => (
    <button key={item.id} type="button" className="due-row" onClick={() => look(item.ref)}>
      {item.is_new && <span className="due-row__new">{s.isNew}</span>}
      <span className="order-ref">{item.ref}</span>
      <span style={{ flex: 1, textAlign: 'start' }}>
        {item.product.name} × {item.qty}
        {when === 'today' && item.product.prescription_required && ` · ${s.prescriptionShort}`}
      </span>
      {item.deadline && (
        <span className="soft">
          {s.by(when === 'today' ? deadlineClock(item.deadline) : dayAndClock(item.deadline, now))}
        </span>
      )}
    </button>
  )

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
            {/* A label that stays in sight: "R-" in the box goes as soon as one types
                (docs/11 §9). On a line of its own, above the box and its button. */}
            <label htmlFor="order-number" style={{ flexBasis: '100%', fontWeight: 600 }}>
              {s.orderNumber}
            </label>
            <input
              id="order-number"
              className="counter-input"
              type="text"
              autoComplete="off"
              autoCapitalize="characters"
              placeholder="R-"
              maxLength={ORDER_NUMBER_MAX}
              value={typed}
              // The next client's number replaces the last one without erasing it first.
              onFocus={(event) => event.currentTarget.select()}
              onChange={(event) => setTyped(event.currentTarget.value.toUpperCase())}
            />
            <button type="submit" className="pill-button counter-find" disabled={!typed.trim()}>
              {s.find}
            </button>
          </form>
          <div
            ref={results}
            role="status"
            aria-live="polite"
            style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
          >
            {found.data?.items.map((reservation) => (
              <ReservationCard
                key={reservation.id}
                reservation={reservation}
                notice={noticeFor(notice, reservation.id)}
                onNotice={setNotice}
              />
            ))}
            {asked && found.isSuccess && found.data.items.length === 0 && (
              <Banner tone="amber">{s.noSuchNumber(asked)}</Banner>
            )}
            {lookupFailed && (
              <Banner tone="red" alert>
                {errorMessage(lookupFailed)}
              </Banner>
            )}
          </div>
        </section>

        {/* An ask must be answered within hours: on a phone it comes before what is due
            today, never at the bottom of the page (PS-3: urgent first). */}
        {leftOver && (
          <Banner tone={leftOver.tone} alert={leftOver.tone === 'red'}>
            {leftOver.text}
          </Banner>
        )}
        {openAsks.map((ask) => (
          <AskCard
            key={ask.id}
            ask={ask}
            now={asks.data?.server_now ?? now}
            notice={noticeFor(notice, ask.id)}
            onNotice={setNotice}
          />
        ))}

        <section className="panel" aria-labelledby="due">
          <h2 id="due" className="panel__title">
            {s.dueToday}
          </h2>
          {active.isSuccess && dueToday.length === 0 && <span className="soft">{s.nothingDue}</span>}
          {dueToday.map((item) => row(item, 'today'))}
        </section>

        {later.length > 0 && (
          <section className="panel" aria-labelledby="later">
            <h2 id="later" className="panel__title">
              {s.comingNext}
            </h2>
            {later.map((item) => row(item, 'later'))}
          </section>
        )}
      </main>

      <aside className="portal__aside">
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

/** PS-4: every reservation, waiting or over. The tab is in the address
 * (`?view=history`), so that a notification about a cancelled reservation opens where
 * that reservation is, never an empty "To hand over" (B#52). */
function ReservationsPage() {
  const [address, setAddress] = useSearchParams()
  const view = address.get('view') === 'history' ? 'history' : 'active'
  const setView = (tab: 'active' | 'history') =>
    setAddress(tab === 'history' ? { view: tab } : {}, { replace: true })
  const found = usePharmacyReservations(view)
  const items = found.data?.items ?? []
  const [notice, setNotice] = useState<CardNotice | null>(null)
  // A reservation handed over leaves "To hand over": what the server said stays here.
  const leftOver = notice && !items.some((item) => item.id === notice.key) ? notice : null
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
            onClick={() => {
              setView(tab)
              setNotice(null)
            }}
          >
            {s[tab]}
          </button>
        ))}
      </div>
      {leftOver && (
        <Banner tone={leftOver.tone} alert={leftOver.tone === 'red'}>
          {leftOver.text}
        </Banner>
      )}
      {found.isPending && <Placeholder />}
      {found.isSuccess && items.length === 0 && (
        <span className="soft">{view === 'active' ? s.nothingActive : s.nothingBefore}</span>
      )}
      {items.map((reservation) => (
        <ReservationCard
          key={reservation.id}
          reservation={reservation}
          notice={noticeFor(notice, reservation.id)}
          onNotice={setNotice}
        />
      ))}
    </main>
  )
}
