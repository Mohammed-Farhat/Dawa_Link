import { strings } from '../strings/en'
import { Banner } from './layout'

/**
 * What stands in for a page that can't be shown yet (docs/11 §7: never a blank screen).
 *
 * - While a page, a portal or the question "who is logged in?" is on its way: the common
 *   "Loading…" line.
 * - When the API can't be reached: the amber "Can't reach DawaLink. Retrying…" line. It is
 *   not a log out, so the person is never sent to the welcome or the login page for it.
 */
export function Waiting({ unreachable = false }: { unreachable?: boolean }) {
  return (
    <main className="screen screen--plain" id="main" tabIndex={-1}>
      {unreachable ? (
        <Banner tone="amber">{strings.banner.offline}</Banner>
      ) : (
        <p className="soft" role="status">
          {strings.common.loading}
        </p>
      )}
    </main>
  )
}
