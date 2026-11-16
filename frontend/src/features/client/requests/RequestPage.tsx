import { Modal } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../../api/client'
import { Banner } from '../../../components/layout'
import { dayAndClock } from '../../../format'
import { errorMessage, strings } from '../../../strings/en'
import { Conversation } from '../assistant/AssistantPage'
import { useOffers } from '../data'
import { OfferCard } from './OfferCard'

const r = strings.request

type Request = Schemas['SourcingRequest']
type Item = Schemas['RequestItem']

function timeLeft(until: string, now: string): string {
  const minutes = Math.max(0, Math.round((Date.parse(until) - Date.parse(now)) / 60_000))
  return r.timeLeft(Math.floor(minutes / 60), minutes % 60)
}

/** How far a medicine is: 1 searching, 2 found (a card or an offer waits), 3 reserved. */
function stepOf(item: Item): number {
  if (item.state === 'SECURED') return 3
  if (item.state === 'PROPOSED' || (item.waiting?.open_offer_ids.length ?? 0) > 0) return 2
  return 1
}

const TONE: Record<Item['state'], string> = {
  SEARCHING: 'blue',
  PROPOSED: 'amber',
  WAITING: 'blue',
  SECURED: 'green',
  UNAVAILABLE: 'red',
  CANCELLED: 'grey',
}

/**
 * CS-16: a sourcing request. Above, where each medicine stands and any offer waiting
 * for the client's tap; below, the thread: what the agent did and says, with its cards.
 *
 * The page reads the request again every few seconds: the agent works on it by itself
 * for up to six hours, and what it does must appear without a reload.
 */
export function RequestPage() {
  const { id = '' } = useParams()
  const found = useQuery({
    queryKey: ['request', id],
    queryFn: () =>
      unwrap(api.GET('/api/v1/requests/{request_id}', { params: { path: { request_id: id } } })),
    refetchInterval: 5000,
    retry: false,
  })

  if (found.isError) {
    return (
      <main className="screen screen--plain">
        <Banner tone="red" alert>
          {r.notFound}
        </Banner>
        <Link to="/" className="pill-button pill-button--grey">
          {strings.notFound.back}
        </Link>
      </main>
    )
  }
  if (!found.data) {
    return (
      <main className="screen screen--plain">
        <p className="soft">{strings.common.loading}</p>
      </main>
    )
  }
  const request = found.data
  if (!request.conversation_id) return <Tracker request={request} />
  return (
    <Conversation
      conversationId={request.conversation_id}
      thread={{
        title: r.title(request.ref),
        subtitle:
          request.state === 'OPEN'
            ? timeLeft(request.ends_at, request.server_now)
            : (r.closed[request.outcome ?? ''] ?? ''),
        backTo: '/',
        above: <Tracker request={request} />,
        canWrite: request.state === 'OPEN',
      }}
    />
  )
}

function Tracker({ request }: { request: Request }) {
  const queryClient = useQueryClient()
  const offers = useOffers()
  const [asking, setAsking] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const open = request.state === 'OPEN'
  const mine = (offers.data?.items ?? []).filter((offer) => offer.request_id === request.id)
  const now = request.server_now

  async function cancel() {
    setFailed(null)
    try {
      const cancelled = await unwrap(
        api.POST('/api/v1/requests/{request_id}/cancel', {
          params: { path: { request_id: request.id } },
        }),
      )
      queryClient.setQueryData(['request', request.id], cancelled)
      await queryClient.invalidateQueries({ queryKey: ['requests'] })
      setAsking(false)
    } catch (error) {
      setFailed(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
    }
  }

  return (
    <>
      <section className="row-card" aria-label={r.title(request.ref)}>
        <div className="row-card__top">
          <span style={{ fontSize: 20, fontWeight: 600 }}>
            {r.reserved(request.units_secured, request.units_wanted)}
          </span>
          <span className="order-ref hint">{request.ref}</span>
        </div>
        <span className="soft" style={{ fontSize: 15 }}>
          {open
            ? r.searchingUntil(dayAndClock(request.ends_at, now))
            : (r.closed[request.outcome ?? ''] ?? '')}
        </span>

        <ul className="plain-list" aria-label={r.medicines}>
          {request.items.map((item) => (
            <li key={item.id} className="tracker-item">
              <div className="row-card__top">
                <span style={{ fontWeight: 600 }}>
                  {item.product.name} × {item.qty}
                </span>
                <span className={`status-pill status-pill--${TONE[item.state]}`}>
                  {item.status_text}
                </span>
              </div>
              <ol className="tracker-steps" aria-label={r.steps[stepOf(item) - 1]}>
                {r.steps.map((step, index) => (
                  <li key={step} className="tracker-step" data-done={index < stepOf(item)}>
                    {step}
                  </li>
                ))}
              </ol>
              {open && item.waiting && item.waiting.asked_pharmacies > 0 && (
                <span className="hint">{r.asked(item.waiting.asked_pharmacies)}</span>
              )}
              {open && item.waiting && item.waiting.asked_pharmacies === 0 && (
                <span className="hint">{r.watching}</span>
              )}
              {item.reservations.map((held) => (
                <Link key={held.id} to={`/reservations/${held.id}`} className="text-button" style={{ alignSelf: 'flex-start', padding: 0 }}>
                  {r.showTicket(held.ref)} · {held.pharmacy_name}
                </Link>
              ))}
            </li>
          ))}
        </ul>

        {open && (
          <button type="button" className="text-button" style={{ alignSelf: 'flex-start', padding: 0, color: 'var(--red)' }} onClick={() => setAsking(true)}>
            {r.cancel}
          </button>
        )}
      </section>

      {mine.map((offer) => (
        <OfferCard key={offer.id} offer={offer} now={offers.data?.server_now ?? now} />
      ))}

      <span className="hint">{r.thread}</span>

      <Modal opened={asking} onClose={() => setAsking(false)} title={r.cancelTitle} centered radius="xl">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <p className="sheet-text">{r.cancelBody}</p>
          {failed && (
            <Banner tone="red" alert>
              {errorMessage(failed)}
            </Banner>
          )}
          <button type="button" className="pill-button pill-button--danger" onClick={() => void cancel()}>
            {r.cancelConfirm}
          </button>
          <button type="button" className="pill-button pill-button--grey" onClick={() => setAsking(false)}>
            {r.keep}
          </button>
        </div>
      </Modal>
    </>
  )
}
