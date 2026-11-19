import { NativeSelect, TextInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, lazy, Suspense, useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { ChangePassword } from '../../components/ChangePassword'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { useDistricts } from '../client/data'
import { DetailsFields, HoursFields, PickupDays } from './details'
import { bodyOf, draftOf, hoursOf, phoneProblem, problemsOf, weekOf, weekProblem } from './draft'

// The map is downloaded only when the settings open (docs/11 §10).
const PinMap = lazy(() => import('./PinMap'))

const d = strings.pharmacy.details
const s = strings.pharmacy.settingsPage

type Profile = Schemas['PharmacyProfile']
type Failure = { code: string; field: string | null }

function failureOf(error: unknown): Failure {
  const refusal = error instanceof ApiFailure ? error : null
  return {
    code: refusal?.code ?? 'INTERNAL_ERROR',
    field: typeof refusal?.details.field === 'string' ? refusal.details.field : null,
  }
}

/**
 * PS-2: while it waits for approval, or after a rejection, the pharmacy corrects what it
 * typed. After a rejection, saving also sends the registration back to DawaLink's team.
 */
export function RegistrationPanel({ pharmacy }: { pharmacy: Profile }) {
  const queryClient = useQueryClient()
  const districts = useDistricts()
  const [draft, setDraft] = useState(() => draftOf(pharmacy))
  const [tried, setTried] = useState(false)
  const [state, setState] = useState<'idle' | 'sending' | 'saved'>('idle')
  const [failed, setFailed] = useState<Failure | null>(null)
  const rejected = pharmacy.status === 'REJECTED'

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    if (Object.values(problemsOf(draft)).some(Boolean)) return
    setState('sending')
    try {
      let saved = await unwrap(api.PATCH('/api/v1/pharmacy/me/registration', { body: bodyOf(draft) }))
      if (rejected) saved = await unwrap(api.POST('/api/v1/pharmacy/me/resubmit'))
      queryClient.setQueryData(['pharmacy', 'me'], saved)
      await queryClient.invalidateQueries({ queryKey: ['me'] })
      setState('saved')
    } catch (error) {
      setFailed(failureOf(error))
      setState('idle')
    }
  }

  return (
    <main className="portal__main">
      <section className="panel" aria-labelledby="registration">
        <h1 id="registration" className="panel__title">
          {d.section}
        </h1>
        <form className="form" onSubmit={submit} noValidate>
          <DetailsFields
            draft={draft}
            onChange={(next) => {
              setDraft(next)
              setState('idle')
            }}
            districts={districts.data ?? []}
            tried={tried}
            refused={failed?.field ?? null}
          />
          <div role="status" aria-live="polite">
            {state === 'saved' && <Banner tone="green">{d.saved}</Banner>}
            {failed && !failed.field && <Banner tone="red">{errorMessage(failed.code)}</Banner>}
          </div>
          <button
            type="submit"
            className="pill-button"
            style={{ alignSelf: 'flex-start' }}
            disabled={state === 'sending'}
          >
            {rejected ? d.resubmit : d.save}
          </button>
        </form>
      </section>
    </main>
  )
}

/**
 * PS-10: what an approved pharmacy changes by itself: its opening hours, how long it
 * keeps a reservation, its phone number, its address and its pin (the owner, 2026-11-16:
 * only the pharmacy knows that it got a new number or moved). Its name and its licence
 * were checked by DawaLink's team, and only they change them (docs/10 TM-D2).
 */
