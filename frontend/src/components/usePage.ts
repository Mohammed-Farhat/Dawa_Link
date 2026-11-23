import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

// Numbered pages for a long list (the owner, 2026-11-23: "Show more keeps scrolling
// down"). The page lives in the address as `?page=2`, next to the list's own choices,
// so that a reload, a shared address and "Back to the list" all find the same page.
// Page 1 is the address without `page`: no list ever writes `?page=1`.

/** How many rows a page shows, on every list of the website. The API gives 50 at most
 * (docs/04 N-31). */
export const PAGE_ROWS = 25

/** The most rows a list may skip (`MAX_SKIP` in backend/src/dawalink/api/schemas/common.py):
 * a page past it would be refused by the API on every visit. */
const MOST_ROWS_SKIPPED = 1_000_000
export const PAGE_MAX = Math.floor(MOST_ROWS_SKIPPED / PAGE_ROWS) + 1

const KEY = 'page'

/** How many pages `total` rows take: at least one, an empty list included. */
export function pageCount(total: number): number {
  return Math.max(1, Math.ceil(total / PAGE_ROWS))
}

/** The rows a page skips: what the API is sent as `cursor` (or `offset`). The one place
 * it is computed. */
export function offsetOf(page: number): number {
  return (page - 1) * PAGE_ROWS
}

/** A page number as the address holds it, or 1. "abc", "0", "-3", "2.5", "1e9" are 1;
 * a number past the API's reach is the last page it can reach. */
export function readPage(value: string | null): number {
  if (!value || !/^[0-9]{1,9}$/.test(value)) return 1
  const page = Number(value)
  if (page < 1) return 1
  return Math.min(page, PAGE_MAX)
}

/** A page number, or a gap standing for the pages between two numbers. */
export type PagerItem = number | 'gap'

/**
 * The numbers the pager shows: the first and the last page, the page shown and its two
 * neighbours. A gap never stands for a single page: that page is shown instead, so
 * "1 … 3" is "1 2 3". Seven pages or fewer are all shown.
 */
export function pagerItems(page: number, pages: number): PagerItem[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, at) => at + 1)
  const shown = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages))
  const numbers = [...shown].sort((a, b) => a - b)
  const items: PagerItem[] = []
  for (const n of numbers) {
    const before = items[items.length - 1]
    if (typeof before === 'number' && n - before === 2) items.push(before + 1)
    else if (typeof before === 'number' && n - before > 2) items.push('gap')
    items.push(n)
  }
  return items
}

export type Paging = {
  /** The page shown, from 1. */
  page: number
  /** What the API is sent to get this page: `offsetOf(page)`. */
  offset: number
  /** Goes to a page, as a new step of the history: Back returns to the page before. The
   * page already shown changes nothing. */
  setPage: (page: number) => void
  /** Back to page 1 without a new step of the history: for a choice kept in memory
   * instead of the address (a box typed in), called where it changes. */
  firstPage: () => void
  /** Sets one of the list's choices (a tab, a filter, a typed text; `null` removes it)
   * and goes back to page 1 in the same change of the address. */
  choose: (key: string, value: string | null) => void
  /** Moves to the last page when the address asks for a page past it (an old link, a
   * list that shrank). It replaces the address: Back never returns to the empty page. */
  keepInRange: (total: number) => void
  /** The address's choices, to read the list's own ones from. */
  params: URLSearchParams
}

/**
 * The page of a list, kept in the address.
 *
 * A choice the page keeps in memory instead of the address (a box typed in) goes back
 * to page 1 by calling `firstPage()` where it changes. Write to the address once per
 * event: two writes in one handler may lose the first.
 */
export function usePage(): Paging {
  const [params, setParams] = useSearchParams()
  const page = readPage(params.get(KEY))

  const write = useCallback(
    (wanted: number, replace: boolean) =>
      setParams(
        (before) => {
          const next = new URLSearchParams(before)
          const chosen = Math.min(Math.max(1, Math.floor(wanted) || 1), PAGE_MAX)
          if (chosen === 1) next.delete(KEY)
          else next.set(KEY, String(chosen))
          return next
        },
        { replace },
      ),
    [setParams],
  )

  // The address as it would be written for a page: no `page` at all for page 1.
  const written = params.get(KEY)
  const isWritten = useCallback(
    (wanted: number) => written === (wanted === 1 ? null : String(wanted)),
    [written],
  )

  // A page already shown, as the address already writes it, is not a new step of the
  // history: Back must still leave the list in one press.
  const setPage = useCallback(
    (wanted: number) => {
      const chosen = Math.min(Math.max(1, Math.floor(wanted) || 1), PAGE_MAX)
      if (!isWritten(chosen)) write(chosen, false)
    },
    [isWritten, write],
  )

  const firstPage = useCallback(() => {
    if (!isWritten(1)) write(1, true)
  }, [isWritten, write])

  const choose = useCallback(
    (key: string, value: string | null) =>
      // Typing replaces the address instead of adding to the history, as the admin's
      // lists always did: Back still leaves the list in one press.
      setParams(
        (before) => {
          const next = new URLSearchParams(before)
          if (value) next.set(key, value)
          else next.delete(key)
          next.delete(KEY)
          return next
        },
        { replace: true },
      ),
    [setParams],
  )

  const keepInRange = useCallback(
    (total: number) => {
      const last = pageCount(total)
      if (page > last) write(last, true)
    },
    [page, write],
  )

  return { page, offset: offsetOf(page), setPage, firstPage, choose, keepInRange, params }
}
