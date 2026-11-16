import { PasswordInput } from '@mantine/core'
import { type FormEvent, useState } from 'react'

import { api, ApiFailure, unwrap } from '../api/client'
import { errorMessage, strings } from '../strings/en'
import { Banner } from './layout'

const s = strings.password

/** A new password. Every other device of this account is logged out (R-AU3). */
export function ChangePassword() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'done' | string>('idle')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!current || next.length < 10) {
      setState('WEAK_PASSWORD')
      return
    }
    setState('sending')
    try {
      await unwrap(
        api.POST('/api/v1/auth/password', {
          body: { current_password: current, new_password: next },
        }),
      )
      setCurrent('')
      setNext('')
      setState('done')
    } catch (error) {
      setState(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
    }
  }

  const refused = !['idle', 'sending', 'done'].includes(state)
  return (
    <form className="form" onSubmit={submit} noValidate>
      <PasswordInput
        label={s.current}
        size="md"
        autoComplete="current-password"
        value={current}
        onChange={(event) => setCurrent(event.currentTarget.value)}
        error={state === 'INVALID_CREDENTIALS' && s.wrong}
      />
      <PasswordInput
        label={s.new}
        description={s.hint}
        size="md"
        autoComplete="new-password"
        value={next}
        onChange={(event) => setNext(event.currentTarget.value)}
        error={state === 'WEAK_PASSWORD' && errorMessage('WEAK_PASSWORD')}
      />
      <div role="status" aria-live="polite">
        {state === 'done' && <Banner tone="green">{s.done}</Banner>}
        {refused && state !== 'INVALID_CREDENTIALS' && state !== 'WEAK_PASSWORD' && (
          <Banner tone="red">{errorMessage(state)}</Banner>
        )}
      </div>
      <button
        type="submit"
        className="pill-button pill-button--grey"
        style={{ alignSelf: 'flex-start' }}
        disabled={state === 'sending'}
      >
        {s.submit}
      </button>
    </form>
  )
}
