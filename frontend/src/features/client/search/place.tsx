import { type ReactNode, useMemo, useState } from 'react'

import { ChoicesContext, type SearchChoices } from './choices'

/** Keeps the search choices while the client moves between the search page, an offer's
 * page and the reserve sheet. In memory only: closing the tab forgets them. */
export function SearchChoicesProvider({ children }: { children: ReactNode }) {
  const [choices, setChoices] = useState<SearchChoices>({
    place: { kind: 'profile' },
    daysOfUse: null,
    pickupDay: null,
    sort: 'best',
    maxPriceLbp: null,
  })
  const store = useMemo(
    () => ({
      ...choices,
      set: (change: Partial<SearchChoices>) => setChoices((now) => ({ ...now, ...change })),
    }),
    [choices],
  )
  return <ChoicesContext.Provider value={store}>{children}</ChoicesContext.Provider>
}
