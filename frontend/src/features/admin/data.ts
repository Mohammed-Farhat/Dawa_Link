import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import type { paths } from '../../api/schema'
import { PAGE_ROWS } from '../../components/usePage'
import { errorMessage, strings } from '../../strings/en'

// What the admin's screens read. The lists that hold work to do ask again by themselves:
// a new escalation must appear without anyone pressing a button.

const REFRESH_MS = 15_000

/** The longest text the API takes in a list's box (api/routes/admin.py): a longer one is
 * refused, and kept in the address it would be refused on every visit. */
export const TYPED_MAX = { ref: 20, search: 100 } as const

export type PharmacyStatus = Schemas['AdminPharmacyRow']['status']
export type EscalationState = Schemas['EscalationRow']['state']
export type ReportState = Schemas['AnswerReportRow']['state']
export type ClientStatus = Schemas['AdminClientRow']['status']

/**
 * "Fri 13 Nov 09:30", in Beirut time. Always the date itself, never "today": the
 * console's times are the app's, and after a demo-clock move "today" on this computer
 * is not today in the app.
 */
export function when(moment: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Beirut',
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
    .format(new Date(moment))
    .replace(',', '')
}

export function codeOf(error: unknown): string {
  return error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
}

/** What an action answered. `at` names the panel whose button caused it (see `Said`). */
export type Note = { tone: 'green' | 'red' | 'amber'; text: string; at?: string }

/**
 * A refusal, to be said in the panel whose button caused it: a message at the top of the
 * page, far from the button, went unseen. "This changed since you opened it" is the
 * exception: the page is read again and the panel may be gone, so it is said at the top.
 */
export function refusal(error: unknown, at: string, words: (code: string) => string = errorMessage): Note {
  const code = codeOf(error)
  if (code === 'CHANGED_SINCE') return { tone: 'amber', text: strings.admin.changed }
  return { tone: 'red', text: words(code), at }
}

/** What a page that could not be read says. An address with a mistyped ID is refused as
 * a malformed field; for the person reading it, it is a page that isn't there. */
export function loadProblem(error: unknown): string {
  const code = codeOf(error)
  return errorMessage(code === 'VALIDATION_ERROR' ? 'NOT_FOUND' : code)
}

/**
 * A list's choices (its tab, its filter, the typed number) live in the page's address,
 * so that "Back to the list" finds the list as the admin left it. Typing replaces the
 * address instead of adding to the history: Back still leaves the list in one press.
 */
export function useListChoices() {
  const [params, setParams] = useSearchParams()
  const choose = useCallback(
    (key: string, value: string | null) =>
      setParams(
        (before) => {
          const next = new URLSearchParams(before)
          if (value) next.set(key, value)
          else next.delete(key)
          return next
        },
        { replace: true },
      ),
    [setParams],
  )
  return [params, choose] as const
}

/** A choice read from the address, if it is one of the list's own; else its default. */
export function oneOf<T extends string>(value: string | null, allowed: readonly (T | null)[], fallback: T | null = null) {
  return (allowed.find((choice) => choice !== null && choice === value) ?? fallback) as T | null
}

/** What a row hands to the page it opens: the list's address, choices included. */
export function useFromList(): { list: string } {
  const { pathname, search } = useLocation()
  return { list: pathname + search }
}

/** Where "Back to the list" goes: the list the admin came from, else the list as it opens. */
export function useBackToList(list: string): string {
  const from = (useLocation().state as { list?: unknown } | null)?.list
  return typeof from === 'string' && (from === list || from.startsWith(`${list}?`)) ? from : list
}

export function useOverview() {
  return useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/overview')),
    refetchInterval: REFRESH_MS,
  })
}

/**
 * One page of a numbered list (`components/Pager.tsx`), as its screen reads it. The rows
 * of the page before stay on the screen while the next page comes (`settled` is false
 * meanwhile: the pager waits for the answer before moving an address past the end).
 */
function asPage<Data extends { items: unknown[]; total: number }>(query: UseQueryResult<Data>) {
  return {
    items: (query.data?.items ?? []) as Data['items'],
    // How many rows the list's choices match, on every page (the API's `total`).
    total: query.data?.total,
    settled: !query.isPlaceholderData,
    loaded: query.isSuccess,
    // Nothing yet, and no failure: the list's placeholder is shown (B#43).
    loading: query.isPending,
    // The request failed (after its retries): the page says so, with [Try again].
    failure: query.isError ? query.error : null,
    retry: () => void query.refetch(),
  }
}

/** One page of the pharmacies. `offset` is the pager's (`usePage`). */
export function useAdminPharmacies(status: PharmacyStatus, typed: string, offset: number) {
  return asPage(
    useQuery({
      queryKey: ['admin', 'pharmacies', status, typed, offset],
      queryFn: () =>
        unwrap(
          api.GET('/api/v1/admin/pharmacies', {
            params: { query: { status, q: typed, cursor: offset, limit: PAGE_ROWS } },
          }),
        ),
      refetchInterval: status === 'PENDING' ? REFRESH_MS : false,
      placeholderData: keepPreviousData,
    }),
  )
}

