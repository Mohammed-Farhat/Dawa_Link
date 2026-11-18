import { TextInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { lbp } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { codeOf, useAdminHealth, useCatalog, useCatalogImports, useFlags, when } from './data'

const s = strings.admin
const h = s.health
const f = s.flags
const k = s.catalog

type Numbers = Record<string, unknown>

function number(value: unknown): string {
  return typeof value === 'number' ? value.toLocaleString('en') : h.none
}

function share(value: unknown): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : h.none
}

function seconds(value: unknown): string {
  return typeof value === 'number' ? `${(value / 1000).toFixed(1)} s` : h.none
}

function dollars(value: unknown): string {
  return typeof value === 'number' ? `$${value.toFixed(2)}` : h.none
}

function Facts({ title, id, rows }: { title: string; id: string; rows: [string, string][] }) {
  return (
    <section className="panel" aria-labelledby={id}>
      <h2 id={id} className="panel__title">
        {title}
      </h2>
      <dl className="card__lines">
        {rows.map(([label, value]) => (
          <div key={label} className="card__line">
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/** AS-2 and AS-10: how the agent and the system are doing, from our own tables, and the
 * alerts that fire right now. */
export function HealthPage() {
  const [days, setDays] = useState(7)
  const found = useAdminHealth(days)
  if (found.isError) return <Banner tone="amber">{errorMessage(codeOf(found.error))}</Banner>
  if (!found.data) return <p className="soft">{strings.common.loading}</p>
  const agent = found.data.agent as Numbers
  const requests = found.data.requests as Numbers
  const market = found.data.marketplace as Numbers
  const system = found.data.system as Numbers
  const escalations = Object.entries((requests.escalations_by_reason ?? {}) as Record<string, number>)
  return (
    <main className="portal__main">
      <div className="row-card__top">
        <h1 className="page-title">{h.title}</h1>
        <div className="tabs" role="tablist" aria-label={h.period}>
          {[1, 7, 30].map((choice) => (
            <button
              key={choice}
              type="button"
              role="tab"
              aria-selected={days === choice}
              className="tabs__tab"
              onClick={() => setDays(choice)}
            >
              {h.days(choice)}
            </button>
          ))}
        </div>
      </div>
      <div role="status" aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {found.data.alerts.length === 0 && <Banner tone="green">{h.noAlerts}</Banner>}
        {found.data.alerts.map((alert) => (
          <Banner key={alert} tone="red" alert>
            {h.alerts[alert as keyof typeof h.alerts] ?? alert}
          </Banner>
        ))}
      </div>
      <div className="portal__columns">
        <div className="portal__main">
          <Facts
            id="agent"
            title={h.agent}
            rows={[
              [h.turns, number(agent.turns)],
              [h.latency, `${seconds(agent.latency_p50_ms)} · ${seconds(agent.latency_p95_ms)}`],
              [h.errors, `${number(agent.errors)} (${share(agent.error_rate)})`],
              [h.fallbacks, number(agent.fallbacks)],
              [h.guards, number(agent.guardrail_triggers)],
              [h.tools, `${number(agent.tool_calls)} · ${number(agent.tool_errors)}`],
              [h.tokens, `${number(agent.tokens_in)} · ${number(agent.tokens_out)}`],
              [h.cost, dollars(agent.cost_usd)],
              [h.month, `${dollars(agent.month_spend_usd)} / ${dollars(agent.month_budget_usd)}`],
              [h.model, typeof agent.model === 'string' ? agent.model : h.none],
              [h.prompt, typeof agent.prompt_version === 'string' ? agent.prompt_version : h.none],
            ]}
          />
          <Facts
            id="requests"
            title={h.requests}
            rows={[
              [h.closed, number(requests.closed)],
              [h.fulfilled, share(requests.fulfilled_share)],
              [h.replans, typeof requests.replans_per_request === 'number' ? String(requests.replans_per_request) : h.none],
              [h.earlyRelease, `${number(requests.early_release_asked)} · ${number(requests.early_release_accepted)}`],
              [h.perFulfilled, dollars(requests.cost_per_fulfilled_usd)],
              ...escalations.map(
                ([reason, count]): [string, string] => [
                  `${h.escalated}: ${s.escalations.reasons[reason as keyof typeof s.escalations.reasons] ?? reason}`,
                  String(count),
                ],
              ),
            ]}
          />
        </div>
        <div className="portal__aside">
          <Facts
            id="market"
            title={h.marketplace}
            rows={[
              [h.reservations, number(market.reservations)],
              [h.pickedUp, share(market.picked_up_share)],
              [h.notAvailable, share(market.not_available_share)],
              [h.noShows, share(market.no_show_share)],
              [h.unitsSaved, number(market.units_saved)],
            ]}
          />
          <Facts
            id="system"
            title={h.system}
            rows={[
              [h.clockLate, h.secondsLate(Number(system.clock_check_late_s ?? 0))],
              [h.turnsWaiting, number(system.turns_waiting)],
              [h.turnsStuck, number(system.turns_stuck)],
              [h.emailsFailed, number(system.emails_failed)],
            ]}
          />
        </div>
      </div>
    </main>
  )
}

/** AS-7: what code flagged for a person to look at. A flag holds counts, never a message. */
export function FlagsPage() {
  const queryClient = useQueryClient()
  const found = useFlags()
  const [reason, setReason] = useState('')
  const [said, setSaid] = useState<{ tone: 'green' | 'red' | 'amber'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const items = found.data?.items ?? []

  async function act(call: () => Promise<Schemas['AbuseFlagRow']>) {
    setSaid(null)
    setBusy(true)
    try {
      await call()
      setSaid({ tone: 'green', text: f.done })
      setReason('')
    } catch (error) {
      const code = codeOf(error)
      setSaid({ tone: code === 'CHANGED_SINCE' ? 'amber' : 'red', text: code === 'CHANGED_SINCE' ? s.changed : errorMessage(code) })
    } finally {
      setBusy(false)
      void queryClient.invalidateQueries({ queryKey: ['admin'] })
    }
  }

  const off = busy || !reason.trim()
  return (
    <main className="portal__main">
      <div>
        <h1 className="page-title">{f.title}</h1>
        <span className="soft">{f.intro}</span>
      </div>
      <div role="status" aria-live="polite">
        {said && <Banner tone={said.tone}>{said.text}</Banner>}
      </div>
      {found.isSuccess && items.length === 0 && <div className="empty">{f.none}</div>}
      {items.length > 0 && (
        <TextInput
          label={s.reason}
          description={s.reasonHint}
          size="md"
          maxLength={300}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
      )}
      {items.map((flag) => {
        const path = { flag_id: flag.id }
        const subject =
          flag.subject_type === 'client' ? `/admin/clients/${flag.subject_id}` : `/admin/pharmacies/${flag.subject_id}`
        return (
          <article key={flag.id} className="row-card" aria-label={f.rules[flag.rule as keyof typeof f.rules] ?? flag.rule}>
            <div className="row-card__top">
              <h2 className="card__title" style={{ margin: 0 }}>
                {f.rules[flag.rule as keyof typeof f.rules] ?? flag.rule}
              </h2>
              <span className={`status-pill status-pill--${flag.severity === 'high' ? 'red' : 'grey'}`}>
                {f.severity[flag.severity]}
              </span>
            </div>
            <span className="soft" style={{ fontSize: 15 }}>
              {f.raised(when(flag.created_at))} ·{' '}
              {Object.entries(flag.evidence)
                .filter(([, value]) => typeof value === 'number')
                .map(([key, value]) => `${f.evidence[key as keyof typeof f.evidence] ?? key}: ${String(value)}`)
                .join(' · ')}
            </span>
            <Link to={subject} className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
              {flag.subject_type === 'client' ? f.openClient : f.openPharmacy}
            </Link>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
              <button
                type="button"
                className="pill-button pill-button--grey"
                disabled={off}
                onClick={() =>
                  void act(() =>
                    unwrap(api.POST('/api/v1/admin/abuse-flags/{flag_id}/dismiss', { params: { path }, body: { reason } })),
                  )
                }
              >
                {f.dismiss}
              </button>
              <button
                type="button"
                className="pill-button pill-button--grey"
                disabled={off}
                onClick={() =>
                  void act(() =>
                    unwrap(
                      api.POST('/api/v1/admin/abuse-flags/{flag_id}/act', { params: { path }, body: { action: 'warn', reason } }),
                    ),
                  )
                }
              >
                {f.warn}
              </button>
              <button
                type="button"
                className="pill-button pill-button--danger"
                disabled={off}
                onClick={() =>
                  void act(() =>
                    unwrap(
                      api.POST('/api/v1/admin/abuse-flags/{flag_id}/act', { params: { path }, body: { action: 'suspend', reason } }),
                    ),
                  )
                }
              >
                {f.suspend}
              </button>
            </div>
            <p className="hint">{f.warnHint}</p>
          </article>
        )
      })}
    </main>
  )
}

/** AS-9: the catalog as imported, to read. It changes by the import script only. */
export function CatalogPage() {
  const [typed, setTyped] = useState('')
  const found = useCatalog(typed.trim())
  const imports = useCatalogImports()
  const latest = imports.data?.items[0]
  return (
    <main className="portal__main">
      <div>
        <h1 className="page-title">{k.title}</h1>
        <span className="soft">{k.intro}</span>
      </div>
      {latest && (
        <Banner tone="grey">{k.source(latest.file_name, latest.source_date, latest.rows_imported, latest.rows_total)}</Banner>
      )}
      <TextInput
        label={k.search}
        size="md"
        autoComplete="off"
        value={typed}
        onChange={(event) => setTyped(event.currentTarget.value)}
      />
      {found.loaded && found.items.length === 0 && <div className="empty">{k.none}</div>}
      {found.items.length > 0 && (
        <section className="panel">
          <div className="table-scroll" role="region" aria-label={k.table} tabIndex={0}>
            <table className="stock-table">
              <thead>
                <tr>
                  <th scope="col">{k.columns.name}</th>
                  <th scope="col">{k.columns.code}</th>
                  <th scope="col">{k.columns.pack}</th>
                  <th scope="col">{k.columns.price}</th>
                  <th scope="col">{k.columns.flags}</th>
                  <th scope="col">{k.columns.same}</th>
                </tr>
              </thead>
              <tbody>
                {found.items.map((product) => (
                  <tr key={product.id}>
                    <th scope="row">
                      {product.name}
                      {product.strength && <span className="hint"> · {product.strength}</span>}
                    </th>
                    <td>{product.code}</td>
                    <td>{[product.form, product.pack].filter(Boolean).join(' ')}</td>
                    <td>{lbp(product.public_price_lbp)}</td>
                    <td>
                      {product.controlled ? (
                        <span className="status-pill status-pill--red">{k.controlled}</span>
                      ) : (
                        <span className="status-pill status-pill--grey">
                          {product.prescription_required ? k.prescription : k.noPrescription}
                        </span>
                      )}
                    </td>
                    <td>{product.same_medicine > 1 ? k.same(product.same_medicine - 1) : k.alone}</td>
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
