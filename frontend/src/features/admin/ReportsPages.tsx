import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { codeOf, type ReportState, useAnswerReports, when } from './data'

const s = strings.admin
const r = s.reports
const reasons = strings.chat.report.reasons

type Row = Schemas['AnswerReportRow']

const STATES: ReportState[] = ['NEW', 'CONFIRMED', 'DISMISSED']

function reasonText(reason: string): string {
  return reasons[reason as keyof typeof reasons] ?? reason
}

/**
 * AS-8, as the owner chose it (2026-11-19): one list. Each row is a reply a client
 * marked with a thumbs-down, with their reason and the message it answered, and two
 * buttons. "Real problem" keeps the reply as a regression case (A-D6): nothing to file,
 * nothing to download here.
 */
export function ReportsPage() {
  const queryClient = useQueryClient()
  const [state, setState] = useState<ReportState>('NEW')
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<{ tone: 'green' | 'red' | 'amber'; text: string } | null>(null)
  const found = useAnswerReports(state)
  const items = found.data?.items ?? []

  async function review(row: Row, real: boolean) {
    setSaid(null)
    setBusy(true)
    const params = { path: { report_id: row.id } }
    try {
      await unwrap(
        real
          ? api.POST('/api/v1/admin/answer-reports/{report_id}/confirm', {
              params,
              body: { category: 'other', add_to_regression: true },
            })
          : api.POST('/api/v1/admin/answer-reports/{report_id}/dismiss', { params }),
      )
      setSaid({ tone: 'green', text: r.reviewed })
    } catch (error) {
      const code = codeOf(error)
      setSaid({ tone: code === 'CHANGED_SINCE' ? 'amber' : 'red', text: code === 'CHANGED_SINCE' ? s.changed : errorMessage(code) })
    } finally {
      setBusy(false)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'reports'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'overview'] })
    }
  }

  return (
    <main className="portal__main">
      <div>
        <h1 className="page-title">{r.title}</h1>
        <span className="soft">{r.intro}</span>
      </div>
      <div className="tabs" role="tablist" aria-label={r.title}>
        {STATES.map((choice) => (
          <button
            key={choice}
            type="button"
            role="tab"
            aria-selected={state === choice}
            className="tabs__tab"
            onClick={() => {
              setSaid(null)
              setState(choice)
            }}
          >
            {r.states[choice]}
          </button>
        ))}
      </div>
      <div role="status" aria-live="polite">
        {said && <Banner tone={said.tone}>{said.text}</Banner>}
      </div>
      {found.isSuccess && items.length === 0 && (
        <div className="empty">{state === 'NEW' ? r.none : r.noneOther}</div>
      )}
      {items.map((row) => (
        <article key={row.id} className="row-card" aria-label={reasonText(row.reason)}>
          <div className="row-card__top">
            <span className="status-pill status-pill--amber">{reasonText(row.reason)}</span>
            <span className="hint">{when(row.created_at)}</span>
          </div>
          {row.comment && (
            <span className="soft" style={{ fontSize: 15 }} dir="auto">
              {r.comment(row.comment)}
            </span>
          )}
          <div>
            {row.asked && (
              <div className="thread-line" dir="auto">
                <span className="thread-line__who">{r.asked}</span>
                <span>{row.asked}</span>
              </div>
            )}
            <div className="thread-line thread-line--reported" dir="auto">
              <span className="thread-line__who">{r.answered}</span>
              <span style={{ whiteSpace: 'pre-wrap' }}>{row.reply}</span>
            </div>
          </div>
          {row.state === 'NEW' && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
              <button type="button" className="pill-button" disabled={busy} onClick={() => void review(row, true)}>
                {r.confirm}
              </button>
              <button
                type="button"
                className="pill-button pill-button--grey"
                disabled={busy}
                onClick={() => void review(row, false)}
              >
                {r.dismiss}
              </button>
            </div>
          )}
        </article>
      ))}
    </main>
  )
}
