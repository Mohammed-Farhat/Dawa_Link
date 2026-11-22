import type { Schemas } from '../../../api/client'
import { AlertIcon, CheckIcon, PrescriptionIcon } from '../../../components/icons'
import { aboutUsd, calendarDate, lbp, plainAmount } from '../../../format'
import { strings } from '../../../strings/en'

// The same facts, in the same order, wherever an offer is shown (docs/11 §4):
// how far, opening hours, whether the box lasts, the prescription, the price and what
// is saved.

type Listing = Schemas['Listing']

/** The price, about how much in dollars, and the saving in yellow (docs/11 §4). */
export function PriceBlock({
  price,
  saving,
  big,
}: {
  price: Schemas['Money']
  saving: Schemas['Money']
  big?: boolean
}) {
  return (
    <div className="price-block">
      <span style={{ fontSize: big ? 22 : 17, fontWeight: 600 }}>{lbp(price.lbp)}</span>
      {aboutUsd(price) && <span className="hint">{aboutUsd(price)}</span>}
      {saving.lbp > 0 && (
        <span className="saving" style={{ alignSelf: 'flex-end' }}>
          {strings.common.save_(plainAmount(saving.lbp))}
        </span>
      )}
    </div>
  )
}

/** Whether the box lasts the client's days. Never a color alone: an icon and words. */
export function FitBadge({ listing, daysOfUse }: { listing: Listing; daysOfUse: number | null }) {
  return <Fit fits={listing.fits} expiryDate={listing.expiry_date} daysOfUse={daysOfUse} />
}

/**
 * The same line for any box: a search's, an assistant's card's, an offer's (B#5).
 * `fits` null, or no days said: the expiry date, to check. False: it doesn't last.
 */
export function Fit({
  fits,
  expiryDate,
  daysOfUse,
}: {
  fits: boolean | null
  expiryDate: string
  daysOfUse: number | null
}) {
  const o = strings.offer
  const expiry = calendarDate(expiryDate)
  if (daysOfUse === null || fits === null) {
    return (
      <span className="card__note card__note--amber">
        <AlertIcon small />
        {o.makeSure(expiry)}
      </span>
    )
  }
  if (!fits) {
    return (
      <span className="card__note" style={{ color: 'var(--red)', fontWeight: 500 }}>
        <AlertIcon small />
        {o.doesntLast(daysOfUse, expiry)}
      </span>
    )
  }
  return (
    <span className="card__note" style={{ color: 'var(--green)', fontWeight: 500 }}>
      <CheckIcon small />
      {o.lastsYour(daysOfUse)}
    </span>
  )
}

export function PrescriptionLine() {
  return (
    <span className="card__note">
      <PrescriptionIcon small />
      {strings.chat.prescription}
    </span>
  )
}
