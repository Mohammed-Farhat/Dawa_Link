import { NativeSelect, TextInput } from '@mantine/core'
import { lazy, Suspense } from 'react'

import type { Schemas } from '../../api/client'
import { strings } from '../../strings/en'
import {
  closing,
  type Draft,
  problemsOf,
  type Range,
  START,
  USUAL,
  type Week,
} from './draft'

// The map is the heaviest thing on the website, and only a pharmacy putting its pin
// needs it: it is downloaded when this form opens, never before (docs/11 §10).
const PinMap = lazy(() => import('./PinMap'))

const d = strings.pharmacy.details
const h = strings.pharmacy.hours

/**
 * The fields a pharmacy fills in about itself (PS-1): at registration, and again while it
 * waits or after a rejection. `refused` is the field the API refused, if any.
 */
export function DetailsFields({
  draft,
  onChange,
  districts,
  tried,
  refused,
}: {
  draft: Draft
  onChange: (next: Draft) => void
  districts: Schemas['District'][]
  tried: boolean
  refused: string | null
}) {
  const problems = problemsOf(draft)
  const wrong = (field: string) =>
    (tried && problems[field]) || (refused === field && d.problems[field]) || null
  const set = (change: Partial<Draft>) => onChange({ ...draft, ...change })
  const district = districts.find((row) => String(row.id) === draft.district)
  return (
    <>
      <TextInput
        label={d.name}
        description={d.nameHint}
        size="md"
        autoComplete="organization"
        value={draft.name}
        onChange={(event) => set({ name: event.currentTarget.value })}
        error={wrong('name')}
      />
      <TextInput
        label={d.license}
        size="md"
        autoComplete="off"
        value={draft.license}
        onChange={(event) => set({ license: event.currentTarget.value })}
        error={wrong('license_number')}
      />
      <TextInput
        label={d.phone}
        description={d.phoneHint}
        size="md"
        type="tel"
        autoComplete="tel"
        value={draft.phone}
        onChange={(event) => set({ phone: event.currentTarget.value })}
        error={wrong('phone')}
      />
      <TextInput
        label={d.address}
        size="md"
        autoComplete="street-address"
        value={draft.address}
        onChange={(event) => set({ address: event.currentTarget.value })}
        error={wrong('address')}
      />
      <NativeSelect
        label={d.district}
        size="md"
        value={draft.district}
        onChange={(event) => set({ district: event.currentTarget.value })}
        error={wrong('district_id')}
        data={[
          { value: '', label: '' },
          ...districts.map((row) => ({ value: String(row.id), label: row.name })),
        ]}
      />

      <fieldset className="choice">
        <legend>{d.pin}</legend>
        <span className="hint">{d.pinHint}</span>
        <Suspense fallback={<p className="hint">{d.mapLoading}</p>}>
          <PinMap
            value={draft.pin}
            center={district ? { lat: district.lat, lon: district.lon } : START}
            onChange={(pin) => set({ pin })}
          />
        </Suspense>
        <span role="status" className={wrong('location') ? 'field-problem' : 'hint'}>
          {draft.pin ? d.pinSet : wrong('location')}
        </span>
      </fieldset>

      <HoursFields
        week={draft.week}
        onChange={(week) => set({ week })}
        problem={(tried && problems.hours) || (refused === 'hours' ? d.problems.hours : null)}
      />
      <PickupDays value={draft.pickupDays} onChange={(pickupDays) => set({ pickupDays })} />
    </>
  )
}

export function PickupDays({ value, onChange }: { value: number; onChange: (days: number) => void }) {
  return (
    <fieldset className="choice">
      <legend>{d.pickupDays}</legend>
      <div className="chips">
        {[1, 2, 3].map((days) => (
          <button
            key={days}
            type="button"
            className="chip"
            aria-pressed={value === days}
            onClick={() => onChange(days)}
          >
            {d.days(days)}
          </button>
        ))}
      </div>
      <span className="hint">{d.pickupDaysHint}</span>
    </fieldset>
  )
}

/** A day that closes at midday and reopens: 08:00 to 20:00 becomes 08:00 to 13:00 and
 * 16:00 to 20:00, for the pharmacy to correct. */
function withAfternoon(day: Range): Range[] {
  const morning = day.open < '13:00' && closing(day) > '13:00' ? { ...day, close: '13:00' } : day
  const evening = closing(day) > '16:00' ? day.close : '20:00'
  return [morning, { open: closing(morning) > '16:00' ? closing(morning) : '16:00', close: evening }]
}

/** The week's opening hours: up to two ranges a day (R-T2), for a midday closing. */
export function HoursFields({
  week,
  onChange,
  problem,
}: {
  week: Week
  onChange: (next: Week) => void
  problem: string | null
}) {
  const setDay = (day: number, ranges: Range[]) =>
    onChange(week.map((existing, index) => (index === day ? ranges : existing)))
  return (
    <fieldset className="choice">
      <legend>{d.hours}</legend>
      {week.map((ranges, day) => {
        const name = h.days[day] ?? ''
        return (
          <div key={name} className="hours-row">
            <label className="hours-row__day">
              <input
                type="checkbox"
                checked={ranges.length > 0}
                aria-label={h.open(name)}
                onChange={(event) => setDay(day, event.currentTarget.checked ? [{ ...USUAL }] : [])}
              />
              {name}
            </label>
            {ranges.length === 0 && <span className="hint">{h.closed}</span>}
            {ranges.map((range, index) => (
              <span key={index} className="hours-row__range">
                <input
                  type="time"
                  className="time-input"
                  aria-label={h.opens(name, index > 0)}
                  value={range.open}
                  onChange={(event) =>
                    setDay(
                      day,
                      ranges.map((existing, at) =>
                        at === index ? { ...existing, open: event.currentTarget.value } : existing,
                      ),
                    )
                  }
                />
                <span aria-hidden="true">{h.to}</span>
                <input
                  type="time"
                  className="time-input"
                  aria-label={h.closes(name, index > 0)}
                  value={range.close}
                  onChange={(event) =>
                    setDay(
                      day,
                      ranges.map((existing, at) =>
                        at === index ? { ...existing, close: event.currentTarget.value } : existing,
                      ),
                    )
                  }
                />
              </span>
            ))}
            {ranges.length === 1 && (
              <button
                type="button"
                className="text-button"
                aria-label={h.addRange(name)}
                onClick={() => setDay(day, withAfternoon(ranges[0] ?? USUAL))}
              >
                {h.addShort}
              </button>
            )}
            {ranges.length === 2 && (
              <button
                type="button"
                className="text-button"
                aria-label={h.removeRange(name)}
                onClick={() => setDay(day, ranges.slice(0, 1))}
              >
                {h.removeShort}
              </button>
            )}
          </div>
        )
      })}
      <span className="hint">{h.midnight}</span>
      {problem && (
        <span role="alert" className="field-problem">
          {problem}
        </span>
      )}
    </fieldset>
  )
}
