import { Checkbox, PasswordInput, TextInput } from '@mantine/core'
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { api, ApiFailure, unwrap } from '../../api/client'
import { useSession } from '../../api/session'
import { BackIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { passwordGaps } from '../../components/passwordRule'
import { PasswordRules } from '../../components/PasswordRules'
import { errorMessage, strings } from '../../strings/en'
import { emptyWhere, whereIsSaid, type WhereValue } from './where'
import { WhereYouLive } from './WhereYouLive'

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

/**
 * The frame of a public page with a form. A phone shows the form alone; a computer puts
 * it beside a panel that says what DawaLink is (decision log BLD-D40). The panel is an
 * illustration: a screen reader goes straight to the form.
 */
export function AuthFrame({ children, side = true }: { children: ReactNode; side?: boolean }) {
  const w = strings.welcome
  // The admins' login is a tool's door, not a client's page: the form stands alone.
  if (!side) {
    return (
      <div className="auth auth--alone">
        <main className="screen screen--plain screen--white auth__main">{children}</main>
      </div>
    )
  }
  return (
    <div className="auth">
      <aside className="auth__side" aria-hidden="true">
        <div className="brand">
          <span className="brand__mark">D</span>
          {strings.appName}
        </div>
        <h2>{strings.authSide.title}</h2>
        <p>{strings.authSide.intro}</p>
        <ol className="steps">
          {w.steps.map((step, index) => (
            <li key={step}>
              <span className="steps__number">{index + 1}</span>
              {step}
            </li>
          ))}
        </ol>
      </aside>
      <main className="screen screen--plain screen--white auth__main">{children}</main>
    </div>
  )
}

const NAME_PART = /^[\p{L}\p{M} '.-]{1,40}$/u

/** CS-2: sign up. The answer is always "check your email" (R-AU7). */
export function SignUpPage() {
  const s = strings.signUp
  const navigate = useNavigate()
  const [firstName, setFirstName] = useState('')
  const [middleName, setMiddleName] = useState('')
  const [lastName, setLastName] = useState('')
  const [birthDate, setBirthDate] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [phone, setPhone] = useState('')
  const [where, setWhere] = useState<WhereValue>(emptyWhere)
  const [terms, setTerms] = useState(false)
  const [tried, setTried] = useState(false)
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [failedField, setFailedField] = useState<string | null>(null)
  const [common, setCommon] = useState(false)

  const [today] = useState(() => new Date().toISOString().slice(0, 10))
  const problems = {
    firstName: NAME_PART.test(firstName.trim()) ? null : s.partProblem,
    middleName: !middleName.trim() || NAME_PART.test(middleName.trim()) ? null : s.partProblem,
    lastName: NAME_PART.test(lastName.trim()) ? null : s.partProblem,
    birthDate: birthDate && birthDate <= today ? null : s.birthProblem,
    email: EMAIL_SHAPE.test(email.trim()) ? null : s.emailProblem,
    password: passwordGaps(password).length === 0 ? null : errorMessage('WEAK_PASSWORD'),
    where: whereIsSaid(where) ? null : strings.where.problem,
    terms: terms ? null : s.termsProblem,
  }
  // What the server said about one box, next to that box.
  const refusedField = failed === 'VALIDATION_ERROR' ? failedField : null

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    setFailedField(null)
    setCommon(false)
    if (Object.values(problems).some(Boolean)) return
    setSending(true)
    try {
      await unwrap(
        api.POST('/api/v1/auth/register/client', {
          body: {
            email: email.trim(),
            password,
            first_name: firstName.trim(),
            middle_name: middleName.trim() || null,
            last_name: lastName.trim(),
            birth_date: birthDate,
            phone: phone.trim() || null,
            // One way or the other: a place on the map, or an area.
            ...(where.mode === 'map'
              ? { home_place: where.pin }
              : {
                  district_id: Number(where.area.district),
                  home_area_id: where.area.town ? Number(where.area.town) : null,
                }),
            accept_terms: true,
          },
        }),
      )
      navigate('/check-email', { state: { email: email.trim() } })
    } catch (error) {
      setFailed(codeOf(error))
      if (error instanceof ApiFailure) {
        setFailedField(typeof error.details?.field === 'string' ? error.details.field : null)
        const missing = error.details?.missing
        setCommon(Array.isArray(missing) && missing.includes('uncommon'))
      }
    } finally {
      setSending(false)
    }
  }

  return (
    <AuthFrame>
      <BackToWelcome />
      <h1 className="page-title">{s.title}</h1>
      <form className="form" onSubmit={submit} noValidate>
        <div className="auth__form-row auth__form-row--three">
          <TextInput
            label={s.firstName}
            size="md"
            autoComplete="given-name"
            value={firstName}
            onChange={(event) => setFirstName(event.currentTarget.value)}
            error={(tried && problems.firstName) || (refusedField === 'first_name' && s.partProblem)}
          />
          <TextInput
            label={s.middleName}
            placeholder={s.optional}
            size="md"
            autoComplete="additional-name"
            value={middleName}
            onChange={(event) => setMiddleName(event.currentTarget.value)}
            error={(tried && problems.middleName) || (refusedField === 'middle_name' && s.partProblem)}
          />
          <TextInput
            label={s.lastName}
            size="md"
            autoComplete="family-name"
            value={lastName}
            onChange={(event) => setLastName(event.currentTarget.value)}
            error={(tried && problems.lastName) || (refusedField === 'last_name' && s.partProblem)}
          />
        </div>
        <div className="auth__form-row">
          <TextInput
            label={s.birthDate}
            size="md"
            type="date"
            max={today}
            autoComplete="bday"
            value={birthDate}
            onChange={(event) => setBirthDate(event.currentTarget.value)}
            error={(tried && problems.birthDate) || (refusedField === 'birth_date' && s.birthProblem)}
          />
          <TextInput
            label={s.phone}
            size="md"
            type="tel"
            autoComplete="tel"
            value={phone}
            onChange={(event) => setPhone(event.currentTarget.value)}
            error={refusedField === 'phone' && errorMessage('VALIDATION_ERROR')}
          />
        </div>
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
          size="md"
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          error={
            (common && strings.password.common) ||
            (tried && problems.password) ||
            (failed === 'WEAK_PASSWORD' && errorMessage(failed))
          }
        />
        <PasswordRules password={password} />
        <WhereYouLive
          value={where}
          onChange={setWhere}
          problem={
            (tried && problems.where) ||
            ((refusedField === 'location' || refusedField === 'district_id') && strings.where.problem)
          }
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
        {failed && failed !== 'WEAK_PASSWORD' && !refusedField && (
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
    </AuthFrame>
  )
}

/** CS-4: "we sent you a link". Shown after every sign-up, whatever the email (R-AU7). */
export function CheckEmailPage() {
  const s = strings.checkEmail
  const { state } = useLocation() as { state: { email?: string } | null }
  return (
    <AuthFrame>
      <BackToWelcome />
      <h1 className="page-title">{s.title}</h1>
      <p className="soft" style={{ margin: 0, fontSize: 17, lineHeight: 1.5 }}>
        {s.body(state?.email ?? '…')}
      </p>
      {import.meta.env.DEV && <p className="hint">{s.local}</p>}
      <Link to="/login" className="pill-button pill-button--wide pill-button--grey">
        {s.logIn}
      </Link>
    </AuthFrame>
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
    <AuthFrame>
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
    </AuthFrame>
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
    <AuthFrame side={!withCode}>
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
    </AuthFrame>
  )
}
