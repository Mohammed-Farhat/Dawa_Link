import { Modal } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { CheckIcon, CloseIcon, MapIcon, PhoneIcon, PrescriptionIcon } from '../../components/icons'
import { Banner } from '../../components/layout'
import { reservationTone } from '../../components/reservationTone'
import { aboutUsd, calendarDate, dayAndClock, directionsUrl, lbp, reservationWords } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { useReservation } from './data'

const s = strings.ticket

type Reservation = Schemas['Reservation']

/** What the page's heading says: what to do with a live ticket, or what happened to one
 * that is no longer waiting, by its state, whatever words the server uses (A#36, B#13). */
function headingOf(reservation: Reservation | undefined): string {
  if (!reservation) return strings.shell.reservationTitle
  if (reservation.state === 'RESERVED') return s.header
  return s.ended[reservation.state] ?? strings.shell.reservationTitle
}

/** CS-10: the pickup ticket. The order number, huge, for the pharmacist to read.
 *
 * A reservation that is no longer waiting (cancelled, missed, not available, picked up)
 * opens on the same page, which says so first: no "Show this at the counter", no "Pay at
 * the counter", and Directions and Call as plain buttons (A#36). */
export function TicketPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { key: visit } = useLocation()
  const queryClient = useQueryClient()
  const found = useReservation(id)
  const [asking, setAsking] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [contested, setContested] = useState(false)

  /** [I picked it up]: the pharmacy forgot to press [Picked up] (docs/04 R-N3). */
  async function contest() {
    setFailed(null)
    try {
      const told = await unwrap(
        api.POST('/api/v1/reservations/{reservation_id}/contest', {
          params: { path: { reservation_id: id } },
        }),
      )
      queryClient.setQueryData(['reservation', id], told)
      setContested(true)
    } catch (error) {
      setFailed(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
    }
  }

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
  const live = reservation?.state === 'RESERVED'
  const ended = reservation !== undefined && !live
  return (
    <div className="ticket-screen">
      <main className="ticket-screen__inner">
        <header className="ticket-screen__top">
          <button
            type="button"
            className="round-button round-button--dark"
            aria-label={strings.common.close}
            // Opened straight from a link or an email, there is no page to go back to.
            onClick={() => (visit === 'default' ? navigate('/') : navigate(-1))}
          >
            <CloseIcon />
          </button>
          {/* Shown once the reservation is known: the focus goes to the heading on arrival,
              and "Cancelled" or "Missed pickup" must be the first thing heard. */}
          {found.isPending ? (
            <span />
          ) : (
            <h1 className={`ticket-screen__title${ended ? ' ticket-screen__title--ended' : ''}`}>
              {headingOf(reservation)}
            </h1>
          )}
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
            {ended && <Banner tone={reservationTone(reservation.state)}>{reservationWords(reservation)}</Banner>}
            <section className="ticket" aria-label={headingOf(reservation)}>
              <div className="ticket__head">
                {live && (
                  <span className="status-pill status-pill--green" style={{ alignSelf: 'center' }}>
                    <CheckIcon small />
                    {s.reserved}
                  </span>
                )}
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
                  <dt>{live ? s.pay : s.total}</dt>
                  <dd>{lbp(reservation.total.lbp)}</dd>
                  {aboutUsd(reservation.total) && (
                    <dd className="ticket__sub">{aboutUsd(reservation.total)}</dd>
                  )}
                </div>
                {/* A saving is the client's only if they come, or came, for the box. */}
                {(live || reservation.state === 'PICKED_UP') && reservation.saving.lbp > 0 && (
                  <div>
                    <dt>{s.youSave}</dt>
                    <dd>
                      <span className="saving saving--big">
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
                className={live ? 'pill-button' : 'pill-button pill-button--dark'}
                href={directionsUrl(reservation.pharmacy.pin)}
                target="_blank"
                rel="noreferrer"
              >
                <MapIcon small />
                {s.directions}{' '}
                {/* Heard, never seen: the map opens in another tab (WCAG 3.2.5). */}
                <span className="sr-only">{strings.common.opensNewTab}</span>
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
            {reservation.contestable && !contested && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }}>
                <span style={{ color: 'var(--ink-on-dark)', fontSize: 15, textAlign: 'center' }}>
                  {s.contestHint}
                </span>
                <button type="button" className="pill-button pill-button--white" onClick={() => void contest()}>
                  {s.contest}
                </button>
              </div>
            )}
            <div role="status" aria-live="polite">
              {contested && <Banner tone="green">{s.contested}</Banner>}
              {failed && !asking && <Banner tone="red">{errorMessage(failed)}</Banner>}
            </div>
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
