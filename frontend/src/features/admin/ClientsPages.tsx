import { TextInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { type ClientStatus, codeOf, useAdminClient, useAdminClients, when } from './data'

const s = strings.admin
const c = s.clients

type Row = Schemas['AdminClientRow']
type Detail = Schemas['AdminClient']
type Note = { tone: 'green' | 'red' | 'amber'; text: string }

const STATUSES: (ClientStatus | null)[] = [null, 'ACTIVE', 'PAUSED', 'SUSPENDED']
const TONE: Record<ClientStatus, string> = {
  UNVERIFIED: 'grey',
  ACTIVE: 'green',
  PAUSED: 'amber',
  SUSPENDED: 'red',
}

/** What an admin knows of a client without opening their contact details: a status
 * and a few counts. Never a name. */
function Counts({ row }: { row: Row }) {
  return (
    <span className="soft" style={{ fontSize: 15 }}>
      {[row.district ?? c.noDistrict, c.orders(row.open_orders), c.requests(row.open_requests), c.noShows(row.no_shows)].join(' · ')}
    </span>
  )
}

/** AS-5: clients as statuses and counts. A complaint quotes an order or request number:
 * that number finds its client. */
export function ClientsPage() {
  const [status, setStatus] = useState<ClientStatus | null>(null)
  const [ref, setRef] = useState('')
  const found = useAdminClients(status, ref.trim())
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
              <span className={`status-pill status-pill--${row.contested > 0 ? 'amber' : TONE[row.status]}`}>
                {row.contested > 0 ? c.contestWaiting : c.statuses[row.status]}
              </span>
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

/** One client: the status, what they contest, and what an admin may do, each with a
 * reason. The contact details are behind a button, and each look is in the audit log. */
export function ClientPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const found = useAdminClient(id)
  const [reason, setReason] = useState('')
  const [contact, setContact] = useState<Schemas['ClientContact'] | null>(null)
  const [busy, setBusy] = useState(false)
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
  const { client, contested } = found.data
  const path = { client_id: id }

  async function act(call: () => Promise<Detail>, done: string) {
    setSaid(null)
    setBusy(true)
    try {
      queryClient.setQueryData(['admin', 'client', id], await call())
      setSaid({ tone: 'green', text: done })
      setReason('')
    } catch (error) {
      const code = codeOf(error)
      setSaid({ tone: code === 'CHANGED_SINCE' ? 'amber' : 'red', text: code === 'CHANGED_SINCE' ? s.changed : errorMessage(code) })
      await queryClient.invalidateQueries({ queryKey: ['admin', 'client', id] })
    } finally {
      setBusy(false)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'clients'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'overview'] })
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

  const body = { reason }
  const needsReason = busy || !reason.trim()
  function stop(event: FormEvent) {
    event.preventDefault()
  }

  return (
    <div className="portal__columns">
      <main className="portal__main">
        <Link to="/admin/clients" className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
          {s.back}
        </Link>
        <div className="row-card__top">
          <h1 className="page-title audit-change">{c.name(client.id.slice(0, 8))}</h1>
          <span className={`status-pill status-pill--${TONE[client.status]}`}>{c.statuses[client.status]}</span>
        </div>
        <div role="status" aria-live="polite">
          {said && <Banner tone={said.tone}>{said.text}</Banner>}
        </div>
        <section className="panel" aria-labelledby="numbers">
          <h2 id="numbers" className="panel__title">
            {c.numbers}
          </h2>
          <Counts row={client} />
          {client.paused_until && <span className="soft">{c.pausedUntil(when(client.paused_until))}</span>}
        </section>

        <section className="panel" aria-labelledby="contests">
          <div>
            <h2 id="contests" className="panel__title">
              {c.contests}
            </h2>
            <span className="hint">{c.contestsHint}</span>
          </div>
          {contested.length === 0 && <span className="soft">{c.noContests}</span>}
          {contested.map((order) => (
            <div key={order.id} className="row-card" style={{ background: 'var(--page)' }}>
              <div className="row-card__top">
                <span className="order-ref">{order.ref}</span>
                <span className="hint">{c.contestedOn(when(order.contested_at))}</span>
              </div>
              <span>
                {order.product} · {order.pharmacy}
              </span>
              <button
                type="button"
                className="pill-button pill-button--grey"
                style={{ alignSelf: 'flex-start' }}
                disabled={needsReason}
                onClick={() =>
                  void act(
                    () =>
                      unwrap(
                        api.POST('/api/v1/admin/reservations/{reservation_id}/clear-no-show', {
                          params: { path: { reservation_id: order.id } },
                          body,
                        }),
                      ),
                    c.cleared,
                  )
                }
              >
                {c.clear}
              </button>
            </div>
          ))}
        </section>
      </main>

      <aside className="portal__aside">
        <section className="panel" aria-labelledby="actions">
          <h2 id="actions" className="panel__title">
            {c.actions}
          </h2>
          <form className="form" onSubmit={stop}>
            <TextInput
              label={s.reason}
              description={s.reasonHint}
              size="md"
              maxLength={300}
              value={reason}
              onChange={(event) => setReason(event.currentTarget.value)}
            />
            {client.status === 'PAUSED' && (
              <button
                type="button"
                className="pill-button pill-button--grey"
                disabled={needsReason}
                onClick={() =>
                  void act(() => unwrap(api.POST('/api/v1/admin/clients/{client_id}/lift-pause', { params: { path }, body })), c.lifted)
                }
              >
                {c.liftPause}
              </button>
            )}
            {(client.status === 'ACTIVE' || client.status === 'PAUSED') && (
              <>
                <span className="hint">{c.suspendHint}</span>
                <button
                  type="button"
                  className="pill-button pill-button--danger"
                  disabled={needsReason}
                  onClick={() =>
                    void act(() => unwrap(api.POST('/api/v1/admin/clients/{client_id}/suspend', { params: { path }, body })), c.suspended)
                  }
                >
                  {c.suspend}
                </button>
              </>
            )}
            {client.status === 'SUSPENDED' && (
              <button
                type="button"
                className="pill-button"
                disabled={needsReason}
                onClick={() =>
                  void act(() => unwrap(api.POST('/api/v1/admin/clients/{client_id}/reinstate', { params: { path }, body })), c.reinstated)
                }
              >
                {c.reinstate}
              </button>
            )}
          </form>
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
