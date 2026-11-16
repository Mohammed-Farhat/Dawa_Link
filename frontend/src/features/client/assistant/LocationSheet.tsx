import { Modal, NativeSelect } from '@mantine/core'
import { useState } from 'react'

import { ApiFailure } from '../../../api/client'
import { PinIcon } from '../../../components/icons'
import { Banner } from '../../../components/layout'
import { errorMessage, strings } from '../../../strings/en'
import { useDistricts } from '../data'

const s = strings.chat.location

export type ChosenPlace = { lat: number; lon: number } | { district_id: number; name: string }

/**
 * Where travel times are counted from, in the chat or on the search page (docs/11 §11).
 *
 * The browser asks for the location **only after the client taps**, and we say why
 * first. What happens with the choice is the caller's: the chat sends it to our API,
 * which rounds it; the search page keeps it in memory for its next searches. Either way
 * it is never part of what the AI reads. "Pick on the map" joins these two choices with
 * the map's own slice (BLD-D16).
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
        {failed && (
          <Banner tone="red" alert>
            {failed}
          </Banner>
        )}
      </div>
    </Modal>
  )
}
