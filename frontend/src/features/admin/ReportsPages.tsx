import { NativeSelect } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { codeOf, type ReportState, saveText, useAnswerReport, useAnswerReports, when } from './data'

const s = strings.admin
const r = s.reports
const authors = s.escalations.authors
const reasons = strings.chat.report.reasons

type Detail = Schemas['AnswerReportDetail']
type Line = Schemas['ReportedLine']
type Category = Schemas['ConfirmReport']['category']

const STATES: ReportState[] = ['NEW', 'CONFIRMED', 'DISMISSED']
const CATEGORIES = Object.keys(r.categories) as Category[]

function reasonText(reason: string): string {
  return reasons[reason as keyof typeof reasons] ?? reason
}

/** AS-8: the replies clients marked as wrong. */
export function ReportsPage() {
  const [state, setState] = useState<ReportState>('NEW')
  const [exported, setExported] = useState<string | null>(null)
  const found = useAnswerReports(state)
  const items = found.data?.items ?? []

  async function download() {
    setExported(null)
    try {
      const { cases } = await unwrap(api.GET('/api/v1/admin/answer-reports/export'))
      saveText(JSON.stringify(cases, null, 2), 'regression_cases.json', 'application/json')
      setExported(r.exported(cases.length))
    } catch (error) {
      setExported(errorMessage(codeOf(error)))
    }
  }

  return (
    <main className="portal__main">
      <div className="row-card__top">
        <h1 className="page-title">{r.title}</h1>
        <button type="button" className="pill-button pill-button--grey" onClick={() => void download()}>
          {r.export}
        </button>
      </div>
      <div role="status" aria-live="polite">
        {exported && <Banner tone="grey">{exported}</Banner>}
      </div>
      <div className="tabs" role="tablist" aria-label={r.title}>
        {STATES.map((choice) => (
          <button
            key={choice}
            type="button"
            role="tab"
            aria-selected={state === choice}
            className="tabs__tab"
            onClick={() => setState(choice)}
          >
            {r.states[choice]}
          </button>
        ))}
      </div>
      {found.isSuccess && items.length === 0 && (
        <div className="empty">{state === 'NEW' ? r.none : r.noneOther}</div>
      )}
      {items.map((row) => (
        <article key={row.id} className="row-card">
          <Link to={`/admin/reports/${row.id}`} className="row-link">
            <div className="row-card__top">
              <span className="status-pill status-pill--amber">{reasonText(row.reason)}</span>
              <span className="hint">
                {when(row.created_at)}
                {row.in_regression && ` · ${r.inRegression}`}
              </span>
            </div>
            <span dir="auto">{row.reply}</span>
            {row.comment && (
              <span className="soft" style={{ fontSize: 15 }} dir="auto">
                {r.comment(row.comment)}
              </span>
            )}
          </Link>
        </article>
      ))}
    </main>
  )
}

function ShownLine({ line, reported = false }: { line: Line; reported?: boolean }) {
  const who = authors[line.author as keyof typeof authors] ?? line.author
  return (
    <div className={`thread-line${reported ? ' thread-line--reported' : ''}`} dir="auto">
      <span className="thread-line__who">{who}</span>
      {line.text && <span>{line.text}</span>}
      {line.cards.map((card, index) => (
        <span key={index} className="hint">
          {s.escalations.card(card.title ? `${card.type}: ${card.title}` : card.type)}
          {card.recommended && ` · ${strings.chat.recommended}`}
        </span>
      ))}
      {line.quick_replies.length > 0 && (
        <span className="hint">
          {r.chips}: {line.quick_replies.join(' · ')}
        </span>
      )}
    </div>
  )
}

/** One reported reply with what came before it, and the review: not a problem, or
 * confirmed under a category and, if wanted, added to the regression tests (SM-10). */
