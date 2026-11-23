import createClient, { type Middleware } from 'openapi-fetch'

import { API_URL } from './address'
import type { components, paths } from './schema'

// The API has its own address, separate from the website's (docs/06 §1).
// The types in ./schema are generated from docs/openapi.json: run `npm run gen:api`.

export type Schemas = components['schemas']

// --- The login token (docs/06 §2.1) ---------------------------------------------------
// The server gives it at login; the website keeps it and sends it in a header on every
// call. It is a random string: it says nothing about the user.

export const TOKEN_KEY = 'dawalink.token'
export const LOGGED_OUT_EVENT = 'dawalink:logged-out'

export function getToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY)
}

/** The code the API answers when the session itself ended (docs/06 §3). */
export const UNAUTHENTICATED = 'UNAUTHENTICATED'

const withLogin: Middleware = {
  onRequest({ request }) {
    const token = getToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  async onResponse({ request, response }) {
    // Only the API's own "your session ended" logs the person out. Another 401, such as a
    // wrong current password on Change password, is an answer for the form (A#11).
    if (response.status !== 401) return response
    const body: unknown = await response
      .clone()
      .json()
      .catch(() => null)
    if (failureFrom(body, 401).code !== UNAUTHENTICATED) return response
    sessionEnded(request.headers.get('Authorization')?.replace(/^Bearer /, '') || null)
    return response
  },
}

/**
 * The API answered "your session ended" (`UNAUTHENTICATED`) to a call sent with the token
 * `sent`: the token is forgotten and the page is told. The one place that does it, for
 * the API client and for the chat's stream, which is read without it (`chatStream.ts`).
 *
 * A late answer for the token of someone who has since logged out and been replaced
 * (another tab, a new login) must not log the new person out. A call sent with no token
 * ended no session.
 */
export function sessionEnded(sent: string | null): void {
  if (!sent) return
  const current = getToken()
  if (current && current !== sent) return
  clearToken()
  window.dispatchEvent(new Event(LOGGED_OUT_EVENT))
}

export const api = createClient<paths>({
  baseUrl: API_URL,
  // Looked up at call time, so tests can replace `fetch`.
  fetch: (request) => globalThis.fetch(request),
})
api.use(withLogin)

// --- Errors (docs/06 §3) --------------------------------------------------------------
// The API always answers a failure with a stable `code`. The website decides what to
// say from the code, never from the server's sentence (docs/11 §7).

export class ApiFailure extends Error {
  readonly code: string
  readonly status: number
  readonly details: Record<string, unknown>

  constructor(code: string, status: number, details: Record<string, unknown> = {}) {
    super(code)
    this.code = code
    this.status = status
    this.details = details
  }
}

/** The call never reached the API: no network, or the API is down. */
export const UNREACHABLE = 'UNREACHABLE'

export function failureFrom(body: unknown, status: number): ApiFailure {
  const error = (body as { error?: { code?: string; details?: Record<string, unknown> } })?.error
  return new ApiFailure(error?.code ?? 'INTERNAL_ERROR', status, withField(error?.details ?? {}))
}

// A body the request schema refuses lists its fields as `details.fields` with a path
// ("pharmacy.location.lat"); a rule's refusal names one `details.field` ("phone"). The
// forms read `details.field`, so the first listed field is also given there, as the form
// names it (A#35).
function withField(details: Record<string, unknown>): Record<string, unknown> {
  if (typeof details.field === 'string' || !Array.isArray(details.fields)) return details
  const first: unknown = details.fields[0]
  const path = (first as { field?: unknown } | undefined)?.field
  const field = typeof path === 'string' ? formField(path) : null
  return field ? { ...details, field } : details
}

/** The bodies that wrap a form's fields in one object: `{pharmacy: {name, …}}`. */
const WRAPPERS = new Set(['pharmacy'])

/**
 * The form's field for a path of the API's body: "phone" → "phone",
 * "pharmacy.name" → "name", "pharmacy.location.lat" → "location",
 * "hours[0].open" → "hours". A pin or a list is one field of the form, so the part of the
 * path under it is dropped; "body" (the whole body was unreadable) is no field.
 */
export function formField(path: string): string | null {
  const names = path.replace(/\[\d+\]/g, '').split('.').filter(Boolean)
  while (names.length > 1 && WRAPPERS.has(names[0])) names.shift()
  const field = names[0]
  return field && field !== 'body' ? field : null
}

/** The data of a call, or an `ApiFailure` thrown. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response }
  try {
    result = await call
  } catch {
    throw new ApiFailure(UNREACHABLE, 0)
  }
  if (result.error !== undefined || !result.response.ok) {
    throw failureFrom(result.error, result.response.status)
  }
  return result.data as T
}

/** A new key for one tap: a double tap or a retry never creates two things (docs/06 §1). */
export function newKey(): string {
  return crypto.randomUUID()
}
