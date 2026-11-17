import { type FormEvent, useEffect, useRef, useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../../api/client'
import { ThumbDownIcon } from '../../../components/icons'
import { Banner } from '../../../components/layout'
import { errorMessage, strings } from '../../../strings/en'

const s = strings.chat.report

type Reason = Schemas['ReportAnswer']['reason']
const REASONS = Object.keys(s.reasons) as Reason[]
const MAX_COMMENT = 500

/**
 * The thumbs-down under a reply of the assistant (docs/11 §6, docs/03 CS-9): a reason, a
 * few words if the client wants, and DawaLink's team looks at the reply. Once per reply.
 */
export function ReportAnswer({
  conversationId,
  seq,
  reported,
}: {
  conversationId: string
  seq: number
  reported: boolean
}) {
  const [state, setState] = useState<'closed' | 'open' | 'sending' | 'sent'>(reported ? 'sent' : 'closed')
  const [reason, setReason] = useState<Reason | null>(null)
  const [comment, setComment] = useState('')
  const [failed, setFailed] = useState<string | null>(null)
  const form = useRef<HTMLFormElement>(null)
  // The form opens at the bottom of the chat, half behind the message box: bring it up.
  useEffect(() => {
    if (state === 'open') form.current?.scrollIntoView?.({ block: 'nearest' })
  }, [state])

  async function send(event: FormEvent) {
    event.preventDefault()
    if (!reason) return
    setFailed(null)
    setState('sending')
    try {
      await unwrap(
        api.POST('/api/v1/conversations/{conversation_id}/messages/{seq}/report', {
          params: { path: { conversation_id: conversationId, seq } },
          body: { reason, comment: comment.trim() || null },
        }),
      )
      setState('sent')
    } catch (error) {
      const code = error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
      // Reported from another tab or device: it is reported all the same.
      if (code === 'ALREADY_REPORTED') return setState('sent')
      setFailed(code)
      setState('open')
    }
  }

  if (state === 'sent') return <span className="hint">{s.thanks}</span>
  if (state === 'closed') {
    return (
      <button type="button" className="report-button" aria-label={s.open} onClick={() => setState('open')}>
        <ThumbDownIcon small />
      </button>
    )
  }
  return (
    <form ref={form} className="report-form" onSubmit={send}>
      <div className="chips" role="group" aria-label={s.title}>
        {REASONS.map((choice) => (
          <button
            key={choice}
            type="button"
            className="chip"
            aria-pressed={reason === choice}
            onClick={() => setReason(choice)}
          >
            {s.reasons[choice]}
          </button>
        ))}
      </div>
      <label htmlFor={`report-${seq}`} style={{ fontSize: 15 }}>
        {s.comment}
      </label>
      <textarea
        id={`report-${seq}`}
        className="text-area"
        dir="auto"
        maxLength={MAX_COMMENT}
        aria-describedby={`report-hint-${seq}`}
        value={comment}
        onChange={(event) => setComment(event.currentTarget.value)}
      />
      <span id={`report-hint-${seq}`} className="hint">
        {s.commentHint}
      </span>
      {failed && (
        <Banner tone="red" alert>
          {errorMessage(failed)}
        </Banner>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <button type="submit" className="pill-button" disabled={!reason || state === 'sending'}>
          {s.send}
        </button>
        <button type="button" className="text-button" onClick={() => setState('closed')}>
          {s.cancel}
        </button>
      </div>
    </form>
  )
}
