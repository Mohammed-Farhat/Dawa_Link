import { createContext, type ReactNode, useEffect, useState } from 'react'

// Wider than 992 px the client's portal has a top bar instead of the floating menu, and
// the assistant stands beside the page (docs/11 §3.1).

const WIDE = '(min-width: 992px)'

/** True on a screen wide enough for the side panel. It follows the window's size. */
export function useWide(): boolean {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE).matches)
  useEffect(() => {
    const query = window.matchMedia(WIDE)
    const follow = () => setWide(query.matches)
    query.addEventListener('change', follow)
    return () => query.removeEventListener('change', follow)
  }, [])
  return wide
}

/**
 * What stands beside a page on a wide screen: the assistant. The app gives it; a screen
 * only places it. (A screen can't import the assistant itself: the assistant's own
 * pages are built from screens.) null: nothing beside the page.
 */
export const SidePanelContext = createContext<ReactNode>(null)
