// What a card says after the pharmacist answered on it: "Thank you, the client has two
// hours", or why the server refused. The page keeps it, not the card: a reservation that
// was handed over, or an ask that was answered, leaves its list at the next refresh, and
// its words must not leave with it.

export type CardNotice = {
  /** The reservation's or the ask's id: the card shows the notice while it is there. */
  key: string
  tone: 'green' | 'red'
  text: string
}

export type OnNotice = (notice: CardNotice | null) => void

/** The notice for this card, if the last one is about it. */
export function noticeFor(notice: CardNotice | null, key: string): CardNotice | null {
  return notice?.key === key ? notice : null
}