export function SettingsPage({ pharmacy }: { pharmacy: Profile }) {
  const queryClient = useQueryClient()
  const [week, setWeek] = useState(() => weekOf(pharmacy.hours))
  const [pickupDays, setPickupDays] = useState(pharmacy.pickup_days)
  const [phone, setPhone] = useState(pharmacy.phone)
  const [state, setState] = useState<'idle' | 'sending' | 'saved'>('idle')
  const [tried, setTried] = useState(false)
  const [failed, setFailed] = useState<Failure | null>(null)
  const approved = pharmacy.status === 'APPROVED'
  const phoneChanged = phone.trim() !== pharmacy.phone

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    if (weekProblem(week) || (phoneChanged && phoneProblem(phone))) return
    setState('sending')
    try {
      const saved = await unwrap(
        api.PATCH('/api/v1/pharmacy/me', {
          body: {
            hours: hoursOf(week),
            pickup_days: pickupDays,
            // Sent only when it was edited: the number is stored as +961…, and typing
            // it again the local way would look like a change.
            ...(phoneChanged ? { phone: phone.trim() } : {}),
          },
        }),
      )
      queryClient.setQueryData(['pharmacy', 'me'], saved)
      setPhone(saved.phone)
      setState('saved')
    } catch (error) {
      setFailed(failureOf(error))
      setState('idle')
    }
  }

  return (
    <main className="portal__main">
      <h1 className="page-title">{s.title}</h1>
      {approved && (
        <section className="panel" aria-labelledby="hours">
          <div>
            <h2 id="hours" className="panel__title">
              {s.hoursTitle}
            </h2>
            <span className="hint">{s.hoursNote}</span>
          </div>
          <form className="form" onSubmit={submit} noValidate>
            <HoursFields
              week={week}
              onChange={(next) => {
                setWeek(next)
                setState('idle')
              }}
              problem={(tried && weekProblem(week)) || (failed?.field === 'hours' ? d.problems.hours : null)}
            />
            <PickupDays
              value={pickupDays}
              onChange={(days) => {
                setPickupDays(days)
                setState('idle')
              }}
            />
            <TextInput
              label={d.phone}
              description={d.phoneHint}
              size="md"
              type="tel"
              autoComplete="tel"
              value={phone}
              onChange={(event) => {
                setPhone(event.currentTarget.value)
                setState('idle')
              }}
              error={
                (tried && phoneChanged && phoneProblem(phone)) ||
                (failed?.field === 'phone' ? d.problems.phone : null)
              }
            />
            <div role="status" aria-live="polite">
              {state === 'saved' && <Banner tone="green">{d.saved}</Banner>}
              {failed && !failed.field && <Banner tone="red">{errorMessage(failed.code)}</Banner>}
            </div>
            <button
              type="submit"
              className="pill-button"
              style={{ alignSelf: 'flex-start' }}
              disabled={state === 'sending'}
            >
              {d.save}
            </button>
          </form>
        </section>
      )}

      {approved && <ListingRule pharmacy={pharmacy} />}

      {approved && <PlaceSettings pharmacy={pharmacy} />}

      <section className="panel" aria-labelledby="details">
        <h2 id="details" className="panel__title">
          {s.detailsTitle}
        </h2>
        <dl className="card__lines">
          <div className="card__line">
            <dt>{d.name}</dt>
            <dd>{pharmacy.name}</dd>
          </div>
          <div className="card__line">
            <dt>{d.license}</dt>
            <dd>{pharmacy.license_number}</dd>
          </div>
        </dl>
        <span className="hint">{d.fixed}</span>
      </section>

      <section className="panel" aria-labelledby="password">
        <h2 id="password" className="panel__title">
          {s.passwordTitle}
        </h2>
        <ChangePassword />
      </section>
    </main>
  )
}

/**
 * Where the pharmacy is: its address, its district and its pin on the map. A pharmacy
 * that moves changes them here (the owner, 2026-11-16, Q45). Clients see the new place
 * at once; DawaLink's team then looks at the new pin, which holds nothing up.
 */
/**
 * The pharmacy's own listing rule (the owner, 2026-11-19, BLD-D44): its boxes are listed
 * by themselves when they have this many days left or fewer, or never. The choices come
 * from the server (docs/04 N-54). One box can always be listed by hand, on its card.
 */
function ListingRule({ pharmacy }: { pharmacy: Profile }) {
  const queryClient = useQueryClient()
  const [days, setDays] = useState(pharmacy.auto_list_days)
  const [state, setState] = useState<'idle' | 'sending' | 'saved'>('idle')
  const [failed, setFailed] = useState<Failure | null>(null)
  // The longest wait first: it is what every pharmacy starts with.
  const choices = [...pharmacy.auto_list_choices].sort((a, b) => (a === 0 ? 1 : b === 0 ? -1 : b - a))

  async function submit(event: FormEvent) {
    event.preventDefault()
    setFailed(null)
    setState('sending')
    try {
      const saved = await unwrap(api.PATCH('/api/v1/pharmacy/me', { body: { auto_list_days: days } }))
      queryClient.setQueryData(['pharmacy', 'me'], saved)
      // The stock's lists say which boxes clients see: they are read again.
      await queryClient.invalidateQueries({ queryKey: ['pharmacy', 'stock'] })
      setState('saved')
    } catch (error) {
      setFailed(failureOf(error))
      setState('idle')
    }
  }

  return (
    <section className="panel" aria-labelledby="listing-rule">
      <div>
        <h2 id="listing-rule" className="panel__title">
          {s.ruleTitle}
        </h2>
        <span className="hint">{s.ruleNote}</span>
      </div>
      <form className="form" onSubmit={submit} noValidate>
        <fieldset className="choice">
          <legend>{s.ruleLabel}</legend>
          {choices.map((choice) => (
            <label key={choice} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 16 }}>
              <input
                type="radio"
                name="auto-list-days"
                checked={days === choice}
                onChange={() => {
                  setDays(choice)
                  setState('idle')
                }}
              />
              {s.ruleChoice(choice)}
            </label>
          ))}
          <span className="hint">{s.ruleHint}</span>
        </fieldset>
        <div role="status" aria-live="polite">
          {state === 'saved' && <Banner tone="green">{s.ruleSaved}</Banner>}
          {failed && <Banner tone="red">{errorMessage(failed.code)}</Banner>}
        </div>
        <button
          type="submit"
          className="pill-button"
          style={{ alignSelf: 'flex-start' }}
          disabled={state === 'sending' || days === pharmacy.auto_list_days}
        >
          {s.ruleSave}
        </button>
      </form>
    </section>
  )
}

