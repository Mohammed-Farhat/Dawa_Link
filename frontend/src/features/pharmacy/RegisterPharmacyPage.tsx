import { Checkbox, PasswordInput, TextInput } from '@mantine/core'
import { type FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, ApiFailure, unwrap } from '../../api/client'
import { FormProblems } from '../../components/FormProblems'
import { BackIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { passwordGaps } from '../../components/passwordRule'
import { PasswordRules } from '../../components/PasswordRules'
import { errorMessage, strings } from '../../strings/en'
import { type Failure, failureMessage } from '../../strings/failure'
import { useDistricts } from '../client/data'
import { MAX } from '../client/fields'
import { DetailsFields } from './details'
import { bodyOf, emptyDraft, problemsOf } from './draft'

const s = strings.pharmacy.register
const EMAIL_SHAPE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
/** The fields the form can show the API's refusal on; any other refusal (the pickup
 * days, which are chips; the terms) is said above the button, never lost (A#35). */
const SHOWN_ON_A_FIELD = new Set(['email', ...Object.keys(problemsOf(emptyDraft()))])

/**
 * PS-1: a pharmacy registers itself and its one account. The answer is always "check
 * your email" (R-AU7); the registration reaches DawaLink's team once the email is
 * confirmed.
 */
export default function RegisterPharmacyPage() {
  const navigate = useNavigate()
  const districts = useDistricts()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [draft, setDraft] = useState(emptyDraft)
  const [terms, setTerms] = useState(false)
  const [tried, setTried] = useState(false)
  // Each refused submit, by the form or by the API: the focus goes to the first mistake.
  const [attempt, setAttempt] = useState(0)
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<(Failure & { field: string | null }) | null>(null)

  const problems = {
    email: EMAIL_SHAPE.test(email.trim()) ? null : s.emailProblem,
    password: passwordGaps(password).length === 0 ? null : errorMessage('WEAK_PASSWORD'),
    terms: terms ? null : s.termsProblem,
  }
  const detailProblems = problemsOf(draft)
  const refused = failed?.field && SHOWN_ON_A_FIELD.has(failed.field) ? failed.field : null
  const emailError = (tried && problems.email) || (refused === 'email' && s.emailProblem) || null
  const passwordError =
    (tried && problems.password) || (failed?.code === 'WEAK_PASSWORD' && errorMessage('WEAK_PASSWORD')) || null
  const termsError = (tried && problems.terms) || null
  const marked =
    [emailError, passwordError, termsError].filter(Boolean).length +
    Object.entries(detailProblems).filter(
      ([field, problem]) => (tried && problem) || (refused === field && field !== 'email'),
    ).length

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    if ([...Object.values(problems), ...Object.values(detailProblems)].some(Boolean)) {
      setAttempt((count) => count + 1)
      return
    }
    setSending(true)
    try {
      await unwrap(
        api.POST('/api/v1/auth/register/pharmacy', {
          body: { email: email.trim(), password, pharmacy: bodyOf(draft), accept_terms: true },
        }),
      )
      navigate('/check-email', { state: { email: email.trim() } })
    } catch (error) {
      const refusal = error instanceof ApiFailure ? error : null
      const field = typeof refusal?.details.field === 'string' ? refusal.details.field : null
      const code = refusal?.code ?? 'INTERNAL_ERROR'
      setFailed({ code, details: refusal?.details, field })
      if ((field && SHOWN_ON_A_FIELD.has(field)) || code === 'WEAK_PASSWORD') {
        setAttempt((count) => count + 1)
      }
    } finally {
      setSending(false)
    }
  }

  // A refusal that names a field is shown on that field; the others, above the button.
  // Everything typed stays in the form: a busy moment (every password slot taken, a 503
  // with a wait) or a limit is said with when to try again, in the house words.
  const general = failed && !refused && failed.code !== 'WEAK_PASSWORD' ? failed : null
  return (
    <main className="screen screen--plain screen--white screen--form">
      <Link to="/welcome" className="round-button round-button--grey" aria-label={strings.common.back}>
        <BackIcon />
      </Link>
      <h1 className="page-title">{s.title}</h1>
      <p className="soft" style={{ margin: 0, fontSize: 17, lineHeight: 1.5 }}>
        {s.intro}
      </p>
      <p className="soft" style={{ margin: 0, fontSize: 17, lineHeight: 1.5 }}>
        {s.approvalNote}
      </p>
      <form className="form" onSubmit={submit} noValidate>
        <h2 className="panel__title">{s.account}</h2>
        <TextInput
          label={s.email}
          size="md"
          type="email"
          autoComplete="email"
          maxLength={MAX.email}
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
          error={emailError}
        />
        <PasswordInput
          label={s.password}
          size="md"
          autoComplete="new-password"
          maxLength={MAX.password}
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          error={passwordError}
        />
        <PasswordRules password={password} />

        <h2 className="panel__title">{strings.pharmacy.details.section}</h2>
        <DetailsFields
          draft={draft}
          onChange={setDraft}
          districts={districts.data ?? []}
          tried={tried}
          refused={refused}
        />

        <p className="hint" style={{ margin: 0, lineHeight: 1.5 }}>
          {s.termsNote}
        </p>
        <Checkbox
          label={s.terms}
          size="md"
          checked={terms}
          onChange={(event) => setTerms(event.currentTarget.checked)}
          error={termsError}
          // The library marks text boxes in error, not a checkbox: the focus finds it too.
          aria-invalid={termsError ? true : undefined}
        />
        {general && (
          <Banner tone="red" alert>
            {/* The sign-up limit is counted per hour (R-AU5): never "until tomorrow". */}
            {failureMessage(general, { hourly: true })}
          </Banner>
        )}
        <FormProblems count={marked} attempt={attempt} />
        <button type="submit" className="pill-button pill-button--wide" disabled={sending}>
          {s.submit}
        </button>
        <Link to="/login" className="text-button">
          {s.haveAccount}
        </Link>
      </form>
    </main>
  )
}
