import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'

import { api, ApiFailure, unwrap } from '../../../api/client'
import { Banner } from '../../../components/layout'
import { dayClockInSentence } from '../../../format'
import { strings } from '../../../strings/en'
import { type Failure, failureMessage } from '../../../strings/failure'
import { placeBody, useSearchChoices } from './choices'

const s = strings.search.notify

/** The sheet's own words for a refusal: it speaks of "notify me", never of "watching". */
function refusalWords(failure: Failure, now: string): { tone: 'green' | 'red' | 'amber'; text: string } {
  const { code } = failure
  // Already asked: that is what the client wanted.
  if (code === 'WATCH_EXISTS') return { tone: 'green', text: s.already }
  if (code === 'LIMIT_WATCHES') return { tone: 'amber', text: s.tooMany }
  // Outside request hours, when they open again, by the server's clock (B#37).
  return { tone: code === 'OUTSIDE_REQUEST_HOURS' ? 'amber' : 'red', text: failureMessage(failure, { now }) }
}

/**
 * [Notify me] on a search that found nothing (docs/03 CS-6): DawaLink watches for the
 * medicine for the next 6 hours and offers the first box that appears. A price limit
 * is optional. The place is the search's own, sent in the body and kept nowhere here.
 *
 * `now`: the server's clock, from the search the page made.
 */
export function NotifyMe({ productId, now }: { productId: string; now: string }) {
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
      // "until tomorrow 01:30" from the server's clock when it answered: never the
      // device's, which the demo clock may be ahead of (B#39).
      setSaid({ tone: 'green', text: s.watching(dayClockInSentence(made.ends_at, made.server_now)) })
      setOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['watches'] })
    } catch (error) {
      setSaid(
        refusalWords(
          error instanceof ApiFailure ? { code: error.code, details: error.details } : { code: 'INTERNAL_ERROR' },
          now,
        ),
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
