import { TextInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { type ClientsHaving, type ClientStatus, codeOf, useAdminClient, useAdminClients, when } from './data'
import { ReasonedButton } from './ReasonedButton'

const s = strings.admin
const c = s.clients
const f = s.flags

type Row = Schemas['AdminClientRow']
type Detail = Schemas['AdminClient']
type Reservation = Schemas['ClientReservation']
type Request = Schemas['ClientRequest']
type Flag = Schemas['AbuseFlagRow']
type Note = { tone: 'green' | 'red' | 'amber'; text: string }

const STATUSES: (ClientStatus | null)[] = [null, 'ACTIVE', 'PAUSED', 'SUSPENDED']
const HAVING: (ClientsHaving | null)[] = [null, 'reservation', 'picked_up', 'request', 'look']
const TONE: Record<ClientStatus, string> = {
  UNVERIFIED: 'grey',
  ACTIVE: 'green',
  PAUSED: 'amber',
  SUSPENDED: 'red',
}
const ORDER_TONE: Record<Reservation['state'], string> = {
  OFFERED: 'blue',
  RESERVED: 'blue',
  PICKED_UP: 'green',
  NOT_AVAILABLE: 'grey',
  EXPIRED_NO_SHOW: 'amber',
  CANCELLED_BY_CLIENT: 'grey',
  CANCELLED_BY_SYSTEM: 'grey',
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
  const [status, setStatus] = useState<ClientStatus | null>(null)
  const [having, setHaving] = useState<ClientsHaving | null>(null)
  const [ref, setRef] = useState('')
  const found = useAdminClients(status, having, ref.trim())
  return (
    <main className="portal__main">
      <div>
        <h1 className="page-title">{c.title}</h1>
        <span className="soft">{c.intro}</span>
      </div>
      <div className="tabs" role="tablist" aria-label={c.title}>
        {STATUSES.map((choice) => (
          <button
            key={choice ?? 'all'}
            type="button"
            role="tab"
            aria-selected={status === choice}
            className="tabs__tab"
            onClick={() => setStatus(choice)}
          >
            {choice ? c.statuses[choice] : c.all}
          </button>
        ))}
      </div>
      <div className="tabs" role="radiogroup" aria-label={c.show}>
        {HAVING.map((choice) => (
          <button
            key={choice ?? 'all'}
            type="button"
            role="radio"
            aria-checked={having === choice}
            className="tabs__tab"
            onClick={() => setHaving(choice)}
          >
            {c.having[choice ?? 'all']}
          </button>
        ))}
      </div>
      <TextInput
        label={c.ref}
        description={c.refHint}
        size="md"
        autoComplete="off"
        value={ref}
        onChange={(event) => setRef(event.currentTarget.value)}
      />
      {found.loaded && found.items.length === 0 && <div className="empty">{c.none}</div>}
      {found.items.map((row) => (
        <article key={row.id} className="row-card">
          <Link to={`/admin/clients/${row.id}`} className="row-link" aria-label={c.open(row.id.slice(0, 8))}>
            <div className="row-card__top">
              <h2 className="card__title audit-change" style={{ margin: 0 }}>
                {c.name(row.id.slice(0, 8))}
              </h2>
              <Pill row={row} />
            </div>
            <Counts row={row} />
          </Link>
        </article>
      ))}
      {found.hasMore && (
        <button type="button" className="text-button" onClick={found.more}>
          {s.more}
        </button>
      )}
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
        <span className={`status-pill status-pill--${cleared ? 'grey' : ORDER_TONE[order.state]}`}>
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

  if (found.isError) {
    return (
      <main className="portal__main">
        <Banner tone="amber">{errorMessage(codeOf(found.error))}</Banner>
        <Link to="/admin/clients" className="text-button">
          {s.back}
        </Link>
      </main>
    )
  }
  if (!found.data) return <p className="soft">{strings.common.loading}</p>
  const { client, reservations, requests, contested, flags } = found.data
  const path = { client_id: id }

  /** Runs one action. What it answers is the client's page (or, for a flag, the flag:
   * the page is then read again). */
  async function act(call: () => Promise<Detail | Flag>, done: string): Promise<boolean> {
    setSaid(null)
    try {
      const answer = await call()
      if ('client' in answer) queryClient.setQueryData(['admin', 'client', id], answer)
      else await queryClient.invalidateQueries({ queryKey: ['admin', 'client', id] })
      setSaid({ tone: 'green', text: done })
      return true
    } catch (error) {
      const code = codeOf(error)
      setSaid({ tone: code === 'CHANGED_SINCE' ? 'amber' : 'red', text: code === 'CHANGED_SINCE' ? s.changed : errorMessage(code) })
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
      setSaid({ tone: 'red', text: codeOf(error) === 'RATE_LIMITED' ? c.contactLimit : errorMessage(codeOf(error)) })
    }
  }

  const flagAct = (flag: Flag, action: 'warn' | 'suspend') => (reason: string) =>
    act(
      () =>
        unwrap(
          api.POST('/api/v1/admin/abuse-flags/{flag_id}/act', {
            params: { path: { flag_id: flag.id } },
            body: { action, reason },
          }),
        ),
      action === 'suspend' ? c.suspended : f.done,
    )

  return (
    <div className="portal__columns">
      <main className="portal__main">
        <Link to="/admin/clients" className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
          {s.back}
        </Link>
        <div>
          <div className="row-card__top">
            <h1 className="page-title audit-change">{c.name(client.id.slice(0, 8))}</h1>
            <span className={`status-pill status-pill--${TONE[client.status]}`}>{c.statuses[client.status]}</span>
          </div>
          <Counts row={client} />
          {client.paused_until && (
            <span className="soft" style={{ display: 'block', fontSize: 15 }}>
              {c.pausedUntil(when(client.paused_until))}
            </span>
          )}
        </div>
        <div role="status" aria-live="polite">
          {said && <Banner tone={said.tone}>{said.text}</Banner>}
        </div>

        {flags.length > 0 && (
          <section className="panel" aria-labelledby="flags">
            <div>
              <h2 id="flags" className="panel__title">
                {c.flags}
              </h2>
              <span className="hint">{c.flagsHint}</span>
            </div>
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
                    )
                  }
                />
                <ReasonedButton label={f.warn} tone="outline" onConfirm={flagAct(flag, 'warn')} />
                {client.status !== 'SUSPENDED' && (
                  <ReasonedButton label={f.suspend} tone="danger" onConfirm={flagAct(flag, 'suspend')} />
                )}
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
        <section className="panel" aria-labelledby="actions">
          <h2 id="actions" className="panel__title">
            {c.actions}
          </h2>
          {client.status === 'PAUSED' && (
            <ReasonedButton
              label={c.liftPause}
              onConfirm={(reason) =>
                act(
                  () => unwrap(api.POST('/api/v1/admin/clients/{client_id}/lift-pause', { params: { path }, body: { reason } })),
                  c.lifted,
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
                )
              }
            />
          )}
        </section>

        <section className="panel" aria-labelledby="contact">
          <div>
            <h2 id="contact" className="panel__title">
              {c.contact}
            </h2>
            <span className="hint">{c.contactHint}</span>
          </div>
          {contact ? (
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
