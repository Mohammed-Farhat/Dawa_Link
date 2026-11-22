import { Banner } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { codeOf } from './data'

/**
 * A list whose request failed. Without it the page showed no rows, no "nothing matches"
 * and no error: a blank page. The rows already shown, if any, stay under it.
 */
export function ListFailed({ failure, onRetry }: { failure: unknown; onRetry: () => void }) {
  return (
    <Banner
      tone="red"
      alert
      action={
        <button type="button" className="text-button" onClick={onRetry}>
          {strings.common.tryAgain}
        </button>
      }
    >
      {strings.admin.listFailed} {errorMessage(codeOf(failure))}
    </Banner>
  )
}
