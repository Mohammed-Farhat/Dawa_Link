import { PasswordInput } from '@mantine/core'
import { type FormEvent, useState } from 'react'

import { api, ApiFailure, unwrap } from '../api/client'
import { errorMessage, strings } from '../strings/en'
import { type Failure, failureMessage } from '../strings/failure'
import { FormProblems } from './FormProblems'
import { Banner } from './layout'
import { passwordGaps } from './passwordRule'
import { PasswordRules, PasswordRulesSaid } from './PasswordRules'

const s = strings.password

// The API's bound on a password (`ChangePassword` in the API's schemas).
const PASSWORD_MAX = 200

/** The refusals said on a field of their own; any other is said above the button. */
const ON_FIELDS = ['NO_CURRENT', 'INVALID_CREDENTIALS', 'WEAK_PASSWORD']

/** The API refused the new password as one of the most common ones (R-AU1). */
function tooCommon(failure: Failure | null): boolean {
  const missing = failure?.details?.missing
  return Array.isArray(missing) && missing.includes('uncommon')
}

/** A new password. Every other device of this account is logged out (R-AU3). */
export function ChangePassword() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'done' | 'refused'>('idle')
  const [failure, setFailure] = useState<Failure | null>(null)
  // Counts the refused tries, so each one takes the focus to the field to correct, as
  // every other form does (components/FormProblems.tsx).
  const [refusals, setRefusals] = useState(0)

  function refuse(refused: Failure) {
    setState('refused')
    setFailure(refused)
    setRefusals((count) => count + 1)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    // Each field says what is wrong with itself (B#2).
    if (!current) return refuse({ code: 'NO_CURRENT' })
    if (passwordGaps(next).length > 0) return refuse({ code: 'WEAK_PASSWORD' })
    setState('sending')
    setFailure(null)
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
      // A wrong current password is said on its field, and the person stays logged in:
      // only the API's own "session ended" logs out (A#11). A locked account (after five
      // wrong ones) says how long to wait; a busy server keeps what was typed.
      refuse(
        error instanceof ApiFailure
          ? { code: error.code, details: error.details }
          : { code: 'INTERNAL_ERROR' },
      )
    }
  }

  const code = state === 'refused' ? failure?.code : undefined
  const onField = code !== undefined && ON_FIELDS.includes(code)
  return (
    <form className="form" onSubmit={submit} noValidate>
      <PasswordInput
        label={s.current}
        size="md"
        autoComplete="current-password"
        maxLength={PASSWORD_MAX}
        value={current}
        onChange={(event) => setCurrent(event.currentTarget.value)}
        error={(code === 'NO_CURRENT' && s.currentMissing) || (code === 'INVALID_CREDENTIALS' && s.wrong)}
      />
      <PasswordInput
        label={s.new}
        description={
          <>
            {s.hint}
            <span className="sr-only">
              {' '}
              <PasswordRulesSaid password={next} />
            </span>
          </>
        }
        size="md"
        autoComplete="new-password"
        maxLength={PASSWORD_MAX}
        value={next}
        onChange={(event) => setNext(event.currentTarget.value)}
        // A common password meets the rule's checklist: the API says which it was.
        error={code === 'WEAK_PASSWORD' && (tooCommon(failure) ? s.common : errorMessage('WEAK_PASSWORD'))}
      />
      <PasswordRules password={next} />
      <div role="status" aria-live="polite">
        {state === 'done' && <Banner tone="green">{s.done}</Banner>}
        {code !== undefined && !onField && failure && <Banner tone="red">{failureMessage(failure)}</Banner>}
      </div>
      <FormProblems count={onField ? 1 : 0} attempt={refusals} />
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
