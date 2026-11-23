import { PasswordInput } from '@mantine/core'
import { type FormEvent, useEffect, useRef, useState } from 'react'

import { api, ApiFailure, unwrap } from '../../api/client'
import { useSession } from '../../api/session'
import { FormProblems } from '../../components/FormProblems'
import { Banner } from '../../components/layout'
import { strings } from '../../strings/en'
import { type Failure, failureMessage } from '../../strings/failure'
import { MAX } from './fields'

const m = strings.me

/** The refusals said on the password box; any other is said above the buttons. */
const ON_FIELD = ['NO_PASSWORD', 'INVALID_CREDENTIALS']

/**
 * "Delete my account" (R-AU10): the last section of the profile, quiet until it is
 * opened. Opened, it says what will happen before it asks for the password. A wrong
 * password is said on its box and logs nobody out; after the deletion the person is
 * forgotten in the one place that changes who is logged in, and the welcome page says
 * once that the account is deleted.
 */
export function DeleteAccount() {
  const { accountDeleted } = useSession()
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [sending, setSending] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)
  // Each refused try takes the focus back to the box (components/FormProblems.tsx).
  const [refusals, setRefusals] = useState(0)
  // The button that opens the form goes away when pressed: the focus moves into the form,
  // and back to that button on [Keep my account], never to the top of the page.
  const opener = useRef<HTMLButtonElement>(null)
  const box = useRef<HTMLInputElement>(null)
  const [moved, setMoved] = useState(false)
  useEffect(() => {
    if (!moved) return
    if (open) box.current?.focus()
    else opener.current?.focus()
  }, [open, moved])

  function refuse(refused: Failure) {
    setFailure(refused)
    setRefusals((count) => count + 1)
  }

  function show() {
    setMoved(true)
    setOpen(true)
  }

  function keep() {
    setOpen(false)
    setPassword('')
    setFailure(null)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!password) return refuse({ code: 'NO_PASSWORD' })
    setSending(true)
    setFailure(null)
    try {
      await unwrap(api.POST('/api/v1/me/delete-account', { body: { password } }))
    } catch (error) {
      setSending(false)
      // A wrong password answers 401 INVALID_CREDENTIALS, not UNAUTHENTICATED: the
      // person stays logged in (api/client.ts). A lock says how long to wait; a busy
      // moment keeps what was typed.
      refuse(
        error instanceof ApiFailure ? { code: error.code, details: error.details } : { code: 'INTERNAL_ERROR' },
      )
      return
    }
    accountDeleted()
  }

  const code = failure?.code
  const onField = code !== undefined && ON_FIELD.includes(code)
  return (
    <section className="row-card" aria-labelledby="delete-account">
      <h2 id="delete-account" className="card__title" style={{ margin: 0 }}>
        {m.deleteTitle}
      </h2>
      {!open ? (
        <button
          ref={opener}
          type="button"
          className="text-button"
          style={{ alignSelf: 'flex-start' }}
          onClick={show}
        >
          {m.deleteOpen}
        </button>
      ) : (
        <form className="form" onSubmit={submit} noValidate>
          <p style={{ margin: 0 }}>{m.deleteWhat}</p>
          <ul className="soft" style={{ margin: 0, paddingInlineStart: 20, lineHeight: 1.5 }}>
            {m.deleteLines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p style={{ margin: 0, fontWeight: 600 }}>{m.deleteFinal}</p>
          <PasswordInput
            ref={box}
            label={m.deletePassword}
            description={m.deletePasswordHint}
            size="md"
            autoComplete="current-password"
            maxLength={MAX.password}
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            error={(code === 'NO_PASSWORD' && m.deletePasswordMissing) || (code === 'INVALID_CREDENTIALS' && m.deleteWrong)}
          />
          <div role="status" aria-live="polite">
            {failure && !onField && <Banner tone="red">{failureMessage(failure)}</Banner>}
          </div>
          <FormProblems count={onField ? 1 : 0} attempt={refusals} />
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button type="submit" className="pill-button pill-button--danger" disabled={sending}>
              {m.deleteSubmit}
            </button>
            <button type="button" className="pill-button pill-button--grey" onClick={keep} disabled={sending}>
              {m.deleteKeep}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
