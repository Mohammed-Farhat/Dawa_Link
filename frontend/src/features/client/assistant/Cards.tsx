import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { Schemas } from '../../../api/client'
import { AlertIcon, CheckIcon, PhoneIcon, PrescriptionIcon, TicketIcon } from '../../../components/icons'
import { lbp } from '../../../format'
import { strings } from '../../../strings/en'

const s = strings.chat

type Card = Schemas['Card']

/**
 * A card made by one of the agent's tools (docs/11 §4).
 *
 * **Everything on it comes from the stored card**, written by code: the agent's own
 * words never fill a card's facts, prices or button (R-AG7). A tap sends only the
 * card's ID, and the server checks everything again.
 */
export function ProposalCard({
  card,
  busy,
  onAct,
}: {
  card: Card
  busy: boolean
  onAct: (card: Card, selectedItemKeys: string[] | null) => void
}) {
  const [ticked, setTicked] = useState<string[]>(card.selectable_items.map((item) => item.item_key))
  const open = card.state === 'open'
  const anotherBrand = card.type === 'other_brand'
  const tone = !open ? 'card--over' : card.recommended ? 'card--recommended' : ''

  function toggle(key: string) {
    setTicked((before) =>
      before.includes(key) ? before.filter((other) => other !== key) : [...before, key],
    )
  }

  return (
    <article className={`card ${tone}`} aria-label={card.title}>
      {card.recommended && open && <span className="status-pill status-pill--blue">{s.recommended}</span>}
      {anotherBrand && <span className="status-pill status-pill--amber">{s.anotherBrand}</span>}
      <h2 className="card__title">{card.title}</h2>

      {card.selectable_items.length > 0 && open ? (
        <ul className="card__checks">
          {card.selectable_items.map((item) => (
            <li key={item.item_key}>
              <label className="card__check">
                <input
                  type="checkbox"
                  checked={ticked.includes(item.item_key)}
                  onChange={() => toggle(item.item_key)}
                />
                <span>{item.label}</span>
                <span>{lbp(item.price.lbp)}</span>
              </label>
            </li>
          ))}
        </ul>
      ) : null}

      <dl className="card__lines">
        {card.lines.map((line) => (
          <div className="card__line" key={`${line.label}:${line.value}`}>
            <dt>{line.label}</dt>
            <dd>{line.value}</dd>
          </div>
        ))}
      </dl>

      {card.prescription_notice && (
        <span className="card__note">
          <PrescriptionIcon small />
          {s.prescription}
        </span>
      )}
      {anotherBrand && (
        <span className="card__note card__note--amber">
          <AlertIcon small />
          {s.askPharmacistFirst}
        </span>
      )}

      {/* Used or expired cards say so instead of vanishing (docs/11 §6, rule 8). */}
      {card.state === 'used' && (
        <span className="status-pill status-pill--green">
          <CheckIcon small />
          {card.type === 'reserve' || card.type === 'reserve_group' ? s.reserved : s.used}
        </span>
      )}
      {card.state === 'expired' && <span className="card__note">{s.expired}</span>}

      {open && anotherBrand && card.call_number && (
        <a className="pill-button" href={`tel:${card.call_number}`}>
          <PhoneIcon small />
          {s.call}
        </a>
      )}
      {open && card.action_label && (
        <button
          type="button"
          className="pill-button"
          disabled={busy || (card.selectable_items.length > 0 && ticked.length === 0)}
          onClick={() => onAct(card, card.selectable_items.length > 0 ? ticked : null)}
        >
          {card.action_label}
        </button>
      )}
    </article>
  )
}

/** A template card about something that happened: reserved, picked up, not available. */
export function SystemCard({ card }: { card: Card }) {
  const data = card.data as { order_id?: string; order_ref?: string; request_ref?: string }
  const ref = data.order_ref ?? data.request_ref ?? ''
  const t = s.system
  const words: Record<string, string> = {
    reserved: t.reserved(ref),
    picked_up: t.picked_up(ref),
    not_available: t.not_available(ref),
    cancelled: t.cancelled(ref),
    cancelled_by_system: t.cancelled_by_system(ref),
    expired: t.expired(ref),
    request_reopened: t.request_reopened(ref),
    request_closed: t.request_closed(ref),
    offer: t.offer,
    offer_ended: t.offer_ended,
  }
  const good = card.type === 'reserved' || card.type === 'picked_up'
  return (
    <div className="system-card">
      <div className="system-card__text">
        <span className="system-card__title">
          {good && (
            <span style={{ color: 'var(--green)', display: 'flex' }}>
              <CheckIcon small />
            </span>
          )}
          {words[card.type] ?? t.other}
        </span>
        {card.type === 'reserved' && <span className="soft">{t.reservedHint}</span>}
      </div>
      {card.type === 'reserved' && data.order_id && (
        <Link to={`/reservations/${data.order_id}`} className="pill-button">
          <TicketIcon small />
          {strings.home.showAtCounter}
        </Link>
      )}
    </div>
  )
}

/** The cards under one message: the recommended one in full, the others folded under
 * "See N other options", so the screen stays short on a phone (docs/11 §6, rule 3). */
export function MessageCards({
  cards,
  busy,
  onAct,
}: {
  cards: Card[]
  busy: boolean
  onAct: (card: Card, selectedItemKeys: string[] | null) => void
}) {
  const [showOthers, setShowOthers] = useState(false)
  const recommended = cards.filter((card) => card.origin === 'proposal' && card.recommended)
  const fold = recommended.length > 0
  const first = fold ? recommended : cards
  const others = fold ? cards.filter((card) => !recommended.includes(card)) : []
  const draw = (card: Card) =>
    card.origin === 'system' ? (
      <SystemCard key={card.card_id} card={card} />
    ) : (
      <ProposalCard key={card.card_id} card={card} busy={busy} onAct={onAct} />
    )
  return (
    <>
      {first.map(draw)}
      {others.length > 0 && (
        <button
          type="button"
          className="text-button"
          style={{ alignSelf: 'center' }}
          aria-expanded={showOthers}
          onClick={() => setShowOthers(!showOthers)}
        >
          {showOthers ? s.hideOptions : s.otherOptions(others.length)}
        </button>
      )}
      {showOthers && others.map(draw)}
    </>
  )
}
