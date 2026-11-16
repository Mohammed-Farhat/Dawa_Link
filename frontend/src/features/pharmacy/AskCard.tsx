import { Modal, NativeSelect, NumberInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { calendarDate, plainAmount } from '../../format'
import { errorMessage, strings } from '../../strings/en'

const a = strings.pharmacy.ask

type Ask = Schemas['EarlyReleaseAsk']

function timeLeft(until: string, now: string): string {
  const minutes = Math.max(0, Math.round((Date.parse(until) - Date.parse(now)) / 60_000))
  return a.timeLeft(Math.floor(minutes / 60), minutes % 60)
}

/**
 * PS-9: "A client needs this today, and you hold it without listing it. Release it?"
 *
 * The pharmacist chooses how many packs and the price (never above the public price),
 * or declines with a reason **from a list**: nothing they type goes anywhere near the
 * AI (R-AG8). The need is described without anything about the client.
 */
export function AskCard({ ask, now }: { ask: Ask; now: string }) {
  const queryClient = useQueryClient()
  const most = Math.min(ask.qty_needed, ask.private_item.qty_available, 3)
  const [qty, setQty] = useState(String(Math.max(1, most)))
  const [price, setPrice] = useState<number>(ask.suggested_price.lbp)
  const [declining, setDeclining] = useState(false)
  const [reason, setReason] = useState('keeping_it')
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState<{ tone: 'green' | 'red'; text: string } | null>(null)

  async function answer(accept: boolean) {
    setSending(true)
    setNotice(null)
    try {
      if (accept) {
        const done = await unwrap(
          api.POST('/api/v1/pharmacy/early-release-asks/{ask_id}/accept', {
            params: { path: { ask_id: ask.id } },
            body: { qty: Number(qty), price_lbp: price },
          }),
        )
        setNotice({ tone: 'green', text: done.message })
      } else {
        await unwrap(
          api.POST('/api/v1/pharmacy/early-release-asks/{ask_id}/decline', {
            params: { path: { ask_id: ask.id } },
            body: { reason: reason as Schemas['DeclineAsk']['reason'] },
          }),
        )
        setDeclining(false)
      }
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
    } catch (error) {
      const code = error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
      setNotice({ tone: 'red', text: errorMessage(code) })
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="ask-card" aria-label={a.title(ask.qty_needed, ask.product.name)}>
      <span className="ask-card__label">{a.needed(timeLeft(ask.respond_by, now))}</span>
      <h2 className="ask-card__title">{a.title(ask.qty_needed, ask.product.name)}</h2>
      <span className="soft" style={{ fontSize: 15 }}>
        {a.youHold(
          ask.private_item.qty_available,
          ask.private_item.batch,
          calendarDate(ask.private_item.expiry_date),
        )}
      </span>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
        <NativeSelect
          label={a.release}
          size="md"
          value={qty}
          onChange={(event) => setQty(event.currentTarget.value)}
          data={Array.from({ length: Math.max(1, most) }, (_, index) => ({
            value: String(index + 1),
            label: a.packs(index + 1),
          }))}
        />
        <NumberInput
          label={a.price}
          size="md"
          min={0}
          max={ask.product.public_price.lbp}
          allowDecimal={false}
          thousandSeparator=","
          value={price}
          onChange={(value) => setPrice(typeof value === 'number' ? value : 0)}
        />
      </div>
      <span className="soft" style={{ fontSize: 14 }}>
        {a.suggested(plainAmount(ask.suggested_price.lbp), plainAmount(ask.product.public_price.lbp))}
      </span>
      {notice && (
        <Banner tone={notice.tone} alert={notice.tone === 'red'}>
          {notice.text}
        </Banner>
      )}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button type="button" className="pill-button" disabled={sending} onClick={() => void answer(true)}>
          {a.accept}
        </button>
        <button type="button" className="pill-button pill-button--outline" disabled={sending} onClick={() => setDeclining(true)}>
          {a.decline}
        </button>
      </div>

      <Modal opened={declining} onClose={() => setDeclining(false)} title={a.declineTitle} centered radius="xl">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <p className="sheet-text">{a.declineBody}</p>
          <NativeSelect
            aria-label={a.declineTitle}
            size="md"
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
            data={Object.entries(a.reasons).map(([value, label]) => ({ value, label }))}
          />
          <button type="button" className="pill-button pill-button--danger" disabled={sending} onClick={() => void answer(false)}>
            {a.confirmDecline}
          </button>
        </div>
      </Modal>
    </section>
  )
}