export function useAdminPharmacy(id: string) {
  return useQuery({
    queryKey: ['admin', 'pharmacy', id],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/admin/pharmacies/{pharmacy_id}', {
          params: { path: { pharmacy_id: id } },
        }),
      ),
  })
}

/** One page of the escalations: the cases to work on, or the closed ones. `offset` is
 * the pager's (`usePage`). The rows stay on the screen while the next page comes. */
export function useEscalations(resolved: boolean, offset: number) {
  return useQuery({
    queryKey: ['admin', 'escalations', resolved, offset],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/admin/escalations', {
          params: {
            query: resolved
              ? { state: 'RESOLVED', cursor: offset, limit: PAGE_ROWS }
              : { cursor: offset, limit: PAGE_ROWS },
          },
        }),
      ),
    refetchInterval: resolved ? false : REFRESH_MS,
    placeholderData: keepPreviousData,
  })
}

/** How often an escalation's page asks again while the client's chat is with the team:
 * the admin and the client are writing to each other. */
const CHAT_REFRESH_MS = 5_000

export function useEscalation(id: string) {
  return useQuery({
    queryKey: ['admin', 'escalation', id],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/admin/escalations/{escalation_id}', {
          params: { path: { escalation_id: id } },
        }),
      ),
    refetchInterval: (query) => (query.state.data?.escalation.hold_ends_at ? CHAT_REFRESH_MS : REFRESH_MS),
  })
}

/** One page of the reported answers in one state. `offset` is the pager's (`usePage`). */
export function useAnswerReports(state: ReportState, offset: number) {
  return useQuery({
    queryKey: ['admin', 'reports', state, offset],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/admin/answer-reports', {
          params: { query: { state, cursor: offset, limit: PAGE_ROWS } },
        }),
      ),
    refetchInterval: state === 'NEW' ? REFRESH_MS : false,
    placeholderData: keepPreviousData,
  })
}

/** A family of the audit log's "Kind" filter (`domain/audit_actions.py`, `KINDS`). */
export type AuditKind = NonNullable<
  NonNullable<paths['/api/v1/admin/audit']['get']['parameters']['query']>['kind']
>
export type AuditActor = Schemas['Actor']

/** The audit log's choices: a family of actions, who did it, and one thing it is about
 * (its kind of row and its ID, from a row's [Only this]). */
export type AuditFilters = {
  kind: AuditKind | null
  actor: AuditActor | null
  about: { type: string; id: string } | null
}

/** One page of the audit log, newest first. Numbered pages send `offset` only. */
export function useAudit(filters: AuditFilters, offset: number) {
  return asPage(
    useQuery({
      queryKey: ['admin', 'audit', filters, offset],
      queryFn: () =>
        unwrap(
          api.GET('/api/v1/admin/audit', {
            params: {
              query: {
                kind: filters.kind ?? undefined,
                actor: filters.actor ?? undefined,
                entity_type: filters.about?.type,
                entity_id: filters.about?.id,
                offset,
                limit: PAGE_ROWS,
              },
            },
          }),
        ),
      retry: false,
      placeholderData: keepPreviousData,
    }),
  )
}

export type ClientsHaving = 'reservation' | 'picked_up' | 'request' | 'look'

/** One page of the clients. `offset` is the pager's (`usePage`). */
export function useAdminClients(
  status: ClientStatus | null,
  having: ClientsHaving | null,
  ref: string,
  offset: number,
) {
  return asPage(
    useQuery({
      queryKey: ['admin', 'clients', status, having, ref, offset],
      queryFn: () =>
        unwrap(
          api.GET('/api/v1/admin/clients', {
            params: {
              query: {
                status: status ?? undefined,
                having: having ?? undefined,
                ref,
                cursor: offset,
                limit: PAGE_ROWS,
              },
            },
          }),
        ),
      // Who has a reservation or a request changes without anyone pressing a button here.
      refetchInterval: REFRESH_MS * 2,
      placeholderData: keepPreviousData,
    }),
  )
}

export function useAdminClient(id: string) {
  return useQuery({
    queryKey: ['admin', 'client', id],
    queryFn: () =>
      unwrap(api.GET('/api/v1/admin/clients/{client_id}', { params: { path: { client_id: id } } })),
  })
}

/** One page of the catalog. `offset` is the pager's (`usePage`). */
export function useCatalog(typed: string, offset: number) {
  return asPage(
    useQuery({
      queryKey: ['admin', 'catalog', typed, offset],
      queryFn: () =>
        unwrap(
          api.GET('/api/v1/admin/catalog/products', {
            params: { query: { q: typed, cursor: offset, limit: PAGE_ROWS } },
          }),
        ),
      placeholderData: keepPreviousData,
    }),
  )
}

export function useCatalogImports() {
  return useQuery({
    queryKey: ['admin', 'catalog-imports'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/catalog/imports')),
  })
}

export function useAdminHealth(days: number) {
  return useQuery({
    queryKey: ['admin', 'health', days],
    queryFn: () => unwrap(api.GET('/api/v1/admin/health', { params: { query: { days } } })),
    refetchInterval: REFRESH_MS * 2,
  })
}

export function useDemoClock() {
  return useQuery({
    queryKey: ['admin', 'clock'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/demo-clock')),
    refetchInterval: REFRESH_MS,
  })
}
