import { Modal } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { CheckIcon, CloseIcon, MapIcon, PhoneIcon, PrescriptionIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { aboutUsd, calendarDate, dayAndClock, directionsUrl, lbp } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { useReservation } from './data'

const s = strings.ticket

type Reservation = Schemas['Reservation']

// One word and one color per state (docs/11 §2.1): color is never the only signal.
const TONE: Record<Reservation['state'], 'green' | 'red' | 'grey'> = {
  RESERVED: 'green',
  PICKED_UP: 'green',
  NOT_AVAILABLE: 'red',
  EXPIRED_NO_SHOW: 'red',
  CANCELLED_BY_CLIENT: 'grey',
  CANCELLED_BY_SYSTEM: 'grey',
}

function statusWord(reservation: Reservation): string {
  // "Reserved: pick up by today 21:00" is cut to its first word on a small badge.
  return reservation.status_text.split(':')[0]
}

/** CS-10: the pickup ticket. The order number, huge, for the pharmacist to read. */
export function TicketPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const found = useReservation(id)
  const [asking, setAsking] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)

  async function cancel() {
    setCancelling(true)
    setFailed(null)
    try {
      const cancelled = await unwrap(
        api.POST('/api/v1/reservations/{reservation_id}/cancel', {
          params: { path: { reservation_id: id } },
        }),
      )
      queryClient.setQueryData(['reservation', id], cancelled)
      await queryClient.invalidateQueries({ queryKey: ['reservations'] })
      setAsking(false)
    } catch (error) {
      setFailed(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
    } finally {
      setCancelling(false)
    }
  }

  const reservation = found.data
  return (
    <div className="ticket-screen">
      <main className="ticket-screen__inner">
        <header className="ticket-screen__top">
          <button
            type="button"
            className="round-button round-button--dark"
            aria-label={strings.common.close}
            onClick={() => navigate(-1)}
          >
            <CloseIcon />
          </button>
          <span>{s.header}</span>
          <span style={{ width: 48 }} />
        </header>

        {found.isPending && <p>{strings.common.loading}</p>}
        {found.isError && (
          <>
            <Banner tone="red" alert>
              {s.notFound}
            </Banner>
            <Link to="/" className="pill-button pill-button--dark">
              {strings.notFound.back}
            </Link>
          </>
        )}

        {reservation && (
          <>
            <section className="ticket" aria-label={s.header}>
              <div className="ticket__head">
                <span className={`status-pill status-pill--${TONE[reservation.state]}`} style={{ alignSelf: 'center' }}>
                  {reservation.state === 'RESERVED' && <CheckIcon small />}
                  {statusWord(reservation)}
                </span>
                <span className="ticket__label">{s.orderNumber}</span>
                <span className="ticket__ref">{reservation.ref}</span>
                <span className="ticket__product">
                  {reservation.product.name} × {reservation.qty}
                </span>
              </div>
              <div className="ticket__tear" aria-hidden="true">
                <span />
              </div>
              <dl className="ticket__facts">
                {reservation.state === 'RESERVED' && reservation.deadline && (
                  <div>
                    <dt>{s.pickUpBy}</dt>
                    <dd>{dayAndClock(reservation.deadline, reservation.server_now)}</dd>
                  </div>
                )}
                <div>
                  <dt>{s.pay}</dt>
                  <dd>{lbp(reservation.total.lbp)}</dd>
                  {aboutUsd(reservation.total) && (
                    <dd className="ticket__sub">{aboutUsd(reservation.total)}</dd>
                  )}
                </div>
                {reservation.saving.lbp > 0 && (
                  <div>
                    <dt>{s.youSave}</dt>
                    <dd>
                      <span className="saving" style={{ fontSize: 15, padding: '2px 10px' }}>
                        {lbp(reservation.saving.lbp)}
                      </span>
                    </dd>
                  </div>
                )}
                <div className="ticket__wide">
                  <dt>{s.pharmacy}</dt>
                  <dd>{reservation.pharmacy.name}</dd>
                  <dd className="ticket__sub">
                    {reservation.pharmacy.address}, {reservation.pharmacy.district}
                  </dd>
                  <dd className="ticket__sub">{s.expiresOn(calendarDate(reservation.expiry_date))}</dd>
                </div>
              </dl>
              {reservation.state === 'RESERVED' && reservation.product.prescription_required && (
                <div className="ticket__reminder">
                  <PrescriptionIcon small />
                  {s.prescription}
                </div>
              )}
            </section>

            <div className="ticket-screen__actions">
              <a
                className="pill-button"
                href={directionsUrl(reservation.pharmacy.pin)}
                target="_blank"
                rel="noreferrer"
              >
                <MapIcon small />
                {s.directions}
              </a>
              <a className="pill-button pill-button--dark" href={`tel:${reservation.pharmacy.phone}`}>
                <PhoneIcon small />
                {s.call}
              </a>
            </div>
            {reservation.state === 'RESERVED' && (
              <button
                type="button"
                className="text-button text-button--danger-on-dark"
                style={{ alignSelf: 'center' }}
                onClick={() => setAsking(true)}
              >
                {s.cancel}
              </button>
            )}
          </>
        )}
      </main>

      <Modal opened={asking} onClose={() => setAsking(false)} title={s.cancelTitle} centered radius="xl">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <p className="sheet-text">{s.cancelBody}</p>
          {failed && (
            <Banner tone="red" alert>
              {errorMessage(failed)}
            </Banner>
          )}
          <button
            type="button"
            className="pill-button pill-button--danger"
            onClick={cancel}
            disabled={cancelling}
          >
            {s.cancelConfirm}
          </button>
          <button type="button" className="pill-button pill-button--grey" onClick={() => setAsking(false)}>
            {s.keep}
          </button>
        </div>
      </Modal>
    </div>
  )
}
