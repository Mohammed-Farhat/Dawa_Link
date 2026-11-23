import { strings } from '../strings/en'

/**
 * What a list shows while it loads (docs/11 §7, B#43): grey shapes of its cards, still
 * (no animation), so that nothing jumps when the rows arrive on a slow phone. A screen
 * reader hears the common "Loading…".
 *
 * `count`: how many cards; `height`: a card's height, in pixels, near the real rows'.
 */
export function Placeholder({ count = 3, height = 96 }: { count?: number; height?: number }) {
  return (
    <div className="placeholder" role="status">
      <span className="sr-only">{strings.common.loading}</span>
      {Array.from({ length: count }, (_, at) => (
        <div key={at} className="placeholder__card" style={{ height }} aria-hidden="true" />
      ))}
    </div>
  )
}
