import { TextInput } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { useSession } from '../../api/session'
import { ChangePassword } from '../../components/ChangePassword'
import { FormProblems } from '../../components/FormProblems'
import { Banner, Screen } from '../../components/layout'
import { strings } from '../../strings/en'
import { failureMessage } from '../../strings/failure'
import { DeleteAccount } from './DeleteAccount'
import { MAX, phoneProblem, WHERE_FIELDS } from './fields'
import { type Pin, whereIsSaid, type WhereValue } from './where'
import { WhereYouLive } from './WhereYouLive'

const m = strings.me
const f = strings.signUp

// The API's fields the details form shows on a box of its own; any other refusal is
// said by [Save] (A#35).
const DETAILS_FIELDS = ['first_name', 'middle_name', 'last_name', 'birth_date', 'phone']

type Me = Schemas['Me']
type Client = NonNullable<Me['client']>

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="row-card" aria-labelledby={id}>
      <h2 id={id} className="card__title" style={{ margin: 0 }}>
        {title}
      </h2>
      {children}
    </section>
  )
}

/** What a form of this page shows after [Save]. */
function useSaving() {
  const [state, setState] = useState<'idle' | 'sending' | 'saved'>('idle')
  const [failed, setFailed] = useState<{ code: string; field: string | null; details: Record<string, unknown> } | null>(
    null,
  )
  // Each refusal, so the focus goes to the box it is about (components/FormProblems.tsx).
  const [attempt, setAttempt] = useState(0)
  async function run(work: () => Promise<unknown>) {
    setFailed(null)
    setState('sending')
    try {
      await work()
      setState('saved')
    } catch (error) {
      const failure = error instanceof ApiFailure ? error : null
      setFailed({
        code: failure?.code ?? 'INTERNAL_ERROR',
        field: typeof failure?.details.field === 'string' ? failure.details.field : null,
        details: failure?.details ?? {},
      })
      setState('idle')
      setAttempt((count) => count + 1)
    }
  }
  return { state, failed, attempt, run, touched: () => setState('idle') }
}

/**
 * [Save]'s answer. A refusal is said here unless the form shows it on one of its boxes
 * (`onFields`): a refusal of a box the form doesn't have is never lost (A#35). A limit
 * says how long to wait: a place counts toward a limit per hour (N-47).
 */
function Result({ saving, onFields = [] }: { saving: ReturnType<typeof useSaving>; onFields?: string[] }) {
  const failed = saving.failed
  const said = failed && !(failed.field && onFields.includes(failed.field))
  return (
    <div role="status" aria-live="polite">
      {saving.state === 'saved' && <Banner tone="green">{m.saved}</Banner>}
      {said && (
        <Banner tone="red">{failureMessage({ code: failed.code, details: failed.details }, { hourly: true })}</Banner>
      )}
    </div>
  )
}

/**
 * CS-13: who is logged in and what they can set (decision log BLD-D40): their name and
 * date of birth, their phone, where they live (searches start there when no location is
 * shared), a place on the map, and whether the assistant may tell them about other
 * brands. Then notifications, the password, logging out and deleting the account.
 *
 * One column on a phone, two on a computer.
 */
export function MePage() {
  const { me, logout } = useSession()
  const unread = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () => unwrap(api.GET('/api/v1/notifications/unread-count')),
    refetchInterval: 30_000,
  })
  const client = me?.client
  return (
    <Screen>
      <h1 className="page-title">{m.title}</h1>
      <div className="cols cols--two">
        <div className="stack">
          {me && client && <Details key={`details-${me.id}`} me={me} client={client} />}
          {me && client && <Home key={`home-${me.id}`} client={client} />}
        </div>
        <div className="stack">
          {me && (
            <Section id="account" title={m.account}>
              <span style={{ fontSize: 18, fontWeight: 600 }}>{me.full_name}</span>
              <span className="soft">{me.email}</span>
            </Section>
          )}
          {client && <MissedPickups client={client} />}
          {client && <OtherBrands key={`brands-${me?.id}`} client={client} />}
          <Link
            to="/notifications"
            className="row-card row-link"
            style={{ flexDirection: 'row', justifyContent: 'space-between' }}
          >
            <span style={{ fontWeight: 600 }}>{strings.notifications.title}</span>
            {(unread.data?.count ?? 0) > 0 && (
              <span className="status-pill status-pill--blue">
                {strings.notifications.count(unread.data?.count ?? 0)}
              </span>
            )}
          </Link>
          <Section id="password" title={strings.pharmacy.settingsPage.passwordTitle}>
            <ChangePassword />
          </Section>
          <button
            type="button"
            className="pill-button profile-logout"
            onClick={() => void logout()}
          >
            {m.logOut}
          </button>
          {/* The last thing on the page, and quiet until it is opened (R-AU10). */}
          {client && <DeleteAccount />}
        </div>
      </div>
    </Screen>
  )
}

