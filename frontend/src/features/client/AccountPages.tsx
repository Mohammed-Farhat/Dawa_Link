import { Checkbox, NativeSelect, PasswordInput, TextInput } from '@mantine/core'
import { type FormEvent, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { api, ApiFailure, unwrap } from '../../api/client'
import { useSession } from '../../api/session'
import { BackIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { useDistricts } from './data'

const EMAIL_SHAPE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

function codeOf(error: unknown): string {
  return error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
}

function BackToWelcome() {
  return (
    <Link to="/welcome" className="round-button round-button--grey" aria-label={strings.common.back}>
      <BackIcon />
    </Link>
  )
}

/** CS-2: sign up. The answer is always "check your email" (R-AU7). */
export function SignUpPage() {
  const s = strings.signUp
  const navigate = useNavigate()
  const districts = useDistricts()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [phone, setPhone] = useState('')
  const [district, setDistrict] = useState('')
  const [terms, setTerms] = useState(false)
  const [tried, setTried] = useState(false)
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  const problems = {
    fullName: fullName.trim().length < 2 || fullName.trim().length > 80 ? s.nameProblem : null,
    email: EMAIL_SHAPE.test(email.trim()) ? null : s.emailProblem,
    password: password.length >= 10 ? null : errorMessage('WEAK_PASSWORD'),
    district: district ? null : s.districtProblem,
    terms: terms ? null : s.termsProblem,
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    if (Object.values(problems).some(Boolean)) return
    setSending(true)
    try {
      await unwrap(
        api.POST('/api/v1/auth/register/client', {
          body: {
            email: email.trim(),
            password,
            full_name: fullName.trim(),
            phone: phone.trim() || null,
            district_id: Number(district),
            accept_terms: true,
          },
        }),
      )
      navigate('/check-email', { state: { email: email.trim() } })
    } catch (error) {
      setFailed(codeOf(error))
    } finally {
      setSending(false)
    }
  }

  return (
    <main className="screen screen--plain screen--white">
      <BackToWelcome />
      <h1 className="page-title">{s.title}</h1>
      <form className="form" onSubmit={submit} noValidate>
        <TextInput
          label={s.fullName}
          size="md"
          autoComplete="name"
          value={fullName}
          onChange={(event) => setFullName(event.currentTarget.value)}
          error={tried && problems.fullName}
        />
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
          error={(tried && problems.password) || (failed === 'WEAK_PASSWORD' && errorMessage(failed))}
        />
        <TextInput
          label={s.phone}
          size="md"
          type="tel"
          autoComplete="tel"
          value={phone}
          onChange={(event) => setPhone(event.currentTarget.value)}
        />
        <NativeSelect
          label={s.district}
          description={s.districtHint}
          size="md"
          value={district}
          onChange={(event) => setDistrict(event.currentTarget.value)}
          error={tried && problems.district}
          data={[
            { value: '', label: '' },
            ...(districts.data ?? []).map((row) => ({ value: String(row.id), label: row.name })),
          ]}
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
        {failed && failed !== 'WEAK_PASSWORD' && (
          <Banner tone="red" alert>
            {errorMessage(failed)}
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

/** CS-4: "we sent you a link". Shown after every sign-up, whatever the email (R-AU7). */
export function CheckEmailPage() {
  const s = strings.checkEmail
  const { state } = useLocation() as { state: { email?: string } | null }
  return (
    <main className="screen screen--plain screen--white">
      <BackToWelcome />
      <h1 className="page-title">{s.title}</h1>
      <p className="soft" style={{ margin: 0, fontSize: 17, lineHeight: 1.5 }}>
        {s.body(state?.email ?? '…')}
      </p>
      {import.meta.env.DEV && <p className="hint">{s.local}</p>}
      <Link to="/login" className="pill-button pill-button--wide pill-button--grey">
        {s.logIn}
      </Link>
    </main>
  )
}

/** The link of the confirmation email. It confirms the address and logs the user in (R-AU4). */
export function VerifyEmailPage() {
  const s = strings.verify
  const [params, setParams] = useSearchParams()
  const { start } = useSession()
  const navigate = useNavigate()
  const [state, setState] = useState<'working' | 'done' | 'failed'>('working')
  // A link works once: in development React runs effects twice, and the second run
  // would be refused.
  const asked = useRef(false)

  useEffect(() => {
    if (asked.current) return
    asked.current = true
    const token = params.get('token') ?? ''
    // The token leaves the address bar and the history at once: it was read.
    setParams({}, { replace: true })
    unwrap(api.POST('/api/v1/auth/verify-email', { body: { token } }))
      .then((loggedIn) => {
        start(loggedIn)
        setState('done')
      })
      .catch(() => setState('failed'))
  }, [params, setParams, start])

  return (
    <main className="screen screen--plain screen--white">
      <h1 className="page-title">{strings.appName}</h1>
      <div role="status" aria-live="polite">
        {state === 'working' && <p className="soft">{s.working}</p>}
        {state === 'done' && <Banner tone="green">{s.done}</Banner>}
        {state === 'failed' && (
          <Banner tone="red">
            {s.failed} {s.failedHint}
          </Banner>
        )}
      </div>
      {state === 'done' && (
        <button type="button" className="pill-button pill-button--wide" onClick={() => navigate('/')}>
          {s.continue}
        </button>
      )}
      {state === 'failed' && (
        <Link to="/login" className="pill-button pill-button--wide pill-button--grey">
          {strings.login.submit}
        </Link>
      )}
    </main>
  )
}

/** CS-3: log in. One sentence for a wrong email, password or code (R-AU2).
 * `withCode` adds the admins' second factor: only the admin console's login shows it. */
export function LoginPage({ withCode = false }: { withCode?: boolean }) {
  const s = strings.login
  const { start } = useSession()
  const navigate = useNavigate()
  const { state } = useLocation() as { state: { from?: string } | null }
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setFailed(null)
    setSending(true)
    try {
      const loggedIn = await unwrap(
        api.POST('/api/v1/auth/login', {
          body: { email: email.trim(), password, totp_code: code.trim() || null },
        }),
      )
      start(loggedIn)
      // Back to the screen that asked for the login (docs/11 §7, "Session expired").
      navigate(state?.from ?? '/', { replace: true })
    } catch (error) {
      setFailed(codeOf(error) === 'VALIDATION_ERROR' ? 'INVALID_CREDENTIALS' : codeOf(error))
    } finally {
      setSending(false)
    }
  }

  return (
    <main className="screen screen--plain screen--white">
      {!withCode && <BackToWelcome />}
      <h1 className="page-title">{withCode ? strings.admin.loginTitle : s.title}</h1>
      <form className="form" onSubmit={submit} noValidate>
        <TextInput
          label={s.email}
          size="md"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
        />
        <PasswordInput
          label={s.password}
          size="md"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
        />
        {withCode && (
          <TextInput
            label={s.code}
            size="md"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(event) => setCode(event.currentTarget.value)}
          />
        )}
        {failed && (
          <Banner tone="red" alert>
            {failed === 'RATE_LIMITED' ? s.networkBlocked : errorMessage(failed)}
          </Banner>
        )}
        <button
          type="submit"
          className="pill-button pill-button--wide"
          disabled={sending || !email.trim() || !password || (withCode && !code.trim())}
        >
          {s.submit}
        </button>
        {/* An admin account is made by a command, never from the website (A-D1). */}
        {!withCode && (
          <Link to="/signup" className="text-button">
            {s.noAccount}
          </Link>
        )}
      </form>
    </main>
  )
}
