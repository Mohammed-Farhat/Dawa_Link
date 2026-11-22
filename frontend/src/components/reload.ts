// After a new release, a tab opened before it may ask for a part of the website that is
// no longer there (the pharmacy's portal, the map): the import fails. Reloading the page
// once fetches the new release. Never twice in a row: if the reload didn't help, the
// error goes on to the error boundary, which says so and offers the button (A#4).

const RELOADED_AT = 'dawalink.reloadedAt'

/** How long after a reload a second failure is no longer taken for a stale release. */
export const RELOAD_GUARD_MS = 60_000

/**
 * Listens for Vite's event about a part of the website that failed to load. Returns the
 * function that stops listening. `reload` and `now` are given, so a test can stand in.
 */
export function reloadOnceWhenAPartFails(
  reload: () => void = () => window.location.reload(),
  now: () => number = Date.now,
): () => void {
  const onFailure = (event: Event) => {
    const last = Number(read() ?? 0)
    if (now() - last < RELOAD_GUARD_MS) return // reloaded a moment ago: not again
    write(String(now()))
    // The page is about to go: the failure is not thrown to the page.
    event.preventDefault()
    reload()
  }
  window.addEventListener('vite:preloadError', onFailure)
  return () => window.removeEventListener('vite:preloadError', onFailure)
}

// A browser that refuses storage (a private window's settings) never reloads by itself:
// without the mark, it couldn't tell a first failure from a loop.
function read(): string | null {
  try {
    return window.sessionStorage.getItem(RELOADED_AT)
  } catch {
    return String(Number.MAX_SAFE_INTEGER)
  }
}

function write(value: string): void {
  try {
    window.sessionStorage.setItem(RELOADED_AT, value)
  } catch {
    // Nothing to do: `read` already answers "just reloaded" in that browser.
  }
}
