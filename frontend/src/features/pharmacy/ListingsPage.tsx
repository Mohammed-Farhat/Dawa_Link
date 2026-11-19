import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { calendarDate, lbp } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { usePublicConfig } from '../client/data'
import { Link } from 'react-router-dom'

import { usePharmacy, useStock } from './data'

const s = strings.pharmacy.listing
const stockWords = strings.pharmacy.stock

type Item = Schemas['StockItem']

/**
 * PS-7: the boxes clients can find, and the ones that could be. A listing isn't a
 * separate thing: it is a box of the stock within six months of its expiry, that the
 * pharmacy's own rule lists, or that the pharmacy listed by hand (BLD-D44). Here the
 * pharmacy sets its own price for one, pauses it, or lists one its rule still holds back.
 */
export function ListingsPage() {
  const listed = useStock('NEAR_EXPIRY', '')
  const config = usePublicConfig()
  const pharmacy = usePharmacy()
  const rule = pharmacy.data?.auto_list_days
  const items = listed.items
  return (
    <div className="portal__columns">
      <main className="portal__main">
        <div>
          <h1 className="page-title">{s.title}</h1>
          <span className="soft">{s.intro}</span>
          {rule !== undefined && (
            <p className="soft" style={{ margin: '8px 0 0' }}>
              {s.rule(rule)}{' '}
              <Link to="/pharmacy/settings" className="text-button" style={{ padding: 0 }}>
                {s.changeRule}
              </Link>
            </p>
          )}
        </div>
        {listed.loaded && items.length === 0 && <div className="empty">{s.none}</div>}
        {items.map((item) => (
          <Listing key={item.id} item={item} rule={rule ?? 0} />
        ))}
        {listed.hasMore && (
          <button type="button" className="text-button" onClick={listed.more}>
            {stockWords.more}
          </button>
        )}
      </main>
      <aside className="portal__aside">
        <section className="panel" aria-labelledby="tiers">
          <h2 id="tiers" className="panel__title">
            {s.tiers}
          </h2>
          <ul className="plain-list">
            {(config.data?.discount_tiers ?? []).map((tier) => (
              <li key={tier.min_days} className="soft" style={{ fontSize: 15 }}>
                {s.tier(tier.min_days, tier.max_days, tier.discount_pct)}
              </li>
            ))}
          </ul>
        </section>
      </aside>
    </div>
  )
}

function Listing({ item, rule }: { item: Item; rule: number }) {
  const queryClient = useQueryClient()
  const [pricing, setPricing] = useState(false)
  const [typed, setTyped] = useState('')
  const [failed, setFailed] = useState<string | null>(null)
  const price = item.price

  async function change(body: Schemas['StockItemChange']) {
    setFailed(null)
    try {
      await unwrap(
        api.PATCH('/api/v1/pharmacy/inventory/items/{item_id}', {
          params: { path: { item_id: item.id } },
          body,
        }),
      )
      setPricing(false)
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
    } catch (error) {
      setFailed(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
    }
  }

  function savePrice(event: FormEvent) {
    event.preventDefault()
    if (/^\d+$/.test(typed)) void change({ price_override_lbp: Number(typed) })
  }

  const state = item.paused
    ? s.paused
    : item.held_back
      ? s.heldBack
      : item.qty_available === 0
        ? s.outOfStock
        : item.listed_by_hand
          ? s.listedByYou
          : s.visible
  return (
    <article className="row-card" aria-label={`${item.product.name} · ${item.batch}`}>
      <div className="row-card__top">
        <h2 className="card__title" style={{ margin: 0 }}>
          {item.product.name}
          {item.product.strength && <span className="hint"> · {item.product.strength}</span>}
        </h2>
        <span className={`status-pill status-pill--${item.visible ? 'green' : 'amber'}`}>{state}</span>
      </div>
      <span className="soft" style={{ fontSize: 15 }}>
        {s.line(item.batch, calendarDate(item.expiry_date), stockWords.daysLeft(item.days_left))}
      </span>
      <span className="soft" style={{ fontSize: 15 }}>
        {s.available(item.qty_available, item.qty_reserved)}
      </span>
      {item.held_back && <span className="hint">{s.waitsFor(rule)}</span>}
      {price.effective && (
        <span style={{ fontSize: 17, fontWeight: 600 }}>
          {s.price(lbp(price.effective.lbp), price.discount_pct ?? 0)}
          <span className="hint" style={{ fontWeight: 400 }}>
            {' '}
            · {price.override ? s.ownPrice : s.systemPrice} ·{' '}
            {s.publicPrice(lbp(item.product.public_price.lbp))}
          </span>
        </span>
      )}
      {failed && (
        <Banner tone="red" alert>
          {errorMessage(failed)}
        </Banner>
      )}
      {pricing ? (
        <form onSubmit={savePrice} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
          <input
            className="quantity-input quantity-input--wide"
            type="text"
            inputMode="numeric"
            aria-label={s.priceOf(item.product.name)}
            value={typed}
            onChange={(event) => setTyped(event.currentTarget.value.replace(/\D/g, ''))}
          />
          <button type="submit" className="pill-button" disabled={!typed}>
            {s.savePrice}
          </button>
          <button type="button" className="text-button" onClick={() => setPricing(false)}>
            {s.cancel}
          </button>
          <span className="hint" style={{ flexBasis: '100%' }}>
            {s.priceHint}
          </span>
        </form>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          <button
            type="button"
            className="text-button"
            style={{ paddingInlineStart: 0 }}
            onClick={() => {
              setTyped(price.override ? String(price.override.lbp) : '')
              setPricing(true)
            }}
          >
            {s.setPrice}
          </button>
          {price.override && (
            <button type="button" className="text-button" onClick={() => void change({ price_override_lbp: null })}>
              {s.backToSystem}
            </button>
          )}
          {/* One way out of each state: a box the rule holds back is listed by hand; a
              box listed by hand goes back to the rule; any other is paused or resumed. */}
          {item.held_back ? (
            <button type="button" className="text-button" onClick={() => void change({ listed: true })}>
              {s.listNow}
            </button>
          ) : item.listed_by_hand ? (
            <button type="button" className="text-button" onClick={() => void change({ listed: false })}>
              {s.backToRule}
            </button>
          ) : (
            <button type="button" className="text-button" onClick={() => void change({ paused: !item.paused })}>
              {item.paused ? s.resume : s.pause}
            </button>
          )}
        </div>
      )}
    </article>
  )
}
