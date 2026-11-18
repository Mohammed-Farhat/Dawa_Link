import { NativeSelect, TextInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, lazy, Suspense, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { useDistricts } from '../client/data'
import {
  codeOf,
  type PharmacyStatus,
  useAdminPharmacies,
  useAdminPharmacy,
  useOverview,
  when,
} from './data'

// The map is downloaded only when an admin opens a pharmacy (docs/11 §10).
const PinMap = lazy(() => import('../pharmacy/PinMap'))

const s = strings.admin
const p = s.pharmacies
const one = s.pharmacy
const d = strings.pharmacy.details
const days = strings.pharmacy.hours.days

type Pharmacy = Schemas['AdminPharmacy']
type Pin = Schemas['Pin']
type Note = { tone: 'green' | 'red' | 'amber'; text: string }

const STATUSES: PharmacyStatus[] = ['PENDING', 'APPROVED', 'REJECTED', 'SUSPENDED']
const TONE: Record<PharmacyStatus, string> = {
  PENDING: 'amber',
  APPROVED: 'green',
  REJECTED: 'red',
  SUSPENDED: 'red',
}

/** AS-3 and AS-4: the approval queue first, then every pharmacy by status. */
export function PharmaciesPage() {
  const [status, setStatus] = useState<PharmacyStatus>('PENDING')
  const [typed, setTyped] = useState('')
  const found = useAdminPharmacies(status, typed.trim())
  const toCheck = useOverview().data?.pins_to_check ?? 0
  return (
    <main className="portal__main">
      <h1 className="page-title">{p.title}</h1>
      {/* A pharmacy that moved is among the approved ones: say so where the admin lands. */}
      {toCheck > 0 && status !== 'APPROVED' && (
        <Banner tone="amber">
          {p.movedWaiting(toCheck)}{' '}
          <button type="button" className="text-button" onClick={() => setStatus('APPROVED')}>
            {p.showMoved}
          </button>
        </Banner>
      )}
      <div className="tabs" role="tablist" aria-label={p.title}>
        {STATUSES.map((choice) => (
          <button
            key={choice}
            type="button"
            role="tab"
            aria-selected={status === choice}
            className="tabs__tab"
            onClick={() => setStatus(choice)}
          >
            {p.statuses[choice]}
          </button>
        ))}
      </div>
      <TextInput
        label={p.search}
        size="md"
        autoComplete="off"
        value={typed}
        onChange={(event) => setTyped(event.currentTarget.value)}
      />
      {found.loaded && found.items.length === 0 && (
        <div className="empty">{status === 'PENDING' && !typed.trim() ? p.noneWaiting : p.none}</div>
      )}
      {found.items.map((row) => (
        <article key={row.id} className="row-card">
          <Link to={`/admin/pharmacies/${row.id}`} className="row-link" aria-label={p.open(row.name)}>
            <div className="row-card__top">
              <h2 className="card__title" style={{ margin: 0 }}>
                {row.name}
              </h2>
              <span className={`status-pill status-pill--${row.pin_to_check ? 'amber' : TONE[row.status]}`}>
                {row.pin_to_check ? p.pinToCheck : row.info_requested ? p.infoAsked : p.statuses[row.status]}
              </span>
            </div>
            <span className="soft" style={{ fontSize: 15 }}>
              {row.district} · {p.license(row.license_number)}
            </span>
            <span className="hint">
              {row.status === 'PENDING' ? p.waitingSince(when(row.created_at)) : p.registered(when(row.created_at))}
            </span>
          </Link>
        </article>
      ))}
      {found.hasMore && (
        <button type="button" className="text-button" onClick={found.more}>
          {s.more}
        </button>
      )}
    </main>
  )
}

/** One pharmacy: what it typed, where its pin is, what the checks found, and the decision. */
export function PharmacyPage() {
  const { id = '' } = useParams()
  const found = useAdminPharmacy(id)
  // Kept here: the view below starts again when the pharmacy's details or status change,
  // and what the last action answered must still be on the screen.
  const [note, setNote] = useState<Note | null>(null)
  if (found.isError) {
    return (
      <main className="portal__main">
        <Banner tone="amber">{errorMessage(codeOf(found.error))}</Banner>
        <Link to="/admin" className="text-button">
          {s.back}
        </Link>
      </main>
    )
  }
  if (!found.data) return <p className="soft">{strings.common.loading}</p>
  // A new version of the details is a new form: what was typed over the old one is dropped.
  return (
    <PharmacyView
      key={found.data.version + found.data.status}
      pharmacy={found.data}
      note={note}
      setNote={setNote}
    />
  )
}

function hoursLines(pharmacy: Pharmacy): string[] {
  return days.map((day, weekday) => {
    const ranges = pharmacy.hours.filter((range) => range.weekday === weekday)
    const text = ranges.map((range) => `${range.open} to ${range.close}`).join(', ')
    return `${day}: ${text || one.closed}`
  })
}

function PharmacyView({
  pharmacy,
  note,
  setNote,
}: {
  pharmacy: Pharmacy
  note: Note | null
  setNote: (note: Note | null) => void
}) {
  const queryClient = useQueryClient()
  const [pin, setPin] = useState<Pin>(pharmacy.location)
  const pinMoved = pin.lat !== pharmacy.location.lat || pin.lon !== pharmacy.location.lon

  /** Shows what the API answered, and the page as it is now. */
  async function act(call: () => Promise<Pharmacy>, done: string) {
    setNote(null)
    try {
      const saved = await call()
      queryClient.setQueryData(['admin', 'pharmacy', pharmacy.id], saved)
      setNote({ tone: 'green', text: done })
    } catch (error) {
      const code = codeOf(error)
      setNote({ tone: code === 'CHANGED_SINCE' ? 'amber' : 'red', text: code === 'CHANGED_SINCE' ? s.changed : errorMessage(code) })
      if (code === 'CHANGED_SINCE') {
        await queryClient.invalidateQueries({ queryKey: ['admin', 'pharmacy', pharmacy.id] })
      }
      throw error
    } finally {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'pharmacies'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'overview'] })
    }
  }

  return (
    <div className="portal__columns">
      <main className="portal__main">
        <Link to="/admin" className="text-button" style={{ alignSelf: 'flex-start', paddingInlineStart: 0 }}>
          {s.back}
        </Link>
        <div className="row-card__top">
          <h1 className="page-title">{pharmacy.name}</h1>
          <span className={`status-pill status-pill--${TONE[pharmacy.status]}`}>
            {pharmacy.info_requested ? p.infoAsked : p.statuses[pharmacy.status]}
          </span>
        </div>
        <div role="status" aria-live="polite">
          {note && <Banner tone={note.tone}>{note.text}</Banner>}
        </div>
        {pharmacy.status_reason && <Banner tone="grey">{one.reasonGiven(pharmacy.status_reason)}</Banner>}

        <section className="panel" aria-labelledby="typed">
          <h2 id="typed" className="panel__title">
            {one.details}
          </h2>
          <dl className="card__lines">
            <Line label={d.name} value={pharmacy.name} />
            <Line label={d.license} value={pharmacy.license_number} />
            <Line
              label={d.phone}
              value={
                pharmacy.phone_changed_at
                  ? `${pharmacy.phone} · ${one.phoneChanged(when(pharmacy.phone_changed_at))}`
                  : pharmacy.phone
              }
            />
            <Line label={one.email} value={pharmacy.email} />
            <Line
              label={d.address}
              value={
                pharmacy.moved_at
                  ? `${pharmacy.address}, ${pharmacy.district} · ${one.moved(when(pharmacy.moved_at))}`
                  : `${pharmacy.address}, ${pharmacy.district}`
              }
            />
            <Line label={one.pickup} value={d.days(pharmacy.pickup_days)} />
          </dl>
          {pharmacy.status !== 'PENDING' && pharmacy.status !== 'REJECTED' && (
            <div>
              <span className="hint">{one.activity}</span>
              <dl className="card__lines">
                <Line label={one.liveListings} value={String(pharmacy.live_listings)} />
                <Line
                  label={one.lastStockUpdate}
                  value={
                    pharmacy.last_inventory_update ? when(pharmacy.last_inventory_update) : one.never
                  }
                />
                <Line
                  label={one.notAvailable}
                  value={one.notAvailableOf(
                    pharmacy.not_available_30d,
                    pharmacy.not_available_30d + pharmacy.handed_over_30d,
                  )}
                />
              </dl>
            </div>
          )}
          <div>
            <span className="hint">{one.hours}</span>
            <ul className="plain-list">
              {hoursLines(pharmacy).map((line) => (
                <li key={line} className="soft" style={{ fontSize: 15 }}>
                  {line}
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="panel" aria-labelledby="where">
          <div>
            <h2 id="where" className="panel__title">
              {one.where}
            </h2>
            <span className="hint">{one.whereHint}</span>
          </div>
          <Suspense fallback={<span className="soft">{strings.common.loading}</span>}>
            <PinMap value={pin} center={pharmacy.location} onChange={setPin} />
          </Suspense>
          {pinMoved && <Banner tone="amber">{one.pinMoved}</Banner>}
        </section>

        <EditDetails pharmacy={pharmacy} pin={pinMoved ? pin : null} act={act} />
      </main>

      <aside className="portal__aside">
        <section className="panel" aria-labelledby="checks">
          <h2 id="checks" className="panel__title">
            {one.checks}
          </h2>
          <ul className="plain-list" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <li>{one.emailConfirmed}</li>
            <li>{one.licenseUnique}</li>
            <li>
              {pharmacy.same_address.length === 0 ? (
                one.noSameAddress
              ) : (
                <>
                  <strong>{one.sameAddress}</strong>{' '}
                  {pharmacy.same_address.map((other) => (
                    <Link key={other.id} to={`/admin/pharmacies/${other.id}`} className="text-button">
                      {other.name}
                    </Link>
                  ))}
                </>
              )}
            </li>
            {pharmacy.pin_to_check && pharmacy.moved_at ? (
              <li style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <strong>{one.pinMovedByPharmacy(when(pharmacy.moved_at))}</strong>
                <button
                  type="button"
                  className="pill-button pill-button--grey"
                  onClick={() =>
                    void act(
                      () =>
                        unwrap(
                          api.POST('/api/v1/admin/pharmacies/{pharmacy_id}/check-pin', {
                            params: { path: { pharmacy_id: pharmacy.id } },
                          }),
                        ),
                      one.pinConfirmed,
                    ).catch(() => undefined)
                  }
                >
                  {one.pinIsRight}
                </button>
              </li>
            ) : (
              (pharmacy.pin_checked || pharmacy.status === 'PENDING') && (
                <li>{pharmacy.pin_checked ? one.pinChecked : one.pinNotChecked}</li>
              )
            )}
            <li className="soft">{one.nameCheck}</li>
          </ul>
        </section>
        {pharmacy.status === 'PENDING' && <Decide pharmacy={pharmacy} act={act} />}
        {(pharmacy.status === 'APPROVED' || pharmacy.status === 'SUSPENDED') && (
          <Suspension pharmacy={pharmacy} act={act} />
        )}
      </aside>
    </div>
  )
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="card__line">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

type Act = (call: () => Promise<Pharmacy>, done: string) => Promise<void>

/** [Approve], [Ask for more information] or [Reject] (SM-1). The two that say no need
 * words the pharmacy will read. */
function Decide({ pharmacy, act }: { pharmacy: Pharmacy; act: Act }) {
  const [asking, setAsking] = useState<'reject' | 'request-info' | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const path = { pharmacy_id: pharmacy.id }

  async function run(call: () => Promise<Pharmacy>, done: string) {
    setBusy(true)
    try {
      await act(call, done)
      setAsking(null)
      setReason('')
    } catch {
      // `act` has already said what went wrong.
    } finally {
      setBusy(false)
    }
  }

  function approve() {
    void run(
      () =>
        unwrap(
          api.POST('/api/v1/admin/pharmacies/{pharmacy_id}/approve', {
            params: { path },
            // The approval is of the details this page shows (docs/06 §12).
            body: { version: pharmacy.version },
          }),
        ),
      one.approved,
    )
  }

  function send(event: FormEvent) {
    event.preventDefault()
    if (asking === 'reject') {
      void run(
        () => unwrap(api.POST('/api/v1/admin/pharmacies/{pharmacy_id}/reject', { params: { path }, body: { reason } })),
        one.rejected,
      )
    } else {
      void run(
        () =>
          unwrap(api.POST('/api/v1/admin/pharmacies/{pharmacy_id}/request-info', { params: { path }, body: { reason } })),
        one.asked,
      )
    }
  }

  return (
    <section className="panel" aria-labelledby="decide">
      <h2 id="decide" className="panel__title">
        {one.decide}
      </h2>
      {asking === null ? (
        <>
          <button type="button" className="pill-button pill-button--green" disabled={busy} onClick={approve}>
            {one.approve}
          </button>
          <button type="button" className="pill-button pill-button--grey" onClick={() => setAsking('request-info')}>
            {one.askMore}
          </button>
          <button type="button" className="text-button" onClick={() => setAsking('reject')}>
            {one.reject}
          </button>
        </>
      ) : (
        <form className="form" onSubmit={send}>
          <label htmlFor="decision-reason" style={{ fontWeight: 600 }}>
            {asking === 'reject' ? one.rejectReason : one.askReason}
          </label>
          <textarea
            id="decision-reason"
            className="text-area"
            maxLength={300}
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
          />
          <button type="submit" className="pill-button" disabled={busy || !reason.trim()}>
            {asking === 'reject' ? one.confirmReject : one.confirmAsk}
          </button>
          <button type="button" className="text-button" onClick={() => setAsking(null)}>
            {one.cancel}
          </button>
        </form>
      )}
    </section>
  )
}

/** [Suspend] an approved pharmacy, or [Reinstate] a suspended one, with a reason the
 * pharmacy reads (SM-1). What clients already reserved there is kept. */
function Suspension({ pharmacy, act }: { pharmacy: Pharmacy; act: Act }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const suspended = pharmacy.status === 'SUSPENDED'
  const path = { pharmacy_id: pharmacy.id }

  async function send(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await act(
        () =>
          suspended
            ? unwrap(api.POST('/api/v1/admin/pharmacies/{pharmacy_id}/reinstate', { params: { path }, body: { reason } }))
            : unwrap(api.POST('/api/v1/admin/pharmacies/{pharmacy_id}/suspend', { params: { path }, body: { reason } })),
        suspended ? one.reinstated : one.suspended,
      )
      setReason('')
    } catch {
      // `act` has already said what went wrong.
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel" aria-labelledby="suspension">
      <div>
        <h2 id="suspension" className="panel__title">
          {suspended ? one.reinstate : one.suspend}
        </h2>
        <span className="hint">{suspended ? one.reinstateHint : one.suspendHint}</span>
      </div>
      <form className="form" onSubmit={send}>
        <label htmlFor="suspension-reason" style={{ fontWeight: 600 }}>
          {one.suspensionReason}
        </label>
        <textarea
          id="suspension-reason"
          className="text-area"
          maxLength={300}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        <button
          type="submit"
          className={suspended ? 'pill-button' : 'pill-button pill-button--danger'}
          disabled={busy || !reason.trim()}
        >
          {suspended ? one.confirmReinstate : one.confirmSuspend}
        </button>
      </form>
    </section>
  )
}

/** An admin corrects a name, a licence, a phone, an address or the pin, with a reason.
 * Only what was changed is sent, so a field nobody touched is never checked again. */
function EditDetails({ pharmacy, pin, act }: { pharmacy: Pharmacy; pin: Pin | null; act: Act }) {
  const districts = useDistricts()
  const [name, setName] = useState(pharmacy.name)
  const [license, setLicense] = useState(pharmacy.license_number)
  const [phone, setPhone] = useState(pharmacy.phone)
  const [address, setAddress] = useState(pharmacy.address)
  const [district, setDistrict] = useState(String(pharmacy.district_id))
  const [reason, setReason] = useState('')
  const [refused, setRefused] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const changes: Schemas['AdminPharmacyEdit'] = {
    reason,
    ...(name.trim() !== pharmacy.name ? { name: name.trim() } : {}),
    ...(license.trim() !== pharmacy.license_number ? { license_number: license.trim() } : {}),
    ...(phone.trim() !== pharmacy.phone ? { phone: phone.trim() } : {}),
    ...(address.trim() !== pharmacy.address ? { address: address.trim() } : {}),
    ...(Number(district) !== pharmacy.district_id ? { district_id: Number(district) } : {}),
    ...(pin ? { location: pin } : {}),
  }
  const nothing = Object.keys(changes).length === 1

  async function save(event: FormEvent) {
    event.preventDefault()
    setRefused(null)
    setBusy(true)
    try {
      await act(
        () =>
          unwrap(
            api.PATCH('/api/v1/admin/pharmacies/{pharmacy_id}', {
              params: { path: { pharmacy_id: pharmacy.id } },
              body: changes,
            }),
          ),
        one.saved,
      )
    } catch (error) {
      const field = error instanceof ApiFailure ? error.details.field : null
      setRefused(typeof field === 'string' ? field : null)
    } finally {
      setBusy(false)
    }
  }

  const wrong = (field: string) => (refused === field ? (d.problems[field] ?? errorMessage('VALIDATION_ERROR')) : null)
  return (
    <section className="panel" aria-labelledby="edit">
      <div>
        <h2 id="edit" className="panel__title">
          {one.edit}
        </h2>
        <span className="hint">{one.editHint}</span>
      </div>
      <form className="form" onSubmit={save} noValidate>
        <TextInput label={d.name} size="md" value={name} onChange={(e) => setName(e.currentTarget.value)} error={wrong('name')} />
        <TextInput
          label={d.license}
          size="md"
          value={license}
          onChange={(e) => setLicense(e.currentTarget.value)}
          error={wrong('license_number')}
        />
        <TextInput
          label={d.phone}
          size="md"
          type="tel"
          value={phone}
          onChange={(e) => setPhone(e.currentTarget.value)}
          error={wrong('phone')}
        />
        <TextInput
          label={d.address}
          size="md"
          value={address}
          onChange={(e) => setAddress(e.currentTarget.value)}
          error={wrong('address')}
        />
        <NativeSelect
          label={d.district}
          size="md"
          value={district}
          onChange={(e) => setDistrict(e.currentTarget.value)}
          data={(districts.data ?? []).map((row) => ({ value: String(row.id), label: row.name }))}
        />
        <TextInput
          label={s.reason}
          description={s.reasonHint}
          size="md"
          maxLength={300}
          value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
        />
        <button
          type="submit"
          className="pill-button"
          style={{ alignSelf: 'flex-start' }}
          disabled={busy || nothing || !reason.trim()}
        >
          {one.save}
        </button>
      </form>
    </section>
  )
}
