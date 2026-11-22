import { strings } from '../strings/en'
import { CheckIcon } from './icons'
import { PASSWORD_PART_NAMES, passwordGaps } from './passwordRule'

const s = strings.password

/** The rule under a new password's box, each part ticked as soon as it holds. A tick is
 * a mark and a colour, and a screen reader is told "met" or "missing". */
export function PasswordRules({ password }: { password: string }) {
  const missing = new Set(passwordGaps(password))
  return (
    <ul className="rules" aria-label={s.rulesLabel}>
      {PASSWORD_PART_NAMES.map((part) => {
        const met = !missing.has(part)
        return (
          <li key={part} data-met={met}>
            <span className="rules__mark" aria-hidden="true">
              {met && <CheckIcon small />}
            </span>
            {s.rules[part]}
            <span className="sr-only">{met ? s.met : s.missing}</span>
          </li>
        )
      })}
    </ul>
  )
}

/**
 * The same rule in one sentence, for the password box's own description: "A password
 * needs: At least 10 characters (met), A capital letter (A to Z) (missing), …". A screen
 * reader says it on arriving in the box. The list above can't be tied to the box: the
 * library's password box sets its own `aria-describedby`, from its `description`.
 */
export function PasswordRulesSaid({ password }: { password: string }) {
  const missing = new Set(passwordGaps(password))
  const parts = PASSWORD_PART_NAMES.map((part) => `${s.rules[part]} ${missing.has(part) ? s.missing : s.met}`)
  return <>{`${s.rulesLabel}: ${parts.join(', ')}.`}</>
}
