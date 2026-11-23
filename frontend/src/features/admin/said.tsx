import { Banner } from '../../components/layout'
import type { Note } from './data'

/**
 * Where a note is shown. With `at`, inside that panel, and only a note of that panel.
 * Without it, at the top of the page: a note of no panel, or of a panel that is no longer
 * on the page (`present` lists the ones that are), so that nothing said is lost.
 */
export function Said({ note, at, present = [] }: { note: Note | null; at?: string; present?: string[] }) {
  const shown = note !== null && (at === undefined ? !note.at || !present.includes(note.at) : note.at === at)
  return (
    <div role="status" aria-live="polite">
      {shown && <Banner tone={note.tone}>{note.text}</Banner>}
    </div>
  )
}
