import { Checkbox, Modal, NativeSelect, NumberInput } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { calendarDate, lbp, plainAmount } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { type CardNotice, type OnNotice } from './notice'

const a = strings.pharmacy.ask

type Ask = Schemas['EarlyReleaseAsk']

function timeLeft(until: string, now: string): string {
  const minutes = Math.max(0, Math.round((Date.parse(until) - Date.parse(now)) / 60_000))
  return a.timeLeft(Math.floor(minutes / 60), minutes % 60)
}

/** The discount against the public price, as the rest of the portal rounds it. */
function percentOff(price: number, publicPrice: number): number {
  return publicPrice > 0 ? Math.round((1 - price / publicPrice) * 100) : 0
}

/**
 * PS-9: "A client needs this today, and you hold it without listing it. Release it?"
 *
 * The pharmacist chooses how many packs and the price (never above the public price),
 * or declines with a reason **from a list**: nothing they type goes anywhere near the
 * AI (R-AG8). The need is described without anything about the client.
 *
 * The client gets the offer the moment [Accept] is pressed, so the price is never
 * guessed for the pharmacist: an emptied box stays empty and [Accept] waits, a price
 * above the public one is said and never cut down in silence, and a free box (P-D7) is
 * offered only after the pharmacist ticks that it is free.
 */
export function AskCard({
  ask,
  now,
  notice,
  onNotice,
}: {
  ask: Ask
  now: string
  notice: CardNotice | null
  onNotice: OnNotice
}) {
  const queryClient = useQueryClient()
  const most = Math.min(ask.qty_needed, ask.private_item.qty_available, 3)
  const publicPrice = ask.product.public_price.lbp
  const [qty, setQty] = useState(String(Math.max(1, most)))
  const [price, setPrice] = useState<number | ''>(ask.suggested_price.lbp)
  const [free, setFree] = useState(false)
  const [declining, setDeclining] = useState(false)
  const [reason, setReason] = useState('keeping_it')
  const [sending, setSending] = useState(false)

  const amount = price === '' ? null : price
  const outOfRange = amount === null || amount > publicPrice
  const ready = amount !== null && amount <= publicPrice && (amount > 0 || free)

  async function answer(accept: boolean) {
    if (accept && !ready) return
    setSending(true)
    onNotice(null)
    try {
      if (accept) {
        const done = await unwrap(
          api.POST('/api/v1/pharmacy/early-release-asks/{ask_id}/accept', {
            params: { path: { ask_id: ask.id } },
            body: { qty: Number(qty), price_lbp: Number(amount) },
          }),
        )
        // "Thank you, this need was just met" too: the page keeps it after the card goes.
        onNotice({ key: ask.id, tone: 'green', text: done.message })
      } else {
        await unwrap(
          api.POST('/api/v1/pharmacy/early-release-asks/{ask_id}/decline', {
            params: { path: { ask_id: ask.id } },
            body: { reason: reason as Schemas['DeclineAsk']['reason'] },
          }),
        )
        setDeclining(false)
        onNotice({ key: ask.id, tone: 'green', text: a.declined })
      }
    } catch (error) {
      const code = error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
      onNotice({ key: ask.id, tone: 'red', text: errorMessage(code) })
    } finally {
      // Whatever happened, show the asks as the server has them now.
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
      setSending(false)
    }
  }

  const said = notice && (
    <Banner tone={notice.tone} alert={notice.tone === 'red'}>
      {notice.text}
    </Banner>
  )
  const packs = Number(qty)
  return (
    <section className="ask-card" aria-label={a.title(ask.qty_needed, ask.product.name)}>
      <span className="ask-card__label">{a.needed(timeLeft(ask.respond_by, now))}</span>
      {/* Under the heading "Asks from DawaLink" of Today. */}
      <h3 className="ask-card__title">{a.title(ask.qty_needed, ask.product.name)}</h3>
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
          max={publicPrice}
          clampBehavior="none"
          allowDecimal={false}
          allowNegative={false}
          allowLeadingZeros={false}
          thousandSeparator=","
          value={price}
          onChange={(value) => {
            setPrice(typeof value === 'number' ? value : '')
            setFree(false)
          }}
          error={outOfRange ? a.range(plainAmount(publicPrice)) : null}
        />
      </div>
      <span className="soft" style={{ fontSize: 14 }}>
        {a.suggested(
          plainAmount(ask.suggested_price.lbp),
          // The discount DawaLink would give this box today, or the pharmacy's own price.
          percentOff(ask.suggested_price.lbp, publicPrice),
          plainAmount(publicPrice),
        )}
      </span>
      {amount === 0 && (
        <Checkbox
          label={a.free}
          size="md"
          checked={free}
          onChange={(event) => setFree(event.currentTarget.checked)}
        />
      )}
      {ready && amount !== null && (
        <span style={{ fontSize: 15, fontWeight: 600 }}>
          {amount === 0
            ? a.offerFree(packs)
            : a.offer(packs, lbp(amount), percentOff(amount, publicPrice))}
        </span>
      )}
      {!declining && said}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="pill-button"
          disabled={sending || !ready}
          onClick={() => void answer(true)}
        >
          {a.accept}
        </button>
        <button
          type="button"
          className="pill-button pill-button--outline"
          disabled={sending}
          onClick={() => {
            onNotice(null)
            setDeclining(true)
          }}
        >
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
          {/* A refusal is said here, in the open dialog, not behind it. */}
          {declining && said}
          <button type="button" className="pill-button pill-button--danger" disabled={sending} onClick={() => void answer(false)}>
            {a.confirmDecline}
          </button>
          <button type="button" className="pill-button pill-button--grey" onClick={() => setDeclining(false)}>
            {strings.common.cancel}
          </button>
        </div>
      </Modal>
    </section>
  )
}
