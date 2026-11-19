import { useEffect, useState } from 'react'

// On a computer (wider than 992 px) the client's portal is a desktop layout: a top bar
// and pages that use the window's width (docs/11 §3.1, decision log BLD-D40, BLD-D42).

const WIDE = '(min-width: 992px)'

/** True on a screen wide enough for the desktop layout. It follows the window as it is
 * resized. */
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
