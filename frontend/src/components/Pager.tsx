import { type RefObject, useEffect } from 'react'

import { strings } from '../strings/en'
import { mainArea } from './arrival'
import { PAGE_ROWS, pageCount, pagerItems, type Paging } from './usePage'

const s = strings.pager

/**
 * The pager under a long list: [Previous] 1 2 … 7 [Next], and "Page 2 of 7 · 134 in
 * all". It shows nothing while the total is not known, or when every row fits on one
 * page; render it under the list all the same, because it also moves an address that
 * asks for a page past the last one back to the last (`settled` answers only).
 *
 * - `total`: the rows the list's choices match, the API's `total`.
 * - `settled`: the answer is the one for this page and these choices, not the one kept
 *   on the screen while it comes (TanStack's `!isPlaceholderData`).
 * - `label`: the name of its menu, when a page has two lists.
 * - `top`: where the view goes after a page change; the page's main area by default.
 */
export function Pager({
  paging,
  total,
  settled,
  label = s.label,
  top,
}: {
  paging: Paging
  total: number | undefined
  settled: boolean
  label?: string
  top?: RefObject<HTMLElement | null>
}) {
  const { page, setPage, keepInRange } = paging
  useEffect(() => {
    if (settled && total !== undefined) keepInRange(total)
  }, [settled, total, keepInRange])

  if (total === undefined || total <= PAGE_ROWS) return null
  const pages = pageCount(total)
  const shown = Math.min(page, pages)

  function go(wanted: number) {
    if (wanted < 1 || wanted > pages || wanted === shown) return
    setPage(wanted)
    // The new rows start at the top of the list, as on a website that loads a new page.
    // The focus stays on the button pressed, so the keyboard can press it again.
    const start = top?.current ?? mainArea()
    start?.scrollIntoView?.({ block: 'start' })
  }

  return (
    <nav className="pager" aria-label={label}>
      <ul className="pager__row">
        <li>
          <button
            type="button"
            className="pager__button"
            aria-disabled={shown === 1 || undefined}
            onClick={() => go(shown - 1)}
          >
            {s.previous}
          </button>
        </li>
        {pagerItems(shown, pages).map((item, at) =>
          item === 'gap' ? (
            // Two gaps can't be told apart by their number: by their place.
            <li key={`gap-${at}`} className="pager__number pager__gap" aria-hidden="true">
              {s.gap}
            </li>
          ) : (
            <li key={item} className="pager__number">
              <button
                type="button"
                className="pager__button"
                aria-label={s.page(item)}
                aria-current={item === shown ? 'page' : undefined}
                onClick={() => go(item)}
              >
                {item}
              </button>
            </li>
          ),
        )}
        <li>
          <button
            type="button"
            className="pager__button"
            aria-disabled={shown === pages || undefined}
            onClick={() => go(shown + 1)}
          >
            {s.next}
          </button>
        </li>
      </ul>
      <p className="pager__summary" aria-live="polite">
        {s.summary(shown, pages, total)}
      </p>
    </nav>
  )
}
