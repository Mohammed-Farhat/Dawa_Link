import { Modal } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { CheckIcon, PrescriptionIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { reservationTone } from '../../components/reservationTone'
import { calendarDate, lbp, plainAmount } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { type CardNotice, type OnNotice } from './notice'

const s = strings.pharmacy

type Reservation = Schemas['PharmacyReservation']

/**
 * One reservation as the pharmacist sees it (PS-4): the order number, the product, the
 * batch to take from the shelf, the price to ask for. **Nothing about the client.**
 *
 * [Picked up] is one tap. [Not available] asks which packs first, because it takes them
 * out of the stock. What the server answered is kept by the page (`notice`): a card that
 * was handed over leaves the list of those to hand over, and the answer stays.
 */
export function ReservationCard({
  reservation,
  notice,
  onNotice,
}: {
  reservation: Reservation
  notice: CardNotice | null
  onNotice: OnNotice
}) {
  const queryClient = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [units, setUnits] = useState<number | null>(null)
  const [sending, setSending] = useState(false)
  const waiting = reservation.state === 'RESERVED'

  async function act(action: 'picked-up' | 'not-available') {
    setSending(true)
    onNotice(null)
    try {
      if (action === 'picked-up') {
        await unwrap(
          api.POST('/api/v1/pharmacy/reservations/{reservation_id}/picked-up', {
            params: { path: { reservation_id: reservation.id } },
          }),
        )
        onNotice({ key: reservation.id, tone: 'green', text: s.pickedUpDone(reservation.ref) })
      } else {
        await unwrap(
          api.POST('/api/v1/pharmacy/reservations/{reservation_id}/not-available', {
            params: { path: { reservation_id: reservation.id } },
            body: { units },
          }),
        )
        setAsking(false)
        onNotice({ key: reservation.id, tone: 'green', text: s.notAvailableDone(reservation.ref) })
      }
    } catch (error) {
      // A refusal is said where the pharmacist is looking: in the open dialog, or on
      // the card, never behind a dialog that stays open.
      const code = error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
      onNotice({ key: reservation.id, tone: 'red', text: errorMessage(code) })
    } finally {
      // Whatever happened, show the reservation as the server has it now.
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
      setSending(false)
    }
  }

  const said = notice && (
    <Banner tone={notice.tone} alert={notice.tone === 'red'}>
      {notice.text}
    </Banner>
  )
  return (
    // Focusable from code: a number found at the counter moves the focus here.
    <article className="counter-card" aria-label={s.reservation(reservation.ref)} tabIndex={-1}>
      <div className="counter-card__facts">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span className="order-ref" style={{ fontSize: 22, letterSpacing: 2 }}>
            {reservation.ref}
          </span>
          <span className={`status-pill status-pill--${reservationTone(reservation.state)}`}>
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
        {!asking && said}
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
              onNotice(null)
              setUnits(null)
              setAsking(true)
            }}
          >
            {s.notAvailable}
          </button>
        </div>
      )}

      <Modal
        opened={asking}
        onClose={() => setAsking(false)}
        title={reservation.qty === 1 ? s.notAvailableTitleOne : s.notAvailableTitle}
        centered
        radius="xl"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <p className="sheet-text">{s.notAvailableBody}</p>
          {/* One pack: there is nothing to choose. */}
          {reservation.qty > 1 && (
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
          )}
          {asking && said}
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
