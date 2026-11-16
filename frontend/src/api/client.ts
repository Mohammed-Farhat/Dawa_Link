import createClient, { type Middleware } from 'openapi-fetch'

import { API_URL } from './address'
import type { components, paths } from './schema'

// The API has its own address, separate from the website's (docs/06 §1).
// The types in ./schema are generated from docs/openapi.json: run `npm run gen:api`.

export type Schemas = components['schemas']

// --- The login token (docs/06 §2.1) ---------------------------------------------------
// The server gives it at login; the website keeps it and sends it in a header on every
// call. It is a random string: it says nothing about the user.

const TOKEN_KEY = 'dawalink.token'
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

const withLogin: Middleware = {
  onRequest({ request }) {
    const token = getToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  onResponse({ response }) {
    // The session ended (expired, logged out elsewhere, suspended): forget the token.
    if (response.status === 401 && getToken()) {
      clearToken()
      window.dispatchEvent(new Event(LOGGED_OUT_EVENT))
    }
    return response
  },
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
  return new ApiFailure(error?.code ?? 'INTERNAL_ERROR', status, error?.details ?? {})
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