export function ReportPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const found = useAnswerReport(id)
  const [category, setCategory] = useState<Category>('understanding')
  const [regression, setRegression] = useState(true)
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<{ tone: 'green' | 'red' | 'amber'; text: string } | null>(null)

  if (found.isError) {
    return (
      <main className="portal__main">
        <Banner tone="amber">{errorMessage(codeOf(found.error))}</Banner>
        <Link to="/admin/reports" className="text-button">
          {s.back}
        </Link>
      </main>
    )
  }
  if (!found.data) return <p className="soft">{strings.common.loading}</p>
  const { report, reply, context, run } = found.data
  const path = { report_id: id }

  async function act(call: () => Promise<Detail>) {
    setSaid(null)
    setBusy(true)
    try {
      queryClient.setQueryData(['admin', 'report', id], await call())
      setSaid({ tone: 'green', text: r.reviewed })
    } catch (error) {
      const code = codeOf(error)
      setSaid({ tone: code === 'CHANGED_SINCE' ? 'amber' : 'red', text: code === 'CHANGED_SINCE' ? s.changed : errorMessage(code) })
      await queryClient.invalidateQueries({ queryKey: ['admin', 'report', id] })
    } finally {
      setBusy(false)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'reports'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'overview'] })
    }
  }

  return (
    <div className="portal__columns">
      <main className="portal__main">
        <Link to="/admin/reports" className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
          {s.back}
        </Link>
        <section className="panel" aria-labelledby="reported">
          <div className="row-card__top">
            <h1 id="reported" className="panel__title">
              {r.reported}
            </h1>
            <span className="status-pill status-pill--amber">{reasonText(report.reason)}</span>
          </div>
          {report.comment && (
            <Banner tone="grey">
              <span dir="auto">{r.comment(report.comment)}</span>
            </Banner>
          )}
          {context.length > 0 && <span className="hint">{r.before}</span>}
          <div>
            {context.map((line) => (
              <ShownLine key={line.seq} line={line} />
            ))}
          </div>
          <ShownLine line={reply} reported />
        </section>
      </main>

      <aside className="portal__aside">
        <div role="status" aria-live="polite">
          {said && <Banner tone={said.tone}>{said.text}</Banner>}
        </div>
        <section className="panel" aria-labelledby="review">
          <div className="row-card__top">
            <h2 id="review" className="panel__title">
              {r.states[report.state]}
            </h2>
            {report.in_regression && <span className="status-pill status-pill--blue">{r.inRegression}</span>}
          </div>
          {report.category && (
            <span className="soft">
              {r.category}: {r.categories[report.category as Category] ?? report.category}
            </span>
          )}
          {report.state === 'NEW' && (
            <>
              <NativeSelect
                label={r.category}
                size="md"
                value={category}
                onChange={(event) => setCategory(event.currentTarget.value as Category)}
                data={CATEGORIES.map((value) => ({ value, label: r.categories[value] }))}
              />
              <label style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 44 }}>
                <input
                  type="checkbox"
                  checked={regression}
                  onChange={(event) => setRegression(event.currentTarget.checked)}
                />
                {r.regression}
              </label>
              <button
                type="button"
                className="pill-button"
                disabled={busy}
                onClick={() =>
                  void act(() =>
                    unwrap(
                      api.POST('/api/v1/admin/answer-reports/{report_id}/confirm', {
                        params: { path },
                        body: { category, add_to_regression: regression },
                      }),
                    ),
                  )
                }
              >
                {r.confirm}
              </button>
              <button
                type="button"
                className="pill-button pill-button--grey"
                disabled={busy}
                onClick={() =>
                  void act(() => unwrap(api.POST('/api/v1/admin/answer-reports/{report_id}/dismiss', { params: { path } })))
                }
              >
                {r.dismiss}
              </button>
            </>
          )}
        </section>
        {run && (
          <section className="panel" aria-labelledby="run">
            <h2 id="run" className="panel__title">
              {r.run}
            </h2>
            <dl className="card__lines">
              <div className="card__line">
                <dt>{r.model}</dt>
                <dd>{run.model}</dd>
              </div>
              <div className="card__line">
                <dt>{r.prompt}</dt>
                <dd>{run.prompt_version}</dd>
              </div>
              <div className="card__line">
                <dt>{r.guards}</dt>
                <dd>{run.guardrails.join(', ') || r.noGuards}</dd>
              </div>
              <div className="card__line">
                <dt>{r.trace}</dt>
                <dd className="audit-change">{run.trace_id ?? r.noTrace}</dd>
              </div>
            </dl>
          </section>
        )}
      </aside>
    </div>
  )
}
