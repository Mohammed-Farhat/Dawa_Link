import { NativeSelect, TextInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { Placeholder } from '../../components/Placeholder'
import { errorMessage, strings } from '../../strings/en'
import { codeOf, useAudit, useDemoClock, when } from './data'
import { ListFailed } from './ListFailed'

const s = strings.admin
const a = s.audit
const c = s.clock

type Event = Schemas['AuditRow']

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** "PENDING → APPROVED", or the facts the event holds, as written in the log. */
function change(event: Event): string {
  const show = (side: Event['before']) =>
    side
      ? Object.entries(side)
          .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
          .join(', ')
      : ''
  return [show(event.before), show(event.after)].filter(Boolean).join(' → ')
}

/** AS-11: who changed what. Read-only: no button here changes anything. */
export function AuditPage() {
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [entity, setEntity] = useState('')
  // Only a whole ID is asked for: half of one matches nothing.
  const wanted = UUID.test(entity.trim()) ? entity.trim() : ''
  const found = useAudit({ action, actor, entity: wanted })
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
          value={action}
          onChange={(event) => setAction(event.currentTarget.value)}
          data={Object.entries(a.kinds).map(([value, label]) => ({ value, label }))}
        />
        <NativeSelect
          label={a.actor}
          size="md"
          value={actor}
          onChange={(event) => setActor(event.currentTarget.value)}
          data={Object.entries(a.actors).map(([value, label]) => ({ value, label }))}
        />
        <TextInput
          label={a.entity}
          size="md"
          autoComplete="off"
          style={{ flex: '1 1 320px' }}
          value={entity}
          onChange={(event) => setEntity(event.currentTarget.value)}
        />
      </div>
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
                  <th scope="col">{a.columns.action}</th>
                  <th scope="col">{a.columns.what}</th>
                  <th scope="col">{a.columns.change}</th>
                  <th scope="col">{a.columns.reason}</th>
                </tr>
              </thead>
              <tbody>
                {found.items.map((event) => (
                  <tr key={event.id}>
                    <td>{when(event.occurred_at)}</td>
                    <td>{a.actors[event.actor_type as keyof typeof a.actors] ?? event.actor_type}</td>
                    <th scope="row">{event.action}</th>
                    <td>
                      {event.entity_type}{' '}
                      {event.entity_id && (
                        <button
                          type="button"
                          className="text-button audit-id"
                          onClick={() => setEntity(event.entity_id ?? '')}
                        >
                          {event.entity_id.slice(0, 8)}
                        </button>
                      )}
                    </td>
                    <td className="audit-cell">
                      <p className="audit-change">{change(event)}</p>
                    </td>
                    <td className="audit-cell">{event.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {found.hasMore && (
        <button type="button" className="text-button" onClick={found.more}>
          {s.more}
        </button>
      )}
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
