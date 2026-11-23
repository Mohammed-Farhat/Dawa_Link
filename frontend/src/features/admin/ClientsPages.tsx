import { TextInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { Pager } from '../../components/Pager'
import { reservationTone } from '../../components/reservationTone'
import { Placeholder } from '../../components/Placeholder'
import { usePage } from '../../components/usePage'
import { errorMessage, strings } from '../../strings/en'
import {
  type ClientsHaving,
  type ClientStatus,
  loadProblem,
  type Note,
  oneOf,
  refusal,
  TYPED_MAX,
  useAdminClient,
  useAdminClients,
  useBackToList,
  useFromList,
  when,
} from './data'
import { ListFailed } from './ListFailed'
import { ReasonedButton } from './ReasonedButton'
import { Said } from './said'

const s = strings.admin
const c = s.clients
const f = s.flags

type Row = Schemas['AdminClientRow']
type Detail = Schemas['AdminClient']
type Reservation = Schemas['ClientReservation']
type Request = Schemas['ClientRequest']
type Flag = Schemas['AbuseFlagRow']
/** The panels of a client's page whose buttons can be refused. */
type Place = 'flags' | 'contests' | 'actions' | 'contact'

const LIST = '/admin/clients'

const STATUSES: (ClientStatus | null)[] = [null, 'ACTIVE', 'PAUSED', 'SUSPENDED', 'DELETED']
const HAVING: (ClientsHaving | null)[] = [null, 'reservation', 'picked_up', 'request', 'look']
const TONE: Record<ClientStatus, string> = {
  UNVERIFIED: 'grey',
  ACTIVE: 'green',
  PAUSED: 'amber',
  SUSPENDED: 'red',
  // The client deleted their account (R-AU10): their ID and past reservations only.
  DELETED: 'grey',
}

/** What an admin knows of a client without opening their contact details: a status
 * and what they have going, in numbers. Never a name. */
function Counts({ row }: { row: Row }) {
  return (
    <span className="soft" style={{ fontSize: 15 }}>
      {[
        row.district ?? c.noDistrict,
        c.orders(row.open_orders),
        c.pickedUp(row.picked_up),
        c.requests(row.open_requests),
        c.noShows(row.no_shows),
      ].join(' · ')}
    </span>
  )
}

/** What a client needs an admin for comes before their status. */
function Pill({ row }: { row: Row }) {
  if (row.contested > 0) return <span className="status-pill status-pill--amber">{c.contestWaiting}</span>
  if (row.flags_open > 0) return <span className="status-pill status-pill--amber">{c.flagged}</span>
  return <span className={`status-pill status-pill--${TONE[row.status]}`}>{c.statuses[row.status]}</span>
}

/** AS-5: clients as statuses and counts. A complaint quotes an order or request number:
 * that number finds its client. */
export function ClientsPage() {
  // The choices, the typed number and the page are in the address (`usePage`): "Back to
  // the list" finds the same page.
  const paging = usePage()
  const { params: choices, choose } = paging
  const status = oneOf(choices.get('status'), STATUSES)
  const having = oneOf(choices.get('show'), HAVING)
  // The box keeps its own text, so typing never waits for the address to change.
  // Never longer than the API takes, an old address included: it would fail on every visit.
  const [ref, setRef] = useState((choices.get('ref') ?? '').slice(0, TYPED_MAX.ref))
  const found = useAdminClients(status, having, ref.trim(), paging.offset)
  const from = useFromList()
  // The box is what the list shows. If the address lost its text (a tab of the bar was
  // pressed on this page), it is written back, so that Back finds the same list.
  useEffect(() => {
    if ((choices.get('ref') ?? '') !== ref) choose('ref', ref)
  }, [choices, choose, ref])
  return (
    <main className="portal__main">
      <div>
        <h1 className="page-title">{c.title}</h1>
        <span className="soft">{c.intro}</span>
      </div>
      {/* Two rows of choices that look alike: each says what it chooses. */}
      <div className="admin-filter">
        <span id="clients-account" className="admin-filter__label">
          {c.account}
        </span>
        <div className="tabs tabs--wrap" role="tablist" aria-labelledby="clients-account">
          {STATUSES.map((choice) => (
            <button
              key={choice ?? 'all'}
              type="button"
              role="tab"
              aria-selected={status === choice}
              className="tabs__tab"
              onClick={() => choose('status', choice)}
            >
              {choice ? c.statuses[choice] : c.all}
            </button>
          ))}
        </div>
      </div>
      <div className="admin-filter">
        <span id="clients-show" className="admin-filter__label">
          {c.show}
        </span>
        <div className="tabs tabs--wrap" role="radiogroup" aria-labelledby="clients-show">
          {HAVING.map((choice) => (
            <button
              key={choice ?? 'all'}
              type="button"
              role="radio"
              aria-checked={having === choice}
              className="tabs__tab"
              onClick={() => choose('show', choice)}
            >
              {c.having[choice ?? 'all']}
            </button>
          ))}
        </div>
      </div>
      <TextInput
        label={c.ref}
        description={c.refHint}
        size="md"
        autoComplete="off"
        maxLength={TYPED_MAX.ref}
        value={ref}
        onChange={(event) => {
          setRef(event.currentTarget.value)
          choose('ref', event.currentTarget.value)
        }}
      />
      {found.failure !== null && <ListFailed failure={found.failure} onRetry={found.retry} />}
      {found.loading && <Placeholder />}
      {found.loaded && found.items.length === 0 && <div className="empty">{c.none}</div>}
      {found.items.map((row) => (
        <article key={row.id} className="row-card">
          {/* Named by what it shows, the status included: "Says they picked it up" is
              the reason to open it (WCAG 2.5.3). */}
          <Link to={`/admin/clients/${row.id}`} state={from} className="row-link">
            <div className="row-card__top">
              <h2 className="card__title" style={{ margin: 0 }}>
                {c.one} <span className="order-ref">{row.id.slice(0, 8)}</span>
              </h2>
              <Pill row={row} />
            </div>
            <Counts row={row} />
          </Link>
        </article>
      ))}
      <Pager paging={paging} total={found.total} settled={found.settled} />
    </main>
  )
}

function ReservationLine({ order }: { order: Reservation }) {
  const cleared = order.state === 'EXPIRED_NO_SHOW' && !order.counts_as_no_show
  const moment =
    order.state === 'RESERVED' && order.deadline
      ? c.pickUpBy(when(order.deadline))
      : order.closed_at
        ? when(order.closed_at)
        : c.reservedOn(when(order.created_at))
  return (
    <li className="row-card" style={{ background: 'var(--page)' }}>
      <div className="row-card__top">
        <span className="order-ref">{order.ref}</span>
        <span className={`status-pill status-pill--${cleared ? 'grey' : reservationTone(order.state)}`}>
          {cleared ? c.notCounted : c.orderStates[order.state]}
        </span>
      </div>
      <span>
        {order.product} · {order.pharmacy}
      </span>
      <span className="hint">
        {c.packs(order.units)} · {moment}
      </span>
    </li>
  )
}

function RequestLine({ request }: { request: Request }) {
  const open = request.state === 'OPEN'
  const outcome = request.outcome as keyof typeof c.outcomes | null
  return (
    <li className="row-card" style={{ background: 'var(--page)' }}>
      <div className="row-card__top">
        <span className="order-ref">{request.ref}</span>
        <span className={`status-pill status-pill--${open ? 'blue' : outcome === 'FULFILLED' ? 'green' : 'grey'}`}>
          {open ? c.requestOpen(when(request.ends_at)) : outcome ? (c.outcomes[outcome] ?? outcome) : c.requestClosed}
        </span>
      </div>
      <span className="hint">
        {c.secured(request.secured, request.medicines)} · {c.startedOn(when(request.created_at))}
      </span>
    </li>
  )
}

/** One client: what needs a person first (a flag, a contested missed pickup), then what
 * they have going, then what an admin may do. Each action asks for its reason where its
 * button is. The contact details are behind a button, and each look is in the audit log. */
export function ClientPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const found = useAdminClient(id)
  const [contact, setContact] = useState<Schemas['ClientContact'] | null>(null)
  const [said, setSaid] = useState<Note | null>(null)
  // The contact view answered that the account was deleted meanwhile (R-AU10).
  const [goneMeanwhile, setGoneMeanwhile] = useState(false)
  const back = useBackToList(LIST)

  if (found.isError) {
    return (
      <main className="portal__main">
        {/* The section's name as the page's heading: the focus and the tab's title find it
            when the page could not be read (B#19, B#34). */}
        <h1 className="page-title">{c.title}</h1>
        <Banner tone="red" alert>
          {loadProblem(found.error)}
        </Banner>
        <Link to={back} className="text-button">
          {s.back}
        </Link>
      </main>
    )
  }
  if (!found.data) {
    return (
      <main className="portal__main">
        <p className="soft">{strings.common.loading}</p>
      </main>
    )
  }
  const { client, reservations, requests, contested, flags } = found.data
  const path = { client_id: id }
  // A deleted account keeps an ID and its past reservations only: nothing to contact,
  // nothing to suspend or reinstate.
  const deleted = client.status === 'DELETED' || goneMeanwhile
  const canAct = !deleted && (['ACTIVE', 'PAUSED', 'SUSPENDED'] as ClientStatus[]).includes(client.status)
  // A refusal is said in its panel while the panel is there (see `Said`).
  const present: Place[] = ['contact']
  if (canAct) present.push('actions')
  if (flags.length > 0) present.push('flags')
  if (contested.length > 0) present.push('contests')

  /** Runs one action. What it answers is the client's page (or, for a flag, the flag:
   * the page is then read again). A success is said at the top, a refusal at `at`. */
  async function act(call: () => Promise<Detail | Flag>, done: string, at: Place): Promise<boolean> {
    setSaid(null)
    try {
      const answer = await call()
      if ('client' in answer) queryClient.setQueryData(['admin', 'client', id], answer)
      else await queryClient.invalidateQueries({ queryKey: ['admin', 'client', id] })
      setSaid({ tone: 'green', text: done })
      return true
    } catch (error) {
      setSaid(refusal(error, at))
      await queryClient.invalidateQueries({ queryKey: ['admin', 'client', id] })
      return false
    } finally {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'clients'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'overview'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'escalation'] })
    }
  }

  async function showContact() {
    setSaid(null)
    try {
      setContact(await unwrap(api.GET('/api/v1/admin/clients/{client_id}/contact', { params: { path } })))
    } catch (error) {
      if (error instanceof ApiFailure && error.code === 'NOT_FOUND' && error.details.reason === 'ACCOUNT_DELETED') {
        setGoneMeanwhile(true)
        void queryClient.invalidateQueries({ queryKey: ['admin', 'client', id] })
        return
      }
      setSaid(refusal(error, 'contact', (code) => (code === 'RATE_LIMITED' ? c.contactLimit : errorMessage(code))))
    }
  }

  // A flag's own buttons only note what was done. Suspending is under Actions, and it
  // closes the client's open flags itself (B#58): one button, one meaning.
  const noteWarning = (flag: Flag) => (reason: string) =>
    act(
      () =>
        unwrap(
          api.POST('/api/v1/admin/abuse-flags/{flag_id}/act', {
            params: { path: { flag_id: flag.id } },
            body: { action: 'warn', reason },
          }),
        ),
      f.done,
      'flags',
    )

  return (
    <div className="portal__columns">
      <main className="portal__main">
        <Link to={back} className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
          {s.back}
        </Link>
        <div>
          <div className="row-card__top">
            <h1 className="page-title">
              {c.one} <span className="order-ref">{client.id.slice(0, 8)}</span>
            </h1>
            <span className={`status-pill status-pill--${TONE[client.status]}`}>{c.statuses[client.status]}</span>
          </div>
          <Counts row={client} />
          {client.paused_until && (
            <span className="soft" style={{ display: 'block', fontSize: 15 }}>
              {c.pausedUntil(when(client.paused_until))}
            </span>
          )}
        </div>
        <Said note={said} present={present} />

        {flags.length > 0 && (
          <section className="panel" aria-labelledby="flags">
            <div>
              <h2 id="flags" className="panel__title">
                {c.flags}
              </h2>
              <span className="hint">{c.flagsHint}</span>
            </div>
            <Said note={said} at="flags" />
            {flags.map((flag) => (
              <div key={flag.id} className="row-card" style={{ background: 'var(--page)' }}>
                <div className="row-card__top">
                  <strong>{f.rules[flag.rule as keyof typeof f.rules] ?? flag.rule}</strong>
                  <span className={`status-pill status-pill--${flag.severity === 'high' ? 'red' : 'grey'}`}>
                    {f.severity[flag.severity]}
                  </span>
                </div>
                <span className="hint">
                  {[
                    f.raised(when(flag.created_at)),
                    ...Object.entries(flag.evidence)
                      .filter(([, value]) => typeof value === 'number')
                      .map(([key, value]) => `${f.evidence[key as keyof typeof f.evidence] ?? key}: ${String(value)}`),
                  ].join(' · ')}
                </span>
                <ReasonedButton
                  label={f.dismiss}
                  tone="outline"
                  onConfirm={(reason) =>
                    act(
                      () =>
                        unwrap(
                          api.POST('/api/v1/admin/abuse-flags/{flag_id}/dismiss', {
                            params: { path: { flag_id: flag.id } },
                            body: { reason },
                          }),
                        ),
                      f.done,
                      'flags',
                    )
                  }
                />
                <ReasonedButton label={f.warn} tone="outline" onConfirm={noteWarning(flag)} />
                <span className="hint">{f.warnHint}</span>
              </div>
            ))}
          </section>
        )}

        {contested.length > 0 && (
          <section className="panel" aria-labelledby="contests">
            <div>
              <h2 id="contests" className="panel__title">
                {c.contests}
              </h2>
              <span className="hint">{c.contestsHint}</span>
            </div>
            <Said note={said} at="contests" />
            {contested.map((order) => (
              <div key={order.id} className="row-card" style={{ background: 'var(--page)' }}>
                <div className="row-card__top">
                  <span className="order-ref">{order.ref}</span>
                  <span className="hint">{c.contestedOn(when(order.contested_at))}</span>
                </div>
                <span>
                  {order.product} · {order.pharmacy}
                </span>
                <ReasonedButton
                  label={c.clear}
                  tone="outline"
                  onConfirm={(reason) =>
                    act(
                      () =>
                        unwrap(
                          api.POST('/api/v1/admin/reservations/{reservation_id}/clear-no-show', {
                            params: { path: { reservation_id: order.id } },
                            body: { reason },
                          }),
                        ),
                      c.cleared,
                      'contests',
                    )
                  }
                />
              </div>
            ))}
          </section>
        )}

        <section className="panel" aria-labelledby="reservations">
          <div>
            <h2 id="reservations" className="panel__title">
              {c.reservations}
            </h2>
            {reservations.length > 0 && <span className="hint">{c.reservationsHint}</span>}
          </div>
          {reservations.length === 0 && <span className="soft">{c.noReservations}</span>}
          <ul className="plain-list" style={{ display: 'grid', gap: 10 }}>
            {reservations.map((order) => (
              <ReservationLine key={order.ref} order={order} />
            ))}
          </ul>
        </section>

        <section className="panel" aria-labelledby="requests">
          <div>
            <h2 id="requests" className="panel__title">
              {c.requestsTitle}
            </h2>
            <span className="hint">{c.requestsHint}</span>
          </div>
          {requests.length === 0 && <span className="soft">{c.noRequests}</span>}
          <ul className="plain-list" style={{ display: 'grid', gap: 10 }}>
            {requests.map((request) => (
              <RequestLine key={request.ref} request={request} />
            ))}
          </ul>
        </section>
      </main>

      <aside className="portal__aside">
        {canAct && (
          <section className="panel" aria-labelledby="actions">
            <h2 id="actions" className="panel__title">
              {c.actions}
            </h2>
            <Said note={said} at="actions" />
            {client.status === 'PAUSED' && (
              <ReasonedButton
                label={c.liftPause}
                onConfirm={(reason) =>
                  act(
                    () => unwrap(api.POST('/api/v1/admin/clients/{client_id}/lift-pause', { params: { path }, body: { reason } })),
                    c.lifted,
                    'actions',
                  )
                }
              />
            )}
            {(client.status === 'ACTIVE' || client.status === 'PAUSED') && (
              <>
                <ReasonedButton
                  label={c.suspend}
                  tone="danger"
                  onConfirm={(reason) =>
                    act(
                      () => unwrap(api.POST('/api/v1/admin/clients/{client_id}/suspend', { params: { path }, body: { reason } })),
                      c.suspended,
                      'actions',
                    )
                  }
                />
                <span className="hint">{c.suspendHint}</span>
              </>
            )}
            {client.status === 'SUSPENDED' && (
              <ReasonedButton
                label={c.reinstate}
                tone="plain"
                onConfirm={(reason) =>
                  act(
                    () => unwrap(api.POST('/api/v1/admin/clients/{client_id}/reinstate', { params: { path }, body: { reason } })),
                    c.reinstated,
                    'actions',
                  )
                }
              />
            )}
          </section>
        )}

        <section className="panel" aria-labelledby="contact">
          <div>
            <h2 id="contact" className="panel__title">
              {c.contact}
            </h2>
            {!deleted && <span className="hint">{c.contactHint}</span>}
          </div>
          <Said note={said} at="contact" />
          {deleted ? (
            <span className="soft">{c.deletedContact}</span>
          ) : contact ? (
            <dl className="card__lines">
              <div className="card__line">
                <dt>{c.fullName}</dt>
                <dd>{contact.full_name}</dd>
              </div>
              <div className="card__line">
                <dt>{c.email}</dt>
                <dd>{contact.email}</dd>
              </div>
              <div className="card__line">
                <dt>{c.phone}</dt>
                <dd>{contact.phone ?? c.noPhone}</dd>
              </div>
            </dl>
          ) : (
            <button type="button" className="pill-button pill-button--grey" onClick={() => void showContact()}>
              {c.showContact}
            </button>
          )}
        </section>
      </aside>
    </div>
  )
}
