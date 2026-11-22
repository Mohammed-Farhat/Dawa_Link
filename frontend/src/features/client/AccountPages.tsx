import { Checkbox, PasswordInput, TextInput } from '@mantine/core'
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { api, ApiFailure, getToken, unwrap } from '../../api/client'
import { useSession } from '../../api/session'
import { FormProblems } from '../../components/FormProblems'
import { BackIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { passwordGaps } from '../../components/passwordRule'
import { PasswordRules, PasswordRulesSaid } from '../../components/PasswordRules'
import { errorMessage, strings } from '../../strings/en'
import { type Failure, failureMessage } from '../../strings/failure'
import { MAX, phoneProblem, WHERE_FIELDS } from './fields'
import { emptyWhere, whereIsSaid, type WhereValue } from './where'
import { WhereYouLive } from './WhereYouLive'

const EMAIL_SHAPE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

function codeOf(error: unknown): string {
  return error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
}

function BackToWelcome({ to = '/welcome' }: { to?: string }) {
  return (
    <Link to={to} className="round-button round-button--grey" aria-label={strings.common.back}>
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
  // Each refused submit, by the form or by the API: the focus goes to the first mistake.
  const [attempt, setAttempt] = useState(0)
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [failedField, setFailedField] = useState<string | null>(null)
  // What the API said with its refusal: how long to wait, for a busy moment or a limit.
  const [failedDetails, setFailedDetails] = useState<Record<string, unknown>>({})
  const [common, setCommon] = useState(false)

  const [today] = useState(() => new Date().toISOString().slice(0, 10))
  const problems = {
    firstName: NAME_PART.test(firstName.trim()) ? null : s.partProblem,
    middleName: !middleName.trim() || NAME_PART.test(middleName.trim()) ? null : s.partProblem,
    lastName: NAME_PART.test(lastName.trim()) ? null : s.partProblem,
    birthDate: birthDate && birthDate <= today ? null : s.birthProblem,
    phone: phoneProblem(phone),
    email: EMAIL_SHAPE.test(email.trim()) ? null : s.emailProblem,
    password: passwordGaps(password).length === 0 ? null : errorMessage('WEAK_PASSWORD'),
    where: whereIsSaid(where) ? null : strings.where.problem,
    terms: terms ? null : s.termsProblem,
  }
  // What the server said about one box, next to that box.
  const refusedField = failed === 'VALIDATION_ERROR' ? failedField : null
  const refused = (...fields: string[]) => refusedField !== null && fields.includes(refusedField)
  // What each box shows: the form's own check, or the server's refusal of that box.
  const shown = {
    firstName: (tried && problems.firstName) || (refused('first_name') && s.partProblem) || null,
    middleName: (tried && problems.middleName) || (refused('middle_name') && s.partProblem) || null,
    lastName: (tried && problems.lastName) || (refused('last_name') && s.partProblem) || null,
    birthDate: (tried && problems.birthDate) || (refused('birth_date') && s.birthProblem) || null,
    phone: (tried && problems.phone) || (refused('phone') && s.phoneProblem) || null,
    email: (tried && problems.email) || (refused('email') && s.emailProblem) || null,
    password:
      (common && strings.password.common) ||
      (tried && problems.password) ||
      (failed === 'WEAK_PASSWORD' && errorMessage(failed)) ||
      (refused('password') && errorMessage('WEAK_PASSWORD')) ||
      null,
    where: (tried && problems.where) || (refused(...WHERE_FIELDS) && strings.where.problem) || null,
    terms: (tried && problems.terms) || (refused('accept_terms') && s.termsProblem) || null,
  }
  const marked = Object.values(shown).filter(Boolean).length
  // A refusal no box shows is said above the button, never lost (A#35).
  const general = failed && failed !== 'WEAK_PASSWORD' && marked === 0 ? failed : null

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    setFailedField(null)
    setFailedDetails({})
    setCommon(false)
    if (Object.values(problems).some(Boolean)) {
      setAttempt((count) => count + 1)
      return
    }
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
        setFailedDetails(error.details)
        setFailedField(typeof error.details?.field === 'string' ? error.details.field : null)
        const missing = error.details?.missing
        setCommon(Array.isArray(missing) && missing.includes('uncommon'))
      }
      // A refusal of a box takes the focus there; any other is said above the button.
      setAttempt((count) => count + 1)
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
            maxLength={MAX.name}
            value={firstName}
            onChange={(event) => setFirstName(event.currentTarget.value)}
            error={shown.firstName}
          />
          <TextInput
            label={s.middleName}
            size="md"
            autoComplete="additional-name"
            maxLength={MAX.name}
            value={middleName}
            onChange={(event) => setMiddleName(event.currentTarget.value)}
            error={shown.middleName}
          />
          <TextInput
            label={s.lastName}
            size="md"
            autoComplete="family-name"
            maxLength={MAX.name}
            value={lastName}
            onChange={(event) => setLastName(event.currentTarget.value)}
            error={shown.lastName}
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
            error={shown.birthDate}
          />
          <TextInput
            label={s.phone}
            size="md"
            type="tel"
            autoComplete="tel"
            maxLength={MAX.phone}
            value={phone}
            onChange={(event) => setPhone(event.currentTarget.value)}
            error={shown.phone}
          />
        </div>
        <TextInput
          label={s.email}
          size="md"
          type="email"
          autoComplete="email"
          maxLength={MAX.email}
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
          error={shown.email}
        />
        <PasswordInput
          label={s.password}
          // The rule below, said to a screen reader in the box (B §7).
          description={<PasswordRulesSaid password={password} />}
          descriptionProps={{ className: 'sr-only' }}
          size="md"
          autoComplete="new-password"
          maxLength={MAX.password}
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          error={shown.password}
        />
        <PasswordRules password={password} />
        <WhereYouLive value={where} onChange={setWhere} problem={shown.where} />
        <p className="hint" style={{ margin: 0, lineHeight: 1.5 }}>
          {s.termsNote}
        </p>
        <Checkbox
          label={s.terms}
          size="md"
          checked={terms}
          onChange={(event) => setTerms(event.currentTarget.checked)}
          error={shown.terms}
          // The library marks text boxes in error, not a checkbox: the focus finds it too.
          aria-invalid={shown.terms ? true : undefined}
        />
        {general && (
          <Banner tone="red" alert>
            {failureMessage({ code: general, details: failedDetails })}
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
      <p className="soft" style={{ margin: 0, lineHeight: 1.5 }}>
        {s.noEmail}
      </p>
      {import.meta.env.DEV && <p className="hint">{s.local}</p>}
      <Link to="/login" className="pill-button pill-button--wide pill-button--grey">
        {s.logIn}
      </Link>
    </AuthFrame>
  )
}

/**
 * The link of the confirmation email. It confirms the address and logs nobody in (R-AU4;
 * the owner, 2026-11-22): the person then logs in with their password. The same page for
 * a client and a pharmacist.
 */
export function VerifyEmailPage() {
  const s = strings.verify
  const [params, setParams] = useSearchParams()
  const { logout } = useSession()
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
      .then(async () => {
        // The server has just ended every session of the account: one held in this
        // browser is dropped too, through the one place that changes who is logged in.
        if (getToken()) await logout()
        setState('done')
      })
      .catch(() => setState('failed'))
  }, [params, setParams, logout])

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
        <Link to="/login" className="pill-button pill-button--wide">
          {s.logIn}
        </Link>
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
  const [failed, setFailed] = useState<Failure | null>(null)
  // [Log in] is never greyed out: a submit with a box left empty says so on that box and
  // takes the focus there, as the sign-up form does (B §7).
  const [tried, setTried] = useState(false)
  const [attempt, setAttempt] = useState(0)

  const missing = {
    email: email.trim() ? null : s.emailMissing,
    password: password ? null : s.passwordMissing,
    code: !withCode || code.trim() ? null : s.codeMissing,
  }
  const shown = tried ? missing : { email: null, password: null, code: null }
  const marked = Object.values(shown).filter(Boolean).length

  async function submit(event: FormEvent) {
    event.preventDefault()
    setFailed(null)
    setTried(true)
    if (Object.values(missing).some(Boolean)) {
      setAttempt((count) => count + 1)
      return
    }
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
      // A box the API refuses is still one sentence for a wrong login (R-AU2).
      const refused = codeOf(error)
      setFailed(
        refused === 'VALIDATION_ERROR'
          ? { code: 'INVALID_CREDENTIALS' }
          : { code: refused, details: error instanceof ApiFailure ? error.details : {} },
      )
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
          maxLength={MAX.email}
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
          error={shown.email}
        />
        <PasswordInput
          label={s.password}
          size="md"
          autoComplete="current-password"
          maxLength={MAX.password}
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          error={shown.password}
        />
        {/* Never for an admin: a lost admin is made again by the command (R-AU9). */}
        {!withCode && (
          <Link to="/forgot-password" className="text-button" style={{ alignSelf: 'flex-start' }}>
            {s.forgot}
          </Link>
        )}
        {withCode && (
          <TextInput
            label={s.code}
            size="md"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={MAX.code}
            value={code}
            onChange={(event) => setCode(event.currentTarget.value)}
            error={shown.code}
          />
        )}
        {failed && (
          <Banner tone="red" alert>
            {failed.code === 'RATE_LIMITED'
              ? s.networkBlocked
              : withCode && failed.code === 'INVALID_CREDENTIALS'
                ? s.wrongWithCode
                : failureMessage(failed)}
          </Banner>
        )}
        <FormProblems count={marked} attempt={attempt} />
        <button type="submit" className="pill-button pill-button--wide" disabled={sending}>
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

/**
 * "Forgot your password?" (R-AU9): one email box. The page says the same thing after
 * sending whatever the email was, as the API does (R-AU7): only a limit or a busy
 * moment is said otherwise, and neither says anything about the email.
 */
export function ForgotPasswordPage() {
  const s = strings.forgot
  const [email, setEmail] = useState('')
  const [tried, setTried] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [failed, setFailed] = useState<Failure | null>(null)

  const problem = !email.trim()
    ? strings.login.emailMissing
    : EMAIL_SHAPE.test(email.trim())
      ? null
      : strings.signUp.emailProblem
  const shown = tried ? problem : null

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    if (problem) {
      setAttempt((count) => count + 1)
      return
    }
    setSending(true)
    try {
      await unwrap(api.POST('/api/v1/auth/password/forgot', { body: { email: email.trim() } }))
      setSent(true)
    } catch (error) {
      setFailed({ code: codeOf(error), details: error instanceof ApiFailure ? error.details : {} })
    } finally {
      setSending(false)
    }
  }

  return (
    <AuthFrame>
      <BackToWelcome to="/login" />
      <h1 className="page-title">{s.title}</h1>
      {sent ? (
        <Banner tone="green">{s.sent}</Banner>
      ) : (
        <form className="form" onSubmit={submit} noValidate>
          <p className="soft" style={{ margin: 0, lineHeight: 1.5 }}>
            {s.intro}
          </p>
          <TextInput
            label={strings.login.email}
            size="md"
            type="email"
            autoComplete="username"
            maxLength={MAX.email}
            value={email}
            onChange={(event) => setEmail(event.currentTarget.value)}
            error={shown}
          />
          {failed && (
            <Banner tone="red" alert>
              {/* The limit is counted per hour: never "come back tomorrow". */}
              {failureMessage(failed, { hourly: true })}
            </Banner>
          )}
          <FormProblems count={shown ? 1 : 0} attempt={attempt} />
          <button type="submit" className="pill-button pill-button--wide" disabled={sending}>
            {s.submit}
          </button>
        </form>
      )}
      <p className="soft" style={{ margin: 0, lineHeight: 1.5 }}>
        {s.neverConfirmed}{' '}
        <Link to="/signup" className="text-button">
          {s.signUp}
        </Link>
      </p>
      <Link to="/login" className="pill-button pill-button--wide pill-button--grey">
        {s.logIn}
      </Link>
    </AuthFrame>
  )
}

// A reset link's token, kept for the page's life in this tab's storage (never the
// browser's): a reload of the page, after the token left the address bar, still has it.
const RESET_TOKEN = 'dawalink.resetToken'

function keptResetToken(): string {
  try {
    return window.sessionStorage.getItem(RESET_TOKEN) ?? ''
  } catch {
    return ''
  }
}

function keepResetToken(token: string | null): void {
  try {
    if (token) window.sessionStorage.setItem(RESET_TOKEN, token)
    else window.sessionStorage.removeItem(RESET_TOKEN)
  } catch {
    // Storage refused (a private window): a reload then needs the email's link again.
  }
}

/**
 * The link of the reset email (R-AU9): a new password, once, with the sign-up's rule.
 * Shown to anyone who opens the link, logged in or not: it proves the mailbox, not the
 * login. Once the password is set, nobody is logged in on this browser any more, and the
 * page leads to the login.
 */
export function ResetPasswordPage() {
  const s = strings.reset
  const { logout } = useSession()
  const [params, setParams] = useSearchParams()
  // Read once, as the page opens. The token then leaves the address bar and the history
  // at once, as the confirmation link's does; the form sends it later.
  const [token] = useState(() => params.get('token') ?? keptResetToken())
  const [password, setPassword] = useState('')
  const [tried, setTried] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [sending, setSending] = useState(false)
  const [state, setState] = useState<'form' | 'done' | 'failed'>(token ? 'form' : 'failed')
  const [failed, setFailed] = useState<Failure | null>(null)
  const [common, setCommon] = useState(false)

  useEffect(() => {
    if (params.has('token')) setParams({}, { replace: true })
  }, [params, setParams])
  // Kept while the form waits; gone once the link is used or refused, and when the page
  // is left.
  useEffect(() => {
    keepResetToken(state === 'form' ? token : null)
  }, [state, token])
  useEffect(() => () => keepResetToken(null), [])

  const problem = passwordGaps(password).length === 0 ? null : errorMessage('WEAK_PASSWORD')
  const shown =
    (common && strings.password.common) ||
    (tried && problem) ||
    (failed?.code === 'WEAK_PASSWORD' && errorMessage('WEAK_PASSWORD')) ||
    null

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    setCommon(false)
    if (problem) {
      setAttempt((count) => count + 1)
      return
    }
    setSending(true)
    try {
      await unwrap(api.POST('/api/v1/auth/password/reset', { body: { token, new_password: password } }))
      // Someone logged in on this browser is logged out, through the one place that
      // changes who is logged in, before the page offers the login.
      if (getToken()) await logout()
      setState('done')
    } catch (error) {
      const code = codeOf(error)
      const details = error instanceof ApiFailure ? error.details : {}
      // A token the API can't even read is a link that can't be used, like any other.
      if (code === 'TOKEN_INVALID' || (code === 'VALIDATION_ERROR' && details.field === 'token')) {
        setState('failed')
        return
      }
      setFailed({ code, details })
      const missing = details.missing
      setCommon(Array.isArray(missing) && missing.includes('uncommon'))
      setAttempt((count) => count + 1)
    } finally {
      setSending(false)
    }
  }

  const said = failed && failed.code !== 'WEAK_PASSWORD' ? failed : null
  return (
    <AuthFrame>
      <h1 className="page-title">{s.title}</h1>
      {state === 'done' && (
        <>
          <Banner tone="green">{s.done}</Banner>
          <Link to="/login" className="pill-button pill-button--wide">
            {s.logIn}
          </Link>
        </>
      )}
      {state === 'failed' && (
        <>
          <Banner tone="red">
            {s.failed} {s.failedHint}
          </Banner>
          <Link to="/forgot-password" className="pill-button pill-button--wide">
            {s.askAgain}
          </Link>
        </>
      )}
      {state === 'form' && (
        <form className="form" onSubmit={submit} noValidate>
          <PasswordInput
            label={s.password}
            // The rule below, said to a screen reader in the box, as on the sign-up form.
            description={<PasswordRulesSaid password={password} />}
            descriptionProps={{ className: 'sr-only' }}
            size="md"
            autoComplete="new-password"
            maxLength={MAX.password}
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            error={shown}
          />
          <PasswordRules password={password} />
          {said && (
            <Banner tone="red" alert>
              {failureMessage(said, { hourly: true })}
            </Banner>
          )}
          <FormProblems count={shown ? 1 : 0} attempt={attempt} />
          <button type="submit" className="pill-button pill-button--wide" disabled={sending}>
            {s.submit}
          </button>
        </form>
      )}
    </AuthFrame>
  )
}
