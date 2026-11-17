import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { codeOf, useEscalation, useEscalations, when } from './data'

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
      <h1 className="page-title">{e.title}</h1>
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

/** One escalation: the assistant's summary, the conversation as stored, and the three
 * things a person can do: take it, reply, resolve. Nothing here changes an order. */
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
  const { escalation, thread, trace_ids: traces } = found.data
  const open = escalation.state !== 'RESOLVED'
  const path = { escalation_id: id }

  async function act(call: () => Promise<Detail>, done: string | null) {
    setSaid(null)
    setBusy(true)
    try {
      queryClient.setQueryData(['admin', 'escalation', id], await call())
      if (done) setSaid({ tone: 'green', text: done })
      return true
    } catch (error) {
      const code = codeOf(error)
      setSaid({ tone: code === 'CHANGED_SINCE' ? 'amber' : 'red', text: code === 'CHANGED_SINCE' ? s.changed : errorMessage(code) })
      await queryClient.invalidateQueries({ queryKey: ['admin', 'escalation', id] })
      return false
    } finally {
      setBusy(false)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'escalations'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'overview'] })
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

  async function resolve(event: FormEvent) {
    event.preventDefault()
    await act(
      () => unwrap(api.POST('/api/v1/admin/escalations/{escalation_id}/resolve', { params: { path }, body: { note } })),
      null,
    )
  }

  return (
    <div className="portal__columns">
      <main className="portal__main">
        <Link to="/admin/escalations" className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
          {s.back}
        </Link>
        <section className="panel" aria-labelledby="summary">
          <Head row={escalation} />
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
          <Link
            to={`/admin/clients/${escalation.client_id}`}
            className="text-button"
            style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}
          >
            {e.openClient}
          </Link>
          {escalation.resolution_note && <Banner tone="green">{e.resolvedNote(escalation.resolution_note)}</Banner>}
          {/* R-PRI4, where the temptation is: on the screen of an emergency claim. */}
          <Banner tone="grey">{e.noPriority}</Banner>
        </section>

        <section className="panel" aria-labelledby="thread">
          <div>
            <h2 id="thread" className="panel__title">
              {e.thread}
            </h2>
            <span className="hint">{e.threadNote}</span>
          </div>
          {thread.length === 0 && <span className="soft">{e.threadGone}</span>}
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
            {escalation.state === 'OPEN' && (
              <button
                type="button"
                className="pill-button pill-button--grey"
                disabled={busy}
                onClick={() =>
                  void act(() => unwrap(api.POST('/api/v1/admin/escalations/{escalation_id}/take', { params: { path } })), null)
                }
              >
                {e.take}
              </button>
            )}
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
          <section className="panel" aria-labelledby="resolve">
            <h2 id="resolve" className="panel__title">
              {e.resolve}
            </h2>
            <form className="form" onSubmit={resolve}>
              <label htmlFor="resolve-note">{e.note}</label>
              <textarea
                id="resolve-note"
                className="text-area"
                maxLength={500}
                value={note}
                onChange={(event) => setNote(event.currentTarget.value)}
              />
              <button type="submit" className="pill-button pill-button--grey" disabled={busy || !note.trim()}>
                {e.resolve}
              </button>
            </form>
          </section>
        )}
        {traces.length > 0 && (
          <section className="panel" aria-labelledby="traces">
            <h2 id="traces" className="panel__title">
              {e.traces}
            </h2>
            <ul className="plain-list">
              {traces.map((trace) => (
                <li key={trace} className="audit-change">
                  {trace}
                </li>
              ))}
            </ul>
          </section>
        )}
      </aside>
    </div>
  )
}