function PlaceSettings({ pharmacy }: { pharmacy: Profile }) {
  const queryClient = useQueryClient()
  const districts = useDistricts()
  const [address, setAddress] = useState(pharmacy.address)
  const [district, setDistrict] = useState(String(pharmacy.district_id))
  const [pin, setPin] = useState(pharmacy.location)
  const [state, setState] = useState<'idle' | 'sending' | 'saved'>('idle')
  const [failed, setFailed] = useState<Failure | null>(null)

  // Only what changed is sent: an address nobody touched is never checked again.
  const changes: Schemas['SettingsChange'] = {
    ...(address.trim() !== pharmacy.address ? { address: address.trim() } : {}),
    ...(Number(district) !== pharmacy.district_id ? { district_id: Number(district) } : {}),
    ...(pin.lat !== pharmacy.location.lat || pin.lon !== pharmacy.location.lon ? { location: pin } : {}),
  }
  const nothing = Object.keys(changes).length === 0

  async function submit(event: FormEvent) {
    event.preventDefault()
    setFailed(null)
    setState('sending')
    try {
      const saved = await unwrap(api.PATCH('/api/v1/pharmacy/me', { body: changes }))
      queryClient.setQueryData(['pharmacy', 'me'], saved)
      setAddress(saved.address)
      setState('saved')
    } catch (error) {
      setFailed(failureOf(error))
      setState('idle')
    }
  }

  const wrong = (field: string) => (failed?.field === field ? (d.problems[field] ?? null) : null)
  return (
    <section className="panel" aria-labelledby="place">
      <div>
        <h2 id="place" className="panel__title">
          {s.placeTitle}
        </h2>
        <span className="hint">{s.placeNote}</span>
      </div>
      <form className="form" onSubmit={submit} noValidate>
        <TextInput
          label={d.address}
          size="md"
          autoComplete="street-address"
          value={address}
          onChange={(event) => {
            setAddress(event.currentTarget.value)
            setState('idle')
          }}
          error={wrong('address')}
        />
        <NativeSelect
          label={d.district}
          size="md"
          value={district}
          onChange={(event) => {
            setDistrict(event.currentTarget.value)
            setState('idle')
          }}
          error={wrong('district_id')}
          data={(districts.data ?? []).map((row) => ({ value: String(row.id), label: row.name }))}
        />
        <fieldset className="choice">
          <legend>{d.pin}</legend>
          <span className="hint">{d.pinHint}</span>
          <Suspense fallback={<p className="hint">{d.mapLoading}</p>}>
            <PinMap
              value={pin}
              center={pharmacy.location}
              onChange={(moved) => {
                setPin(moved)
                setState('idle')
              }}
            />
          </Suspense>
          {wrong('location') && (
            <span role="status" className="field-problem">
              {wrong('location')}
            </span>
          )}
        </fieldset>
        <div role="status" aria-live="polite">
          {state === 'saved' && <Banner tone="green">{s.placeSaved}</Banner>}
          {failed && !failed.field && <Banner tone="red">{errorMessage(failed.code)}</Banner>}
        </div>
        <button
          type="submit"
          className="pill-button"
          style={{ alignSelf: 'flex-start' }}
          disabled={state === 'sending' || nothing}
        >
          {s.placeSave}
        </button>
      </form>
    </section>
  )
}
