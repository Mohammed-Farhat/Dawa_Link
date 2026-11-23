import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

import { strings } from '../strings/en'

// What a person hears and sees when a new page comes (B#19, WCAG 2.4.2 and 2.4.3): the
// browser's tab says which page it is, and the focus moves to the page's own heading,
// so a screen reader reads it and the keyboard goes on from there.

/** "Search · DawaLink"; "DawaLink" alone for a page that has no heading yet. */
export function pageTitle(heading: string | null | undefined): string {
  const name = heading?.replace(/\s+/g, ' ').trim()
  return name ? `${name} · ${strings.appName}` : strings.appName
}

/** The main heading of the page shown now: the first h1 of its main area. */
export function mainHeading(): HTMLElement | null {
  return document.querySelector<HTMLElement>('main h1, [role="main"] h1')
}

/** The page's main area: where "Skip to content" goes. */
export function mainArea(): HTMLElement | null {
  return document.querySelector<HTMLElement>('main, [role="main"]')
}

/**
 * Keeps the browser's title on the page's main heading. A page names itself once, with
 * its h1, so no page can forget its title; the heading may arrive after its data does,
 * or be replaced (a medicine's page), so the page is watched while it is shown. Only
 * elements coming and going are watched, not every letter typed in a box: that is what
 * changes a heading, at a fraction of the cost.
 *
 * `fallback`: the page's name while it shows no heading (Search while typing). The one
 * writer of the title: a page doesn't set it itself.
 *
 * It also gives the page's main area the id "main", which "Skip to content" points at,
 * when the page didn't give it one itself.
 */
export function useNamedPage(fallback: string | null = null): void {
  const named = useRef(fallback)
  useEffect(() => {
    named.current = fallback
    nameThePage(fallback)
  }, [fallback])
  useEffect(() => {
    const watch = new MutationObserver(() => nameThePage(named.current))
    watch.observe(document.body, { childList: true, subtree: true })
    return () => watch.disconnect()
  }, [])
}

function nameThePage(fallback: string | null): void {
  const title = pageTitle(mainHeading()?.textContent?.trim() || fallback)
  if (document.title !== title) document.title = title
  const main = mainArea()
  if (main && !main.id && !document.getElementById('main')) main.id = 'main'
}

const never = () => false

/** How long a page may take to show its heading after a move (its data on a slow phone). */
const HEADING_WAIT_MS = 5000

/**
 * After a move to another page, the focus goes to that page's heading. Not on the first
 * page of a visit (the browser starts at its top), not for a change of the query string
 * alone, and not when the page put the focus somewhere of its own (Search's box).
 *
 * `skip`: addresses whose own frame moves the focus itself. A function made once (at the
 * top of a module), so that each render doesn't count as a new page.
 */
export function useFocusOnArrival(skip: (pathname: string) => boolean = never): void {
  const { pathname } = useLocation()
  // The page shown before: none on the first page. Compared, not counted, so that the
  // development mode's second run of an effect is not taken for a move.
  const shown = useRef<string | null>(null)
  useEffect(() => {
    const before = shown.current
    shown.current = pathname
    if (before === null || before === pathname) return
    if (skip(pathname)) return
    let watch: MutationObserver | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    const stop = () => {
      watch?.disconnect()
      if (timer) clearTimeout(timer)
    }
    // Where the focus was when the page came. A heading that arrives late takes it only if
    // nobody moved it since: someone who already went on (to the skip link, the menu)
    // is never pulled back.
    const atArrival = document.activeElement
    const untouched = () =>
      !pageTookFocus() && (document.activeElement === atArrival || document.activeElement === document.body)
    const take = (place: HTMLElement) => {
      if (!place.hasAttribute('tabindex')) place.setAttribute('tabindex', '-1')
      place.focus()
    }
    const arrive = (): boolean => {
      if (!untouched()) return true
      const heading = mainHeading()
      if (!heading) return false
      take(heading)
      return true
    }
    if (!arrive()) {
      watch = new MutationObserver(() => {
        if (arrive()) stop()
      })
      watch.observe(document.body, { childList: true, subtree: true })
      // A page with no heading at all: its main area takes the focus instead.
      timer = setTimeout(() => {
        stop()
        const main = mainArea()
        if (main && untouched()) take(main)
      }, HEADING_WAIT_MS)
    }
    return stop
  }, [pathname, skip])
}

/** The page itself put the focus somewhere inside its main area (a box to type in). */
function pageTookFocus(): boolean {
  const focused = document.activeElement
  return Boolean(focused && focused !== document.body && mainArea()?.contains(focused))
}
