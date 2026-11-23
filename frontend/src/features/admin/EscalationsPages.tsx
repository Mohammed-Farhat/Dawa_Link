import { TextInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { Pager } from '../../components/Pager'
import { Placeholder } from '../../components/Placeholder'
import { reservationTone } from '../../components/reservationTone'
import { usePage } from '../../components/usePage'
import { langOf } from '../../format'
import { strings } from '../../strings/en'
import {
  loadProblem,
  type Note,
  refusal,
  useBackToList,
  useEscalation,
  useEscalations,
  useFromList,
  when,
} from './data'
import { ListFailed } from './ListFailed'
import { ReasonedButton } from './ReasonedButton'
import { Said } from './said'

const s = strings.admin
const e = s.escalations

type Row = Schemas['EscalationRow']
type Detail = Schemas['EscalationDetail']

const MAX_REPLY = 500 // docs/04 SM-9
const LIST = '/admin/escalations'

/** The panels of an escalation's page whose buttons can be refused. */
type Place = 'missed' | 'reply' | 'close'

// A few pills side by side, wrapping on a narrow screen.
const PILLS = { display: 'flex', flexWrap: 'wrap', gap: 6, alignSelf: 'flex-start' } as const

function Head({ row }: { row: Row }) {
  return (
    <div className="row-card__top">
      {/* Every reason of the case, each once. Amber, as on the design canvas, for an
          emergency claim: it asks for attention, nothing has failed. */}
      <span style={PILLS}>
        {row.reasons.map((reason) => (
          <span key={reason} className={`status-pill status-pill--${reason === 'emergency_claim' ? 'amber' : 'grey'}`}>
            {e.reasons[reason]}
          </span>
        ))}
      </span>
      <span className="hint">
        {e.states[row.state]}
        {row.request_ref && ` · ${e.request(row.request_ref)}`} · {e.opened(when(row.created_at))}
      </span>
    </div>
  )
}

/** What waits for the team on an open case: a new ask, or a message of the client. */
function Marks({ row }: { row: Row }) {
  if (row.state === 'RESOLVED' || (!row.new_ask_since_reply && !row.client_wrote_at)) return null
  return (
    <span style={PILLS}>
      {row.new_ask_since_reply && <span className="status-pill status-pill--blue">{e.newAsk}</span>}
      {row.client_wrote_at && <span className="status-pill status-pill--blue">{e.clientWrote(when(row.client_wrote_at))}</span>}
    </span>
  )
}

/** AS-6: who waits for a person. Emergency claims are first, then the cases that wait for
 * the team (never answered, asked again, or the client wrote since the reply). Closed
 * cases are the newest first. Both lists are numbered pages. */
export function EscalationsPage() {
  const paging = usePage()
  const resolved = paging.params.get('closed') === '1'
  const found = useEscalations(resolved, paging.offset)
  const items = found.data?.items ?? []
  const from = useFromList()
  return (
    <main className="portal__main">
      <div>
        <h1 className="page-title">{e.title}</h1>
        <span className="soft">{e.intro}</span>
      </div>
      <div className="tabs tabs--wrap" role="tablist" aria-label={e.title}>
        {[false, true].map((choice) => (
          <button
            key={String(choice)}
            type="button"
            role="tab"
            aria-selected={resolved === choice}
            className="tabs__tab"
            onClick={() => paging.choose('closed', choice ? '1' : null)}
          >
            {choice ? e.resolved : e.open}
          </button>
        ))}
      </div>
      {found.isError && <ListFailed failure={found.error} onRetry={() => void found.refetch()} />}
      {found.isPending && <Placeholder />}
      {found.isSuccess && items.length === 0 && (
        <div className="empty">{resolved ? e.noneResolved : e.none}</div>
      )}
      {items.map((row) => (
        <article key={row.id} className="row-card">
          <Link to={`/admin/escalations/${row.id}`} state={from} className="row-link">
            <Head row={row} />
            <Marks row={row} />
            {/* The newest ask: what the client needs now. In the assistant's words, in the
                client's language. */}
            <span dir="auto" lang={langOf(row.last_summary)}>
              {row.last_summary}
            </span>
          </Link>
        </article>
      ))}
      <Pager paging={paging} total={found.data?.total} settled={!found.isPlaceholderData} />
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
  const [said, setSaid] = useState<Note | null>(null)
  const back = useBackToList(LIST)

  if (found.isError) {
    return (
      <main className="portal__main">
        {/* The section's name as the page's heading: the focus and the tab's title find it
            when the page could not be read (B#19, B#34). */}
        <h1 className="page-title">{e.title}</h1>
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
  const { escalation, thread, contested } = found.data
  const open = escalation.state !== 'RESOLVED'
  const stillCounts = contested.some((order) => order.counts_as_no_show)
  const path = { escalation_id: id }
  const short = escalation.client_id.slice(0, 8)
  // R-PRI4, where the temptation is: on the screen of an emergency claim, and only there.
  const emergency =
    escalation.reason === 'emergency_claim' || escalation.notes.some((added) => added.reason === 'emergency_claim')
  // A refusal is said in its panel while the panel is there (see `Said`).
  const present: Place[] = []
  if (contested.length > 0) present.push('missed')
  if (open) present.push('reply', 'close')

  function refreshLists() {
    void queryClient.invalidateQueries({ queryKey: ['admin', 'escalations'] })
    void queryClient.invalidateQueries({ queryKey: ['admin', 'overview'] })
  }

  async function act(call: () => Promise<Detail>, done: string, at: Place) {
    setSaid(null)
    setBusy(true)
    try {
      queryClient.setQueryData(['admin', 'escalation', id], await call())
      setSaid({ tone: 'green', text: done })
      return true
    } catch (error) {
      setSaid(refusal(error, at))
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
      'reply',
    )
    if (sent) setReply('')
  }

  async function close(event: FormEvent) {
    event.preventDefault()
    await act(
      () => unwrap(api.POST('/api/v1/admin/escalations/{escalation_id}/resolve', { params: { path }, body: { note } })),
      e.closed,
      'close',
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
      setSaid(refusal(error, 'missed'))
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
        <Link to={back} className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
          {s.back}
        </Link>
        <section className="panel" aria-labelledby="summary">
          <Head row={escalation} />
          <Marks row={escalation} />
          <span className="soft" style={{ fontSize: 15 }}>
            <span className="audit-change">{e.client(short)}</span> (
            <Link to={`/admin/clients/${escalation.client_id}`}>{e.openClient}</Link>)
          </span>
          <div>
            <h1 id="summary" className="panel__title">
              {e.summary}
            </h1>
            {/* The assistant's words, in the client's language: read in it (B#10). */}
            <p style={{ margin: '6px 0 0' }} dir="auto" lang={langOf(escalation.summary)}>
              {escalation.summary}
            </p>
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

        {/* Only on a case about a missed pickup, and only its own reservation (with the
            other boxes of its trip): the server sends nothing for a case of another kind. */}
        {contested.length > 0 && (
          <section className="panel" aria-labelledby="missed">
            <div>
              <h2 id="missed" className="panel__title">
                {e.missed}
              </h2>
              {stillCounts && <span className="hint">{e.missedHint}</span>}
            </div>
            <Said note={said} at="missed" />
            {contested.map((order) => (
              <div key={order.id} className="row-card" style={{ background: 'var(--page)' }}>
                <div className="row-card__top">
                  <span className="order-ref">{order.ref}</span>
                  {/* How it ended, in the words of the client's page (B#61). */}
                  <span
                    className={`status-pill status-pill--${
                      order.counts_as_no_show ? reservationTone('EXPIRED_NO_SHOW') : 'grey'
                    }`}
                  >
                    {order.counts_as_no_show ? s.clients.orderStates.EXPIRED_NO_SHOW : s.clients.notCounted}
                  </span>
                </div>
                <span>
                  {order.product} · {order.pharmacy}
                </span>
                <span className="hint">{s.clients.contestedOn(when(order.contested_at))}</span>
                {/* Nothing is left to clear once it no longer counts. */}
                {order.counts_as_no_show && (
                  <ReasonedButton label={e.clear} tone="outline" onConfirm={(reason) => clear(order.id, reason)} />
                )}
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
          {/* Read out as it grows: the client may be writing to the team now. */}
          <div role="log" aria-label={e.thread}>
            {thread.map((line, index) => (
              // Two conversations may follow each other here: a number is not unique.
              // The direction is the message's own, not that of the English label above it.
              <div key={index} className="thread-line">
                {line.starts_another_chat && <span className="hint">{e.anotherChat}</span>}
                <span className="thread-line__who">{e.authors[line.author]}</span>
                {line.text && (
                  <span dir="auto" lang={langOf(line.text)}>
                    {line.text}
                  </span>
                )}
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
        <Said note={said} present={present} />
        {open && (
          <section className="panel" aria-labelledby="reply">
            <h2 id="reply" className="panel__title">
              {e.reply}
            </h2>
            <Said note={said} at="reply" />
            <form className="form" onSubmit={sendReply}>
              <label htmlFor="team-reply" className="sr-only">
                {e.reply}
              </label>
              <textarea
                id="team-reply"
                className="text-area"
                dir="auto"
                lang={langOf(reply)}
                maxLength={MAX_REPLY}
                aria-describedby="team-reply-hint"
                value={reply}
                onChange={(event) => setReply(event.currentTarget.value)}
              />
              <span id="team-reply-hint" className="hint">
                {e.replyHint} {e.left(MAX_REPLY - reply.length)}
              </span>
              {escalation.hold_ends_at && <span className="hint">{e.withTeam(when(escalation.hold_ends_at))}</span>}
              <button type="submit" className="pill-button" disabled={busy || !reply.trim()}>
                {e.send}
              </button>
            </form>
          </section>
        )}
        {open && (
          <section className="panel" aria-label={e.close}>
            <Said note={said} at="close" />
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