/** R-N1, said in a sentence: what counts, how many, and what happens then. */
function MissedPickups({ client }: { client: Client }) {
  const missed = client.missed_pickups_30d
  return (
    <Section id="missed" title={m.missedTitle}>
      <span className={`status-pill status-pill--${missed === 0 ? 'green' : 'amber'}`}>
        {missed === 0
          ? m.missedNone(client.missed_pickups_window_days)
          : m.missedPickups(missed, client.missed_pickups_before_pause)}
      </span>
      <p className="soft" style={{ margin: 0, fontSize: 15, lineHeight: 1.5 }}>
        {m.missedRule(
          client.missed_pickups_before_pause,
          client.missed_pickups_window_days,
          client.missed_pickups_pause_days,
        )}
      </p>
      {missed > 0 && <p className="hint" style={{ margin: 0 }}>{m.missedContest}</p>}
    </Section>
  )
}

function Details({ me, client }: { me: Me; client: Client }) {
  const { refresh } = useSession()
  const saving = useSaving()
  const [first, setFirst] = useState(client.first_name ?? '')
  const [middle, setMiddle] = useState(client.middle_name ?? '')
  const [last, setLast] = useState(client.last_name ?? '')
  const [born, setBorn] = useState(client.birth_date ?? '')
  const [phone, setPhone] = useState(me.phone ?? '')
  const [today] = useState(() => new Date().toISOString().slice(0, 10))
  // A phone the API would refuse is said before anything is sent (B#4).
  const [phoneChecked, setPhoneChecked] = useState(false)
  const [phoneAttempt, setPhoneAttempt] = useState(0)
  const wrong = saving.failed?.field
  const phoneError = (phoneChecked && phoneProblem(phone)) || (wrong === 'phone' && f.phoneProblem) || null
  const marked =
    [phoneError].filter(Boolean).length +
    (['first_name', 'middle_name', 'last_name', 'birth_date'].includes(wrong ?? '') ? 1 : 0)

  function save(event: FormEvent) {
    event.preventDefault()
    if (phoneProblem(phone)) {
      setPhoneChecked(true)
      setPhoneAttempt((count) => count + 1)
      return
    }
    void saving.run(async () => {
      await unwrap(
        api.PATCH('/api/v1/me/profile', {
          body: {
            first_name: first.trim(),
            middle_name: middle.trim() || null,
            last_name: last.trim(),
            ...(born ? { birth_date: born } : {}),
            phone: phone.trim() || null,
          },
        }),
      )
      await refresh()
    })
  }

  const box = (set: (value: string) => void) => (event: { currentTarget: { value: string } }) => {
    set(event.currentTarget.value)
    saving.touched()
  }
  return (
    <Section id="profile" title={m.profile}>
      <form className="form" onSubmit={save} noValidate>
        {/* First, middle, last: the order of the sign-up form (B#30). */}
        <div className="auth__form-row auth__form-row--three">
          <TextInput
            label={f.firstName}
            size="md"
            autoComplete="given-name"
            maxLength={MAX.name}
            value={first}
            onChange={box(setFirst)}
            error={wrong === 'first_name' && f.partProblem}
          />
          <TextInput
            label={f.middleName}
            size="md"
            autoComplete="additional-name"
            maxLength={MAX.name}
            value={middle}
            onChange={box(setMiddle)}
            error={wrong === 'middle_name' && f.partProblem}
          />
          <TextInput
            label={f.lastName}
            size="md"
            autoComplete="family-name"
            maxLength={MAX.name}
            value={last}
            onChange={box(setLast)}
            error={wrong === 'last_name' && f.partProblem}
          />
        </div>
        <div className="auth__form-row">
          <TextInput
            label={f.birthDate}
            size="md"
            type="date"
            max={today}
            autoComplete="bday"
            value={born}
            onChange={box(setBorn)}
            error={wrong === 'birth_date' && f.birthProblem}
          />
          <TextInput
            label={m.phone}
            description={m.phoneHint}
            size="md"
            type="tel"
            autoComplete="tel"
            maxLength={MAX.phone}
            value={phone}
            onChange={box(setPhone)}
            error={phoneError}
          />
        </div>
        <Result saving={saving} onFields={DETAILS_FIELDS} />
        <FormProblems count={marked} attempt={saving.attempt + phoneAttempt} />
        <button
          type="submit"
          className="pill-button"
          style={{ alignSelf: 'flex-start' }}
          disabled={saving.state === 'sending'}
        >
          {m.save}
        </button>
      </form>
    </Section>
  )
}

