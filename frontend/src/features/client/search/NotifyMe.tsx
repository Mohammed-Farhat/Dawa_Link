import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'

import { api, ApiFailure, unwrap } from '../../../api/client'
import { Banner } from '../../../components/layout'
import { clock } from '../../../format'
import { errorMessage, strings } from '../../../strings/en'
import { placeBody, useSearchChoices } from './choices'

const s = strings.search.notify

/**
 * [Notify me] on a search that found nothing (docs/03 CS-6): DawaLink watches for the
 * medicine for the next 6 hours and offers the first box that appears. A price limit
 * is optional. The place is the search's own, sent in the body and kept nowhere here.
 */
export function NotifyMe({ productId }: { productId: string }) {
  const choices = useSearchChoices()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [state, setState] = useState<'idle' | 'sending'>('idle')
  const [said, setSaid] = useState<{ tone: 'green' | 'red' | 'amber'; text: string } | null>(null)

  async function watch(event: FormEvent) {
    event.preventDefault()
    setSaid(null)
    setState('sending')
    try {
      const made = await unwrap(
        api.POST('/api/v1/watches', {
          body: {
            product_id: productId,
            qty: 1,
            days_of_use: choices.daysOfUse ?? 1,
            max_price: typed ? { amount: typed, currency: 'LBP' } : null,
            location: placeBody(choices.place),
          },
        }),
      )
      setSaid({ tone: 'green', text: s.watching(clock(made.ends_at)) })
      setOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['watches'] })
    } catch (error) {
      const code = error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
      // Already watching it: that is what the client wanted.
      setSaid(
        code === 'WATCH_EXISTS'
          ? { tone: 'green', text: s.already }
          : { tone: code === 'OUTSIDE_REQUEST_HOURS' ? 'amber' : 'red', text: errorMessage(code) },
      )
    } finally {
      setState('idle')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center', alignSelf: 'stretch' }}>
      <div role="status" aria-live="polite" style={{ alignSelf: 'stretch' }}>
        {said && <Banner tone={said.tone}>{said.text}</Banner>}
      </div>
      {!open && said?.tone !== 'green' && (
        <button type="button" className="pill-button pill-button--grey" onClick={() => setOpen(true)}>
          {s.button}
        </button>
      )}
      {open && (
        <form className="form" onSubmit={watch} style={{ alignSelf: 'stretch' }}>
          <span className="soft" style={{ fontSize: 15 }}>
            {s.what}
          </span>
          <label htmlFor="watch-max-price" style={{ fontSize: 15 }}>
            {s.maxPrice}
          </label>
          <input
            id="watch-max-price"
            className="quantity-input quantity-input--wide"
            type="text"
            inputMode="numeric"
            maxLength={11}
            value={typed}
            onChange={(event) => setTyped(event.currentTarget.value.replace(/\D/g, '').slice(0, 11))}
          />
          <button type="submit" className="pill-button" disabled={state === 'sending'}>
            {s.start}
          </button>
        </form>
      )}
    </div>
  )
}
