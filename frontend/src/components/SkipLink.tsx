import type { MouseEvent } from 'react'

import { strings } from '../strings/en'
import { mainArea } from './arrival'

/**
 * "Skip to content": the first thing the keyboard reaches on every page, hidden until it
 * has the focus. It moves the focus past the menus to the page's main area (B#34), which
 * `useNamedPage` gives the id "main". The address bar keeps its address.
 */
export function SkipLink() {
  function skip(event: MouseEvent<HTMLAnchorElement>) {
    const main = mainArea()
    if (!main) return
    event.preventDefault()
    if (!main.hasAttribute('tabindex')) main.setAttribute('tabindex', '-1')
    main.focus()
    main.scrollIntoView?.({ block: 'start' })
  }
  return (
    <a href="#main" className="skip-link" onClick={skip}>
      {strings.shell.skip}
    </a>
  )
}
