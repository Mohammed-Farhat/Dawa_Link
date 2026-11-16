import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { ChangePassword } from '../../components/ChangePassword'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { useDistricts } from '../client/data'
import { DetailsFields, HoursFields, PickupDays } from './details'
import { bodyOf, draftOf, hoursOf, problemsOf, weekOf, weekProblem } from './draft'

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
 * PS-10: what an approved pharmacy changes by itself: its opening hours and how long it
 * keeps a reservation. Its name, licence, phone, address and pin were checked by
 * DawaLink's team, and only they change them (docs/10 TM-D2, TH-59).
 */
export function SettingsPage({ pharmacy }: { pharmacy: Profile }) {
  const queryClient = useQueryClient()
  const [week, setWeek] = useState(() => weekOf(pharmacy.hours))
  const [pickupDays, setPickupDays] = useState(pharmacy.pickup_days)
  const [state, setState] = useState<'idle' | 'sending' | 'saved'>('idle')
  const [tried, setTried] = useState(false)
  const [failed, setFailed] = useState<Failure | null>(null)
  const approved = pharmacy.status === 'APPROVED'

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setFailed(null)
    if (weekProblem(week)) return
    setState('sending')
    try {
      const saved = await unwrap(
        api.PATCH('/api/v1/pharmacy/me', { body: { hours: hoursOf(week), pickup_days: pickupDays } }),
      )
      queryClient.setQueryData(['pharmacy', 'me'], saved)
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
            <div role="status" aria-live="polite">
              {state === 'saved' && <Banner tone="green">{d.saved}</Banner>}
              {failed && failed.field !== 'hours' && <Banner tone="red">{errorMessage(failed.code)}</Banner>}
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
          <div className="card__line">
            <dt>{d.phone}</dt>
            <dd>{pharmacy.phone}</dd>
          </div>
          <div className="card__line">
            <dt>{d.address}</dt>
            <dd>
              {pharmacy.address}, {pharmacy.district}
            </dd>
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
