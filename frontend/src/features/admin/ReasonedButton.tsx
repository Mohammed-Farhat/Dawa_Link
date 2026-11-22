import { TextInput } from '@mantine/core'
import { type FormEvent, useEffect, useRef, useState } from 'react'

import { strings } from '../../strings/en'

const s = strings.admin

type Props = {
  label: string
  /** What the button says once the reason is typed, when it differs from `label`. */
  confirm?: string
  /** `outline` is for a button that stands on a grey card, where grey would not show. */
  tone?: 'grey' | 'outline' | 'danger' | 'plain'
  disabled?: boolean
  /** Does the thing, with the reason. The box closes when it answers `true`. */
  onConfirm: (reason: string) => Promise<boolean>
}

/**
 * A button whose action needs a reason for the audit log. Pressing it opens the question
 * where the button is: a reason box somewhere else on the page left the button grey with
 * nothing beside it to say why (the owner's findings, 2026-11-19).
 */
export function ReasonedButton({ label, confirm, tone = 'grey', disabled = false, onConfirm }: Props) {
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const opener = useRef<HTMLButtonElement>(null)
  const wasAsking = useRef(false)
  const look = tone === 'plain' ? 'pill-button' : `pill-button pill-button--${tone}`

  // When the question closes, the focus goes back to the button that opened it: without
  // this it fell to the top of the page (WCAG 2.4.3). Never on the first showing.
  useEffect(() => {
    if (wasAsking.current && !asking) opener.current?.focus()
    wasAsking.current = asking
  }, [asking])

  if (!asking) {
    return (
      <button
        ref={opener}
        type="button"
        className={look}
        style={{ alignSelf: 'flex-start' }}
        disabled={disabled}
        onClick={() => setAsking(true)}
      >
        {label}
      </button>
    )
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      if (await onConfirm(reason.trim())) {
        setAsking(false)
        setReason('')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form" onSubmit={send}>
      <TextInput
        label={s.why(label)}
        description={s.reasonHint}
        size="md"
        maxLength={300}
        autoComplete="off"
        autoFocus
        value={reason}
        onChange={(event) => setReason(event.currentTarget.value)}
      />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <button type="submit" className={look} disabled={busy || !reason.trim()}>
          {confirm ?? label}
        </button>
        <button
          type="button"
          className="text-button"
          onClick={() => {
            setReason('')
            setAsking(false)
          }}
        >
          {s.cancel}
        </button>
      </div>
    </form>
  )
}
