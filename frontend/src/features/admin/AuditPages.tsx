import { NativeSelect } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { Pager } from '../../components/Pager'
import { Placeholder } from '../../components/Placeholder'
import { usePage } from '../../components/usePage'
import { errorMessage, strings } from '../../strings/en'
import { details, link, sentence, thing, who, type AuditEvent } from './auditWords'
import {
  type AuditActor,
  type AuditFilters,
  type AuditKind,
  codeOf,
  oneOf,
  useAudit,
  useDemoClock,
  useOverview,
  when,
} from './data'
import { ListFailed } from './ListFailed'

const s = strings.admin
const a = s.audit
const c = s.clock

// Typed by the API's own list of families: one added there without words here fails the
// typecheck.
const KIND_WORDS: Record<AuditKind | '', string> = a.kinds
const KINDS = Object.keys(KIND_WORDS).filter(Boolean) as AuditKind[]
const ACTORS = Object.keys(a.actors).filter(Boolean) as AuditActor[]

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const ENTITY = /^[a-z_]{1,40}$/

/** "order:<its ID>" in the address, from a row's [Only this]: one value, so that a single
 * write of the address sets both. Anything else in it is ignored. */
function readAbout(value: string | null): AuditFilters['about'] {
  if (!value) return null
  const at = value.indexOf(':')
  const type = value.slice(0, at)
  const id = value.slice(at + 1)
  return at > 0 && ENTITY.test(type) && UUID.test(id) ? { type, id } : null
}

function Who({ event }: { event: AuditEvent }) {
  const said = who(event)
  return (
    <>
      {said.text}
      {said.short && (
        <>
          {' '}
          <span className="order-ref">{said.short}</span>
        </>
      )}
    </>
  )
}

/** AS-11: who did what, in words. Read-only: no button here changes anything. */
export function AuditPage() {
  const paging = usePage()
  const { params, choose } = paging
  const kind = oneOf(params.get('kind'), KINDS)
  const actor = oneOf(params.get('who'), ACTORS)
  const about = readAbout(params.get('about'))
  // The query's key is compared by value: a new object with the same choices is the same page.
  const found = useAudit({ kind, actor, about }, paging.offset)
  const demoMode = useOverview().data?.demo_mode ?? false
  return (
    <main className="portal__main">
      <div>
        <h1 className="page-title">{a.title}</h1>
        <span className="soft">{a.intro}</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-end' }}>
        <NativeSelect
          label={a.kind}
          size="md"
          value={kind ?? ''}
          onChange={(event) => choose('kind', event.currentTarget.value || null)}
          data={Object.entries(KIND_WORDS).map(([value, label]) => ({ value, label }))}
        />
        <NativeSelect
          label={a.actor}
          size="md"
          value={actor ?? ''}
          onChange={(event) => choose('who', event.currentTarget.value || null)}
          data={Object.entries(a.actors).map(([value, label]) => ({ value, label }))}
        />
      </div>
      {about && (
        <Banner tone="grey">
          {a.about(thing(about.type))}{' '}
          <button type="button" className="text-button" onClick={() => choose('about', null)}>
            {a.showAll}
          </button>
        </Banner>
      )}
      {found.failure !== null && <ListFailed failure={found.failure} onRetry={found.retry} />}
      {found.loading && <Placeholder height={56} />}
      {found.loaded && found.items.length === 0 && <div className="empty">{a.none}</div>}
      {found.items.length > 0 && (
        <section className="panel">
          <div className="table-scroll" role="region" aria-label={a.table} tabIndex={0}>
            <table className="stock-table">
              <thead>
                <tr>
                  <th scope="col">{a.columns.when}</th>
                  <th scope="col">{a.columns.who}</th>
                  <th scope="col">{a.columns.what}</th>
                  <th scope="col">{a.columns.about}</th>
                  <th scope="col">{a.columns.reason}</th>
                </tr>
              </thead>
              <tbody>
                {found.items.map((event) => {
                  const said = details(event)
                  const page = link(event, demoMode)
                  const only = event.entity_id && (about?.id !== event.entity_id)
                  return (
                    <tr key={event.id}>
                      <td>{when(event.occurred_at)}</td>
                      <td>
                        <Who event={event} />
                      </td>
                      <th scope="row" className="audit-cell">
                        {sentence(event)}
                        {said.length > 0 && <p className="audit-change hint">{said.join(' · ')}</p>}
                      </th>
                      <td className="audit-cell">
                        {page && (
                          <Link to={page.to}>
                            {page.text}
                          </Link>
                        )}
                        {only && (
                          <>
                            {page && ' · '}
                            <button
                              type="button"
                              className="text-button audit-id"
                              aria-label={a.onlyLabel(thing(event.entity_type))}
                              onClick={() => choose('about', `${event.entity_type}:${event.entity_id}`)}
                            >
                              {a.only}
                            </button>
                          </>
                        )}
                      </td>
                      <td className="audit-cell">{event.reason}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <Pager paging={paging} total={found.total} settled={found.settled} />
    </main>
  )
}

/** AS-12, demo mode only: move the app's time forward to show what happens later. */
export function ClockPage() {
  const queryClient = useQueryClient()
  const clock = useDemoClock()
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<{ tone: 'green' | 'red'; text: string } | null>(null)

  async function advance(minutes: number) {
    setSaid(null)
    setBusy(true)
    try {
      const moved = await unwrap(api.POST('/api/v1/admin/demo-clock/advance', { body: { minutes, reason: c.reason } }))
      queryClient.setQueryData(['admin', 'clock'], moved)
      setSaid({ tone: 'green', text: c.moved })
    } catch (error) {
      setSaid({ tone: 'red', text: errorMessage(codeOf(error)) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="portal__main">
      <section className="panel" aria-labelledby="clock">
        <div>
          <h1 id="clock" className="page-title">
            {c.title}
          </h1>
          <span className="soft">{c.intro}</span>
        </div>
        {clock.data && (
          <div role="status" aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 20, fontWeight: 600 }}>{c.now(when(clock.data.server_now))}</span>
            <span className="soft">{c.ahead(clock.data.offset_minutes)}</span>
          </div>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {c.steps.map((step) => (
            <button
              key={step.minutes}
              type="button"
              className="pill-button pill-button--grey"
              disabled={busy}
              onClick={() => void advance(step.minutes)}
            >
              {step.label}
            </button>
          ))}
        </div>
        {said && <Banner tone={said.tone}>{said.text}</Banner>}
      </section>
    </main>
  )
}
