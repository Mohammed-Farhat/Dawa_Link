import { Modal } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { CheckIcon, PrescriptionIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { calendarDate, lbp, plainAmount } from '../../format'
import { errorMessage, strings } from '../../strings/en'

const s = strings.pharmacy

type Reservation = Schemas['PharmacyReservation']

const TONE: Record<Reservation['state'], string> = {
  RESERVED: 'green',
  PICKED_UP: 'green',
  NOT_AVAILABLE: 'red',
  EXPIRED_NO_SHOW: 'red',
  CANCELLED_BY_CLIENT: 'grey',
  CANCELLED_BY_SYSTEM: 'grey',
}

/**
 * One reservation as the pharmacist sees it (PS-4): the order number, the product, the
 * batch to take from the shelf, the price to ask for. **Nothing about the client.**
 *
 * [Picked up] is one tap. [Not available] asks which packs first, because it takes them
 * out of the stock.
 */
export function ReservationCard({ reservation }: { reservation: Reservation }) {
  const queryClient = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [units, setUnits] = useState<number | null>(null)
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const waiting = reservation.state === 'RESERVED'

  async function act(action: 'picked-up' | 'not-available') {
    setSending(true)
    setFailed(null)
    try {
      if (action === 'picked-up') {
        await unwrap(
          api.POST('/api/v1/pharmacy/reservations/{reservation_id}/picked-up', {
            params: { path: { reservation_id: reservation.id } },
          }),
        )
      } else {
        await unwrap(
          api.POST('/api/v1/pharmacy/reservations/{reservation_id}/not-available', {
            params: { path: { reservation_id: reservation.id } },
            body: { units },
          }),
        )
        setAsking(false)
      }
    } catch (error) {
      setFailed(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
    } finally {
      // Whatever happened, show the reservation as the server has it now.
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
      setSending(false)
    }
  }

  return (
    <article className="counter-card" aria-label={s.reservation(reservation.ref)}>
      <div className="counter-card__facts">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span className="order-ref" style={{ fontSize: 22, letterSpacing: 2 }}>
            {reservation.ref}
          </span>
          <span className={`status-pill status-pill--${TONE[reservation.state]}`}>
            {reservation.status_text}
          </span>
        </div>
        <span style={{ fontSize: 18, fontWeight: 600 }}>
          {reservation.product.name} × {reservation.qty}
        </span>
        <span className="soft" style={{ fontSize: 15 }}>
          {s.batchLine(
            reservation.batch,
            calendarDate(reservation.expiry_date),
            plainAmount(reservation.price_each.lbp),
            lbp(reservation.total.lbp),
          )}
        </span>
        {reservation.product.prescription_required && waiting && (
          <span className="status-pill status-pill--amber">
            <PrescriptionIcon small />
            {s.checkPrescription}
          </span>
        )}
        {failed && (
          <Banner tone="red" alert>
            {errorMessage(failed)}
          </Banner>
        )}
      </div>

      {waiting && (
        <div className="counter-card__actions">
          <button
            type="button"
            className="pill-button pill-button--green pill-button--tall"
            disabled={sending}
            onClick={() => void act('picked-up')}
          >
            <CheckIcon />
            {s.pickedUp}
          </button>
          <button
            type="button"
            className="pill-button pill-button--outline"
            disabled={sending}
            onClick={() => {
              setUnits(null)
              setAsking(true)
            }}
          >
            {s.notAvailable}
          </button>
        </div>
      )}

      <Modal opened={asking} onClose={() => setAsking(false)} title={s.notAvailableTitle} centered radius="xl">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <p className="sheet-text">{s.notAvailableBody}</p>
          <fieldset className="choice">
            <legend className="sr-only">{s.notAvailableTitle}</legend>
            <div className="chips">
              <button type="button" className="chip" aria-pressed={units === null} onClick={() => setUnits(null)}>
                {s.allPacks(reservation.qty)}
              </button>
              {Array.from({ length: reservation.qty - 1 }, (_, index) => index + 1).map((count) => (
                <button
                  key={count}
                  type="button"
                  className="chip"
                  aria-pressed={units === count}
                  onClick={() => setUnits(count)}
                >
                  {s.somePacks(count)}
                </button>
              ))}
            </div>
          </fieldset>
          <button
            type="button"
            className="pill-button pill-button--danger"
            disabled={sending}
            onClick={() => void act('not-available')}
          >
            {s.confirmNotAvailable}
          </button>
          <button type="button" className="pill-button pill-button--grey" onClick={() => setAsking(false)}>
            {strings.common.cancel}
          </button>
        </div>
      </Modal>
    </article>
  )
}
