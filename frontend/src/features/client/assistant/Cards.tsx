import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { Schemas } from '../../../api/client'
import { AlertIcon, CheckIcon, PhoneIcon, PrescriptionIcon, TicketIcon } from '../../../components/icons'
import { calendarDate, clockInSentence, dateAndClock, lbp } from '../../../format'
import { strings } from '../../../strings/en'
import { Fit, PriceBlock } from '../search/parts'
import { travelWords } from '../search/words'

const s = strings.chat

type Card = Schemas['Card']
type CardBox = Schemas['CardBox']

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
  earlier = false,
  onAct,
}: {
  card: Card
  busy: boolean
  /** In an earlier chat, where nothing can be asked any more. */
  earlier?: boolean
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

      {card.box && (
        <div className="row-card__top">
          <span className="soft">{anotherBrand ? s.card.price : s.card.atTheCounter}</span>
          <PriceBlock price={card.box.price} saving={card.box.saving} />
        </div>
      )}

      <dl className="card__lines">
        {card.lines.map((line) => (
          <div className="card__line" key={`${line.label}:${line.value}`}>
            <dt>{line.label}</dt>
            <dd>{line.value}</dd>
          </div>
        ))}
        {card.box && <BoxLines box={card.box} boxes={Math.max(1, card.selectable_items.length)} />}
      </dl>
      {card.box && <BoxFit box={card.box} />}

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
      {card.state === 'expired' && <span className="card__note">{earlier ? s.expiredEarlier : s.expired}</span>}

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

/** The days a card's boxes are for: 1 is also what the assistant uses when the client
 * didn't say (R-F2), so it is treated as not said and the expiry date is shown instead. */
function daysSaid(box: CardBox): number | null {
  return box.days_of_use !== null && box.days_of_use > 1 ? box.days_of_use : null
}

/** The facts of a card's boxes that are lines: the day's hours, the expiry when the fit
 * line doesn't already say it, the trip in search's words (A#37). */
function BoxLines({ box, boxes }: { box: CardBox; boxes: number }) {
  // The fit line says the date itself when no days were said ("Expires …: make sure").
  const fitSaysTheDate = !(box.days_of_use === null && boxes > 1) && daysSaid(box) === null
  return (
    <>
      {box.hours_on_pickup_day && (
        <div className="card__line">
          <dt>{s.card.openThatDay}</dt>
          <dd>{box.hours_on_pickup_day}</dd>
        </div>
      )}
      {!fitSaysTheDate && (
        <div className="card__line">
          <dt>{boxes > 1 ? s.card.soonestExpiry : s.card.expires}</dt>
          <dd>{calendarDate(box.expiry_date)}</dd>
        </div>
      )}
      {box.travel && (
        <div className="card__line">
          <dt>{s.card.travel}</dt>
          <dd>{travelWords(box.travel)}</dd>
        </div>
      )}
    </>
  )
}

/** Whether the boxes last the client's days, as search says it. The assistant made the
 * card only for boxes that last (R-F1): what is left to say is how long, or the date. */
function BoxFit({ box }: { box: CardBox }) {
  if (box.days_of_use === null) {
    return (
      <span className="card__note" style={{ color: 'var(--green)', fontWeight: 500 }}>
        <CheckIcon small />
        {s.card.lastsEach}
      </span>
    )
  }
  return <Fit fits expiryDate={box.expiry_date} daysOfUse={daysSaid(box)} />
}

/** What the chat knows of the client's offers, for its "held for you" cards (B#15). */
export type OffersKnown = {
  /** The offers still waiting for the client's tap; null while that isn't known. */
  open: Set<string> | null
  /** The server's clock (the demo clock may be ahead of the device's). */
  now: string
  /** A request's page shows its offers itself, above the thread: no link away. */
  here: boolean
}

/**
 * A box a pharmacy holds for the client (B#15): which medicine, until when, and where to
 * accept it. Only while the offer still waits does it point there; afterwards it says
 * what happened in words true of every ending (accepted, declined, over).
 */
function HeldOfferCard({ data, offers }: { data: Card['data']; offers: OffersKnown | null }) {
  const t = s.system
  const { order_id: id, product, offer_expires_at: until } = data as {
    order_id?: string
    product?: string
    offer_expires_at?: string | null
  }
  const known = offers?.open ?? null
  const over =
    (known !== null && id !== undefined && !known.has(id)) ||
    (until != null && offers !== null && Date.parse(until) <= Date.parse(offers.now))
  let words: string = t.offer
  if (product && over) words = t.offerWas(product)
  else if (product && until) {
    words = t.offerHeld(product, offers ? clockInSentence(until, offers.now) : dateAndClock(until))
  }
  const link = !over && known !== null && id !== undefined && known.has(id) && !offers?.here
  return (
    <div className="system-card">
      <div className="system-card__text">
        <span className="system-card__title">{words}</span>
      </div>
      {link && (
        <Link to="/" className="pill-button">
          {t.seeOffer}
        </Link>
      )}
    </div>
  )
}

/** A template card about something that happened: reserved, picked up, not available.
 *
 * `waiting`: the reservations still to pick up, or null while that isn't known. A
 * "Reserved" card stays in the chat after its reservation ended; only one still waiting
 * gets the big [Show at the counter], the others a plain link to their ticket (A#36). */
export function SystemCard({
  card,
  waiting = null,
  offers = null,
}: {
  card: Card
  waiting?: Set<string> | null
  offers?: OffersKnown | null
}) {
  const data = card.data as { order_id?: string; order_ref?: string; request_ref?: string }
  const ref = data.order_ref ?? data.request_ref ?? ''
  const t = s.system
  if (card.type === 'offer') return <HeldOfferCard data={card.data} offers={offers} />
  const words: Record<string, string> = {
    reserved: t.reserved(ref),
    picked_up: t.picked_up(ref),
    not_available: t.not_available(ref),
    cancelled: t.cancelled(ref),
    cancelled_by_system: t.cancelled_by_system(ref),
    expired: t.expired(ref),
    request_reopened: t.request_reopened(ref),
    request_closed: t.request_closed(ref),
    team_closed: t.team_closed,
    assistant_back: t.assistant_back,
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
      {card.type === 'reserved' &&
        data.order_id &&
        (waiting?.has(data.order_id) ? (
          <Link to={`/reservations/${data.order_id}`} className="pill-button">
            <TicketIcon small />
            {strings.home.showAtCounter}
          </Link>
        ) : (
          <Link to={`/reservations/${data.order_id}`} className="text-button">
            {t.seeReservation}
          </Link>
        ))}
    </div>
  )
}

/** The cards under one message: the recommended one in full, the others folded under
 * "See N other options", so the screen stays short on a phone (docs/11 §6, rule 3). */
export function MessageCards({
  cards,
  busy,
  earlier = false,
  waiting = null,
  offers = null,
  onAct,
}: {
  cards: Card[]
  busy: boolean
  earlier?: boolean
  waiting?: Set<string> | null
  offers?: OffersKnown | null
  onAct: (card: Card, selectedItemKeys: string[] | null) => void
}) {
  const [showOthers, setShowOthers] = useState(false)
  const recommended = cards.filter((card) => card.origin === 'proposal' && card.recommended)
  const fold = recommended.length > 0
  const first = fold ? recommended : cards
  const others = fold ? cards.filter((card) => !recommended.includes(card)) : []
  const draw = (card: Card) =>
    card.origin === 'system' ? (
      <SystemCard key={card.card_id} card={card} waiting={waiting} offers={offers} />
    ) : (
      <ProposalCard key={card.card_id} card={card} busy={busy} earlier={earlier} onAct={onAct} />
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
