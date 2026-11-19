import { TextInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { codeOf, useEscalation, useEscalations, when } from './data'
import { ReasonedButton } from './ReasonedButton'

const s = strings.admin
const e = s.escalations

type Row = Schemas['EscalationRow']
type Detail = Schemas['EscalationDetail']

const MAX_REPLY = 500 // docs/04 SM-9

function Head({ row }: { row: Row }) {
  const emergency = row.reason === 'emergency_claim'
  return (
    <div className="row-card__top">
      <span className={`status-pill status-pill--${emergency ? 'red' : 'grey'}`}>{e.reasons[row.reason]}</span>
      <span className="hint">
        {e.states[row.state]}
        {row.request_ref && ` · ${e.request(row.request_ref)}`} · {e.opened(when(row.created_at))}
      </span>
    </div>
  )
}

/** AS-6: who waits for a person. Emergency claims are first. */
export function EscalationsPage() {
  const [resolved, setResolved] = useState(false)
  const found = useEscalations(resolved)
  const items = found.data?.items ?? []
  return (
    <main className="portal__main">
      <div>
        <h1 className="page-title">{e.title}</h1>
        <span className="soft">{e.intro}</span>
      </div>
      <div className="tabs" role="tablist" aria-label={e.title}>
        {[false, true].map((choice) => (
          <button
            key={String(choice)}
            type="button"
            role="tab"
            aria-selected={resolved === choice}
            className="tabs__tab"
            onClick={() => setResolved(choice)}
          >
            {choice ? e.resolved : e.open}
          </button>
        ))}
      </div>
      {found.isSuccess && items.length === 0 && (
        <div className="empty">{resolved ? e.noneResolved : e.none}</div>
      )}
      {items.map((row) => (
        <article key={row.id} className="row-card">
          <Link to={`/admin/escalations/${row.id}`} className="row-link">
            <Head row={row} />
            <span>{row.summary}</span>
          </Link>
        </article>
      ))}
    </main>
  )
}

/**
 * One escalation, as the owner chose it (2026-11-19): what the client needs, the chat
 * if there is one, one box to write to the client, and one button to close the case.
 * A first reply says by itself that someone is on it. Nothing here changes an order;
 * a missed pickup the client contests can be cleared, which only stops it counting.
 */
export function EscalationPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const found = useEscalation(id)
  const [reply, setReply] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<{ tone: 'green' | 'red' | 'amber'; text: string } | null>(null)

  if (found.isError) {
    return (
      <main className="portal__main">
        <Banner tone="amber">{errorMessage(codeOf(found.error))}</Banner>
        <Link to="/admin/escalations" className="text-button">
          {s.back}
        </Link>
      </main>
    )
  }
  if (!found.data) return <p className="soft">{strings.common.loading}</p>
  const { escalation, thread, contested } = found.data
  const open = escalation.state !== 'RESOLVED'
  const path = { escalation_id: id }
  const short = escalation.client_id.slice(0, 8)
  // R-PRI4, where the temptation is: on the screen of an emergency claim, and only there.
  const emergency =
    escalation.reason === 'emergency_claim' || escalation.notes.some((added) => added.reason === 'emergency_claim')

  function failed(error: unknown) {
    const code = codeOf(error)
    setSaid({ tone: code === 'CHANGED_SINCE' ? 'amber' : 'red', text: code === 'CHANGED_SINCE' ? s.changed : errorMessage(code) })
  }

  function refreshLists() {
    void queryClient.invalidateQueries({ queryKey: ['admin', 'escalations'] })
    void queryClient.invalidateQueries({ queryKey: ['admin', 'overview'] })
  }

  async function act(call: () => Promise<Detail>, done: string) {
    setSaid(null)
    setBusy(true)
    try {
      queryClient.setQueryData(['admin', 'escalation', id], await call())
      setSaid({ tone: 'green', text: done })
      return true
    } catch (error) {
      failed(error)
      await queryClient.invalidateQueries({ queryKey: ['admin', 'escalation', id] })
      return false
    } finally {
      setBusy(false)
      refreshLists()
    }
  }

  async function sendReply(event: FormEvent) {
    event.preventDefault()
    const sent = await act(
      () => unwrap(api.POST('/api/v1/admin/escalations/{escalation_id}/reply', { params: { path }, body: { text: reply } })),
      e.sent,
    )
    if (sent) setReply('')
  }

  async function close(event: FormEvent) {
    event.preventDefault()
    await act(
      () => unwrap(api.POST('/api/v1/admin/escalations/{escalation_id}/resolve', { params: { path }, body: { note } })),
      e.closed,
    )
  }

  async function clear(reservationId: string, reason: string) {
    setSaid(null)
    try {
      await unwrap(
        api.POST('/api/v1/admin/reservations/{reservation_id}/clear-no-show', {
          params: { path: { reservation_id: reservationId } },
          body: { reason },
        }),
      )
      setSaid({ tone: 'green', text: e.cleared })
      return true
    } catch (error) {
      failed(error)
      return false
    } finally {
      await queryClient.invalidateQueries({ queryKey: ['admin', 'escalation', id] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'client'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'clients'] })
      refreshLists()
    }
  }

  return (
    <div className="portal__columns">
      <main className="portal__main">
        <Link to="/admin/escalations" className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
          {s.back}
        </Link>
        <section className="panel" aria-labelledby="summary">
          <Head row={escalation} />
          <span className="soft" style={{ fontSize: 15 }}>
            <span className="audit-change">{e.client(short)}</span> (
            <Link to={`/admin/clients/${escalation.client_id}`}>{e.openClient}</Link>)
          </span>
          <div>
            <h1 id="summary" className="panel__title">
              {e.summary}
            </h1>
            <p style={{ margin: '6px 0 0' }}>{escalation.summary}</p>
          </div>
          {escalation.notes.length > 0 && (
            <div>
              <span className="hint">{e.added}</span>
              <ul className="plain-list">
                {escalation.notes.map((added, index) => (
                  <li key={index}>
                    <strong>{e.reasons[added.reason as Row['reason']] ?? added.reason}:</strong> {added.summary}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {escalation.resolution_note && <Banner tone="green">{e.resolvedNote(escalation.resolution_note)}</Banner>}
          {emergency && <Banner tone="grey">{e.noPriority}</Banner>}
        </section>

        {contested.length > 0 && (
          <section className="panel" aria-labelledby="missed">
            <div>
              <h2 id="missed" className="panel__title">
                {e.missed}
              </h2>
              <span className="hint">{e.missedHint}</span>
            </div>
            {contested.map((order) => (
              <div key={order.id} className="row-card" style={{ background: 'var(--page)' }}>
                <div className="row-card__top">
                  <span className="order-ref">{order.ref}</span>
                  <span className="hint">{s.clients.contestedOn(when(order.contested_at))}</span>
                </div>
                <span>
                  {order.product} · {order.pharmacy}
                </span>
                <ReasonedButton label={e.clear} tone="outline" onConfirm={(reason) => clear(order.id, reason)} />
              </div>
            ))}
          </section>
        )}

        <section className="panel" aria-labelledby="thread">
          <div>
            <h2 id="thread" className="panel__title">
              {e.thread}
            </h2>
            {thread.length > 0 && <span className="hint">{e.threadNote}</span>}
          </div>
          {thread.length === 0 && <span className="soft">{e.noThread}</span>}
          <div>
            {thread.map((line, index) => (
              // Two conversations may follow each other here: a number is not unique.
              <div key={index} className="thread-line" dir="auto">
                <span className="thread-line__who">{e.authors[line.author]}</span>
                {line.text && <span>{line.text}</span>}
                {line.cards.map((kind, index) => (
                  <span key={index} className="hint">
                    {e.card(kind)}
                  </span>
                ))}
              </div>
            ))}
          </div>
        </section>
      </main>

      <aside className="portal__aside">
        <div role="status" aria-live="polite">
          {said && <Banner tone={said.tone}>{said.text}</Banner>}
        </div>
        {open && (
          <section className="panel" aria-labelledby="reply">
            <h2 id="reply" className="panel__title">
              {e.reply}
            </h2>
            <form className="form" onSubmit={sendReply}>
              <label htmlFor="team-reply" className="sr-only">
                {e.reply}
              </label>
              <textarea
                id="team-reply"
                className="text-area"
                dir="auto"
                maxLength={MAX_REPLY}
                aria-describedby="team-reply-hint"
                value={reply}
                onChange={(event) => setReply(event.currentTarget.value)}
              />
              <span id="team-reply-hint" className="hint">
                {e.replyHint} {e.left(MAX_REPLY - reply.length)}
              </span>
              <button type="submit" className="pill-button" disabled={busy || !reply.trim()}>
                {e.send}
              </button>
            </form>
          </section>
        )}
        {open && (
          <section className="panel" aria-label={e.close}>
            <form className="form" onSubmit={close}>
              <TextInput
                label={e.note}
                description={e.noteHint}
                size="md"
                maxLength={500}
                autoComplete="off"
                value={note}
                onChange={(event) => setNote(event.currentTarget.value)}
              />
              <button type="submit" className="pill-button pill-button--grey" disabled={busy}>
                {e.close}
              </button>
            </form>
          </section>
        )}
      </aside>
    </div>
  )
}
