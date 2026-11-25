import { lazy, Suspense, useState } from 'react'

import { PinIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { strings } from '../../strings/en'
import { useDistricts } from './data'
import { HomeArea } from './HomeArea'
import type { Pin, WhereValue } from './where'

// The map is downloaded only when the client asks for it (docs/11 §10): its pictures
// come from OpenStreetMap's servers, which see who looks at which part of the map
// (docs/10 §4.3). Opening the form, or the profile, never loads it.
const PinMap = lazy(() => import('../pharmacy/PinMap'))

const s = strings.signUp
const w = strings.where

/** Beirut: where the map opens before anything is known. */
const START = { lat: 33.8938, lon: 35.5018 }

/**
 * Where a client lives, on the sign-up form and in the profile: **either** a place on a
 * map, with [Use my location] to put the pin where the device is, **or** the
 * governorate, the district and the town. Never both to fill.
 *
 * The browser asks for the device's location only after the tap, and the page says why
 * first (docs/11 §11). The map itself appears after a tap too: [Pick on the map], or
 * [Use my location], which shows where the pin was put. The pin stays in this form's
 * memory until the form is sent, in a request's body: never in an address or in the
 * browser's storage.
 *
 * `onLocated`: the profile saves at once what [Use my location] found.
 * `untitled`: the section around it already says "Where you live" (the profile), so the
 * title is kept for a screen reader only.
 */
export function WhereYouLive({
  value,
  onChange,
  problem,
  onLocated,
  untitled = false,
}: {
  value: WhereValue
  onChange: (next: WhereValue) => void
  problem?: string | null | false
  onLocated?: (pin: Pin) => void
  untitled?: boolean
}) {
  const districts = useDistricts()
  const [refused, setRefused] = useState(false)
  const [asking, setAsking] = useState(false)
  const [mapOpen, setMapOpen] = useState(false)
  const district = (districts.data ?? []).find((row) => String(row.id) === value.area.district)

  function useMine() {
    setRefused(false)
    if (!('geolocation' in navigator)) {
      setRefused(true)
      return
    }
    setAsking(true)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const pin = { lat: position.coords.latitude, lon: position.coords.longitude }
        setAsking(false)
        // The client sees where the pin was put, and can move it.
        setMapOpen(true)
        onChange({ ...value, mode: 'map', pin })
        onLocated?.(pin)
      },
      () => {
        setAsking(false)
        setRefused(true)
      },
      { timeout: 10_000, maximumAge: 60_000 },
    )
  }

  return (
    <fieldset className="choice">
      <legend className={untitled ? 'sr-only' : undefined}>{s.whereTitle}</legend>
      <span className="hint">{s.whereHint}</span>
      <div className="tabs" role="radiogroup" aria-label={s.whereTitle}>
        {(['map', 'area'] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={value.mode === mode}
            tabIndex={value.mode === mode ? 0 : -1}
            onKeyDown={(event) => {
              if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
              event.preventDefault()
              const next = mode === 'map' ? 'area' : 'map'
              onChange({ ...value, mode: next })
              const radios = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="radio"]')
              radios?.[next === 'map' ? 0 : 1]?.focus()
            }}
            className="tabs__tab"
            onClick={() => onChange({ ...value, mode })}
          >
            {w[mode]}
          </button>
        ))}
      </div>

      {value.mode === 'map' ? (
        <>
          <span className="hint">{w.mapWhy}</span>
          <span style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" className="pill-button pill-button--grey" onClick={useMine} disabled={asking}>
              <PinIcon small />
              {w.useMine}
            </button>
            {!mapOpen && (
              <button type="button" className="pill-button pill-button--grey" onClick={() => setMapOpen(true)}>
                {value.pin ? w.showMap : w.openMap}
              </button>
            )}
          </span>
          {refused && <Banner tone="amber">{w.refused}</Banner>}
          {mapOpen && (
            <Suspense fallback={<p className="hint">{strings.pharmacy.details.mapLoading}</p>}>
              <PinMap
                value={value.pin}
                center={value.pin ?? (district ? { lat: district.lat, lon: district.lon } : START)}
                onChange={(pin) => onChange({ ...value, pin })}
                label={w.mapLabel}
              />
            </Suspense>
          )}
          {(value.pin || mapOpen) && (
            <span className={`status-pill status-pill--${value.pin ? 'green' : 'grey'}`}>
              <PinIcon small />
              {value.pin ? w.pinPut : w.pinMissing}
            </span>
          )}
        </>
      ) : (
        <HomeArea value={value.area} onChange={(area) => onChange({ ...value, area })} />
      )}
      {problem && (
        // `data-problem`: after a refused submit the focus comes here, like to a box in
        // error (components/FormProblems.tsx), and the sentence is read.
        <span className="field-problem" role="alert" data-problem tabIndex={-1}>
          {problem}
        </span>
      )}
    </fieldset>
  )
}
