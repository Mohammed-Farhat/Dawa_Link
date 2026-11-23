import type { Schemas } from '../../api/client'
import { strings } from '../../strings/en'

// The audit log in words (AS-11; the owner, 2026-11-23: "make it more readable"). Every
// stored code stays as it is; only what is shown is translated. The API never sends the
// value of a field that changed (`services/audit.py`): only its name, a move between two
// of the app's own states, counts, and a code from one of the app's own lists.

const a = strings.admin.audit

export type AuditEvent = Schemas['AuditRow']
export type AuditAction = Schemas['AuditAction']

/** A sentence for every code the backend writes. Typed by the API's own list of codes
 * (`AuditAction`): a code added there without a sentence here fails the typecheck. */
export const SENTENCES: Record<AuditAction, string> = a.actions

/** What happened, said after who did it: "approved a pharmacy". A code with no sentence
 * (an event older than this page) is said as it is stored. */
export function sentence(event: AuditEvent): string {
  const known = event.known_action
  if (!known) return a.unknownAction(event.action)
  const byState = a.byState[known]
  return (event.state_to && byState?.[event.state_to]) || SENTENCES[known]
}

/** One of the app's own states in words ("IN_PROGRESS" is "answered"). */
export function stateWords(code: string): string {
  return a.states[code] ?? code.toLowerCase().replaceAll('_', ' ')
}

/** The fields that changed, in words, once each: "lat" and "lon" are one map pin. */
export function fieldWords(fields: string[]): string[] {
  return [...new Set(fields.map((field) => a.fields[field] ?? field.replaceAll('_', ' ')))]
}

/** What a code chosen from one of the app's lists means for this event. */
function codeWords(event: AuditEvent): string | null {
  const code = event.code
  if (!code) return null
  if (event.action.startsWith('escalation.')) {
    return strings.admin.escalations.reasons[code as keyof typeof strings.admin.escalations.reasons] ?? code
  }
  if (event.action.startsWith('answer_report.')) {
    return strings.chat.report.reasons[code as keyof typeof strings.chat.report.reasons] ?? code
  }
  return a.claimKinds[code] ?? code
}

/**
 * The line under the sentence: the fields that changed (never their values), the move
 * between two states, how many things the action ended, and the reason it was given in
 * a code. Empty when there is nothing more to say.
 */
export function details(event: AuditEvent): string[] {
  const said: string[] = []
  const reason = codeWords(event)
  if (reason) said.push(reason)
  const fields = fieldWords(event.changed)
  if (fields.length > 0) said.push(a.changed(fields.join(', ')))
  // A state the sentence already says ("closed a request: nothing was found") is not
  // said twice.
  const saidByTheSentence = Boolean(event.known_action && event.state_to && a.byState[event.known_action]?.[event.state_to])
  if (event.state_from && event.state_to && event.state_from !== event.state_to && !saidByTheSentence) {
    said.push(a.moved(stateWords(event.state_from), stateWords(event.state_to)))
  }
  for (const [key, count] of Object.entries(event.counts)) {
    const words = a.counts[key]
    if (words) said.push(words(count))
  }
  return said
}

/** Who did it. A client is "A client" and the short ID of their page, never a name. */
export function who(event: AuditEvent): { text: string; short: string | null } {
  const by = event.who
  switch (by.kind) {
    case 'admin':
      return { text: by.name ?? a.who.admin, short: null }
    case 'pharmacy':
      return { text: by.name ?? a.who.pharmacy, short: null }
    case 'client':
      return { text: a.who.client, short: by.id ? by.id.slice(0, 8) : null }
    case 'agent':
      return { text: a.who.agent, short: null }
    default:
      return { text: a.who.system, short: null }
  }
}

/** The page of the console the event is about, and the link's words: none when there is
 * no page (a registration never confirmed, a row deleted since), and the demo clock only
 * in demo mode, where its page exists. */
export function link(event: AuditEvent, demoMode: boolean): { to: string; text: string } | null {
  const subject = event.subject
  if (!subject) return null
  switch (subject.kind) {
    case 'pharmacy': {
      // The pharmacy's own name when it did it; otherwise the page says which one.
      const named = event.who.kind === 'pharmacy' && event.who.id === subject.id ? event.who.name : null
      return subject.id ? { to: `/admin/pharmacies/${subject.id}`, text: named ?? a.links.pharmacy } : null
    }
    case 'client':
      return subject.id ? { to: `/admin/clients/${subject.id}`, text: a.links.client(subject.id.slice(0, 8)) } : null
    case 'escalation':
      return subject.id ? { to: `/admin/escalations/${subject.id}`, text: a.links.escalation } : null
    case 'reports':
      return { to: '/admin/reports', text: a.links.reports }
    case 'clock':
      return demoMode ? { to: '/admin/clock', text: a.links.clock } : null
    default:
      return null
  }
}

/** What a row is about, in a word: "reservation", "box of stock". */
export function thing(entityType: string): string {
  return a.things[entityType] ?? a.thing
}
