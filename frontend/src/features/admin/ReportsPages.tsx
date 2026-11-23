import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, type Schemas, unwrap } from '../../api/client'
import { Pager } from '../../components/Pager'
import { Placeholder } from '../../components/Placeholder'
import { usePage } from '../../components/usePage'
import { langOf } from '../../format'
import { strings } from '../../strings/en'
import { type Note, oneOf, refusal, type ReportState, useAnswerReports, when } from './data'
import { ListFailed } from './ListFailed'
import { Said } from './said'

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
  // The tab and the page live in the address: "Back" finds the list as it was left.
  const paging = usePage()
  const state = oneOf(paging.params.get('state'), STATES, 'NEW') as ReportState
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<Note | null>(null)
  const found = useAnswerReports(state, paging.offset)
  const items = found.data?.items ?? []
  // A refusal is said under the answer it is about, while that answer is listed.
  const present = items.map((row) => row.id)

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
      setSaid(refusal(error, row.id))
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
      <div className="tabs tabs--wrap" role="tablist" aria-label={r.title}>
        {STATES.map((choice) => (
          <button
            key={choice}
            type="button"
            role="tab"
            aria-selected={state === choice}
            className="tabs__tab"
            onClick={() => {
              setSaid(null)
              paging.choose('state', choice === 'NEW' ? null : choice)
            }}
          >
            {r.states[choice]}
          </button>
        ))}
      </div>
      <Said note={said} present={present} />
      {found.isError && <ListFailed failure={found.error} onRetry={() => void found.refetch()} />}
      {found.isPending && <Placeholder />}
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
            <span className="soft" style={{ fontSize: 15 }}>
              {r.commentLabel}{' '}
              <span dir="auto" lang={langOf(row.comment)}>
                {row.comment}
              </span>
            </span>
          )}
          {/* The direction is the message's own, not that of the English label above it. */}
          <div>
            {row.asked && (
              <div className="thread-line">
                <span className="thread-line__who">{r.asked}</span>
                <span dir="auto" lang={langOf(row.asked)}>
                  {row.asked}
                </span>
              </div>
            )}
            <div className="thread-line thread-line--reported">
              <span className="thread-line__who">{r.answered}</span>
              <span dir="auto" lang={langOf(row.reply)} style={{ whiteSpace: 'pre-wrap' }}>
                {row.reply}
              </span>
            </div>
          </div>
          <Said note={said} at={row.id} />
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
      <Pager paging={paging} total={found.data?.total} settled={!found.isPlaceholderData} />
    </main>
  )
}