/**
 * Where the client lives: a place on a map (with [Use my location], which puts the pin
 * where the device is and saves at once), **or** the governorate, the district and the
 * town (the owner, 2026-11-18, BLD-D42). Saving one way removes the other: a saved
 * place wins over an area when a search starts, so keeping both would hide the area.
 */
function Home({ client }: { client: Client }) {
  const { refresh } = useSession()
  const saving = useSaving()
  // The saved place is asked for only here, where its owner looks at it: the profile
  // itself never carries the point.
  const saved = useQuery({
    queryKey: ['home-place', client.home_place_saved],
    queryFn: () => unwrap(api.GET('/api/v1/me/home-place')),
    enabled: client.home_place_saved,
    retry: false,
    gcTime: 0,
  })
  const [where, setWhere] = useState<WhereValue>({
    mode: client.home_place_saved || !client.district ? 'map' : 'area',
    pin: null,
    area: {
      governorate: client.district?.governorate ?? '',
      district: client.district ? String(client.district.id) : '',
      town: client.home_area ? String(client.home_area.id) : '',
    },
  })
  // What the map shows: the pin just put, or the one that is saved.
  const shown: WhereValue = { ...where, pin: where.pin ?? saved.data ?? null }

  function savePlace(pin: Pin) {
    void saving.run(async () => {
      await unwrap(api.PUT('/api/v1/me/home-place', { body: pin }))
      await refresh()
    })
  }

  function save(event: FormEvent) {
    event.preventDefault()
    if (!whereIsSaid(shown)) return
    if (shown.mode === 'map' && shown.pin) {
      savePlace(shown.pin)
      return
    }
    void saving.run(async () => {
      // The area first, the place after: if the second call fails the client still has
      // somewhere a search can start from.
      await unwrap(
        api.PATCH('/api/v1/me/profile', {
          body: {
            district_id: Number(where.area.district),
            home_area_id: where.area.town ? Number(where.area.town) : null,
          },
        }),
      )
      if (client.home_place_saved) await unwrap(api.DELETE('/api/v1/me/home-place'))
      await refresh()
    })
  }

  return (
    <Section id="home" title={m.homeTitle}>
      <form className="form" onSubmit={save} noValidate>
        <WhereYouLive
          value={shown}
          onChange={(next) => {
            setWhere(next)
            saving.touched()
          }}
          onLocated={savePlace}
          untitled
          problem={saving.failed?.field && WHERE_FIELDS.includes(saving.failed.field) ? strings.where.problem : null}
        />
        <Result saving={saving} onFields={WHERE_FIELDS} />
        <button
          type="submit"
          className="pill-button"
          style={{ alignSelf: 'flex-start' }}
          disabled={saving.state === 'sending' || !whereIsSaid(shown)}
        >
          {m.save}
        </button>
      </form>
    </Section>
  )
}

function OtherBrands({ client }: { client: Client }) {
  const { refresh } = useSession()
  const saving = useSaving()
  const [allowed, setAllowed] = useState(client.alternatives_ok_default)

  function change(next: boolean) {
    setAllowed(next)
    void saving.run(async () => {
      await unwrap(api.PATCH('/api/v1/me/profile', { body: { alternatives_ok_default: next } }))
      await refresh()
    })
  }

  return (
    <Section id="assistant" title={m.assistant}>
      <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, minHeight: 44 }}>
        <input
          type="checkbox"
          style={{ marginTop: 4 }}
          checked={allowed}
          onChange={(event) => change(event.currentTarget.checked)}
        />
        <span>
          {m.otherBrands}
          <br />
          <span className="hint">{m.otherBrandsHint}</span>
        </span>
      </label>
      <Result saving={saving} />
    </Section>
  )
}
