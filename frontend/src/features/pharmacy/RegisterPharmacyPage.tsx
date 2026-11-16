import { Checkbox, PasswordInput, TextInput } from '@mantine/core'
import { type FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, ApiFailure, unwrap } from '../../api/client'
import { BackIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { useDistricts } from '../client/data'
import { DetailsFields } from './details'
import { bodyOf, emptyDraft, problemsOf } from './draft'

const s = strings.pharmacy.register
const EMAIL_SHAPE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

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
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<{ code: string; field: string | null } | null>(null)

  const problems = {
    email: EMAIL_SHAPE.test(email.trim()) ? null : s.emailProblem,
    password: password.length >= 10 ? null : errorMessage('WEAK_PASSWORD'),
    terms: terms ? null : s.termsProblem,
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    if ([...Object.values(problems), ...Object.values(problemsOf(draft))].some(Boolean)) return
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
      setFailed({
        code: refusal?.code ?? 'INTERNAL_ERROR',
        field: typeof refusal?.details.field === 'string' ? refusal.details.field : null,
      })
    } finally {
      setSending(false)
    }
  }

  // A refusal that names a field is shown on that field; the others, above the button.
  const general = failed && !failed.field && failed.code !== 'WEAK_PASSWORD' ? failed.code : null
  return (
    <main className="screen screen--plain screen--white screen--form">
      <Link to="/welcome" className="round-button round-button--grey" aria-label={strings.common.back}>
        <BackIcon />
      </Link>
      <h1 className="page-title">{s.title}</h1>
      <p className="soft" style={{ margin: 0, fontSize: 17, lineHeight: 1.5 }}>
        {s.intro}
      </p>
      <form className="form" onSubmit={submit} noValidate>
        <h2 className="panel__title">{s.account}</h2>
        <TextInput
          label={s.email}
          size="md"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
          error={tried && problems.email}
        />
        <PasswordInput
          label={s.password}
          description={s.passwordHint}
          size="md"
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          error={
            (tried && problems.password) ||
            (failed?.code === 'WEAK_PASSWORD' && errorMessage('WEAK_PASSWORD'))
          }
        />

        <h2 className="panel__title">{strings.pharmacy.details.section}</h2>
        <DetailsFields
          draft={draft}
          onChange={setDraft}
          districts={districts.data ?? []}
          tried={tried}
          refused={failed?.field ?? null}
        />

        <p className="hint" style={{ margin: 0, lineHeight: 1.5 }}>
          {s.termsNote}
        </p>
        <Checkbox
          label={s.terms}
          size="md"
          checked={terms}
          onChange={(event) => setTerms(event.currentTarget.checked)}
          error={tried && problems.terms}
        />
        {general && (
          <Banner tone="red" alert>
            {errorMessage(general)}
          </Banner>
        )}
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
