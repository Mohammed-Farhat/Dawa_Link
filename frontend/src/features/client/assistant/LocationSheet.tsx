import { Modal, NativeSelect } from '@mantine/core'
import { lazy, Suspense, useState } from 'react'

import { ApiFailure } from '../../../api/client'
import { PinIcon } from '../../../components/icons'
import { Banner } from '../../../components/layout'
import { errorMessage, strings } from '../../../strings/en'
import { useDistricts } from '../data'

// The map is downloaded only when the client asks for it (docs/11 §10): a phone that
// shares its location, or names a district, never loads it.
const PinMap = lazy(() => import('../../pharmacy/PinMap'))

const s = strings.chat.location

/** Where the map opens before a district is chosen: Beirut. */
const START = { lat: 33.8938, lon: 35.5018 }

export type ChosenPlace = { lat: number; lon: number } | { district_id: number; name: string }

/**
 * Where travel times are counted from, in the chat or on the search page (docs/11 §11).
 *
 * The browser asks for the location **only after the client taps**, and we say why
 * first. What happens with the choice is the caller's: the chat sends it to our API,
 * which rounds it; the search page keeps it in memory for its next searches. Either way
 * it is never part of what the AI reads.
 *
 * "Pick on the map" (BLD-D16) is for a computer, or for a client who won't share the
 * device's location: they put a pin where they are. The point is handled exactly like a
 * shared location, and it stays in this component's memory until [Use this place]: it
 * is never in an address, in the browser's history or in its storage. The map's
 * pictures come from OpenStreetMap, which sees the part of the map looked at, never the
 * pin (docs/10 §4.3).
 */
export function LocationSheet({
  opened,
  onClose,
  onChoose,
}: {
  opened: boolean
  onClose: () => void
  onChoose: (place: ChosenPlace) => Promise<void> | void
}) {
  const districts = useDistricts()
  const [district, setDistrict] = useState('')
  const [failed, setFailed] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [mapOpen, setMapOpen] = useState(false)
  const [pin, setPin] = useState<{ lat: number; lon: number } | null>(null)

  async function choose(place: ChosenPlace) {
    setSending(true)
    setFailed(null)
    try {
      await onChoose(place)
      onClose()
    } catch (error) {
      setFailed(errorMessage(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'))
    } finally {
      setSending(false)
    }
  }

  function useMine() {
    if (!('geolocation' in navigator)) {
      setFailed(s.refused)
      return
    }
    navigator.geolocation.getCurrentPosition(
      (position) => void choose({ lat: position.coords.latitude, lon: position.coords.longitude }),
      () => setFailed(s.refused),
      { timeout: 10_000, maximumAge: 60_000 },
    )
  }

  const chosen = (districts.data ?? []).find((row) => String(row.id) === district)
  return (
    <Modal opened={opened} onClose={onClose} title={s.title} centered radius="xl">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <p className="sheet-text">{s.why}</p>
        <button type="button" className="pill-button" onClick={useMine} disabled={sending}>
          <PinIcon small />
          {s.useMine}
        </button>
        <NativeSelect
          label={s.orDistrict}
          size="md"
          value={district}
          onChange={(event) => setDistrict(event.currentTarget.value)}
          data={[
            { value: '', label: '' },
            ...(districts.data ?? []).map((row) => ({ value: String(row.id), label: row.name })),
          ]}
        />
        <button
          type="button"
          className="pill-button pill-button--grey"
          disabled={!chosen || sending}
          onClick={() => chosen && void choose({ district_id: chosen.id, name: chosen.name })}
        >
          {s.useDistrict}
        </button>
        {!mapOpen ? (
          <button type="button" className="pill-button pill-button--grey" onClick={() => setMapOpen(true)}>
            {s.pickOnMap}
          </button>
        ) : (
          <fieldset className="choice">
            <legend>{s.pickOnMap}</legend>
            <span className="hint">{s.mapHint}</span>
            <Suspense fallback={<p className="hint">{strings.pharmacy.details.mapLoading}</p>}>
              <PinMap
                value={pin}
                // Around the district chosen above, if one is; otherwise Beirut.
                center={chosen ? { lat: chosen.lat, lon: chosen.lon } : START}
                onChange={setPin}
              />
            </Suspense>
            <button
              type="button"
              className="pill-button"
              disabled={!pin || sending}
              onClick={() => pin && void choose(pin)}
            >
              {s.usePin}
            </button>
          </fieldset>
        )}
        {failed && (
          <Banner tone="red" alert>
            {failed}
          </Banner>
        )}
      </div>
    </Modal>
  )
}
