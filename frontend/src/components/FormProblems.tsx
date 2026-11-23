import { useEffect, useRef } from 'react'

import { strings } from '../strings/en'

/** What makes a field "in error" for the focus: the component library marks its fields
 * with `aria-invalid` (a password box marks its frame, and the box itself
 * `data-invalid`); anything else (a pin on a map, a week of hours) carries
 * `data-problem` on a focusable element (`tabIndex={-1}`). */
const IN_ERROR = [
  'input[aria-invalid="true"]',
  'input[data-invalid]',
  'select[aria-invalid="true"]',
  'textarea[aria-invalid="true"]',
  '[data-problem]',
].join(', ')

/**
 * One line by a form's button after a refused submit: "Check the 3 fields marked in red
 * above." The errors themselves are next to their fields, often a screen or more above
 * the button, so the pharmacist or the client would otherwise see nothing happen.
 *
 * Each refused submit (`attempt` goes up by one, a refusal of the server that names a
 * field included) moves the focus to the first field in error, in the page's order, and
 * brings it into view. Fixing a field changes the count without moving the focus again.
 *
 * Put it inside the `<form>`, just before its button. `count` is what the form itself
 * knows is wrong, never read from the page.
 */
export function FormProblems({ count, attempt }: { count: number; attempt: number }) {
  const line = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    if (attempt === 0) return
    const form = line.current?.closest('form')
    const first = form?.querySelector<HTMLElement>(IN_ERROR)
    if (!first) return
    first.scrollIntoView?.({ block: 'center' })
    first.focus({ preventScroll: true })
    // Only a new submit moves the focus: typing a correction must not.
  }, [attempt])

  if (attempt === 0 || count === 0) return null
  return (
    // A new element for each submit: the alert is read again even with the same words.
    <p key={attempt} ref={line} role="alert" className="field-problem" style={{ margin: 0 }}>
      {strings.forms.check(count)}
    </p>
  )
}
