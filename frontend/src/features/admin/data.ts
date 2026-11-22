import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { errorMessage, strings } from '../../strings/en'

// What the admin's screens read. The lists that hold work to do ask again by themselves:
// a new escalation must appear without anyone pressing a button.

const REFRESH_MS = 15_000
const PAGE = 50 // the most the API gives at once (docs/04 N-31)

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

export function useAdminPharmacies(status: PharmacyStatus, typed: string) {
  const pages = useInfiniteQuery({
    queryKey: ['admin', 'pharmacies', status, typed],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/admin/pharmacies', {
          params: { query: { status, q: typed, cursor: pageParam, limit: PAGE } },
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
    refetchInterval: status === 'PENDING' ? REFRESH_MS : false,
  })
  return {
    items: pages.data?.pages.flatMap((page) => page.items) ?? [],
    loaded: pages.isSuccess,
    // Nothing yet, and no failure: the list's placeholder is shown (B#43).
    loading: pages.isPending,
    // The request failed (after its retries): the page says so, with [Try again].
    failure: pages.isError ? pages.error : null,
    retry: () => void pages.refetch(),
    hasMore: pages.hasNextPage,
    more: () => void pages.fetchNextPage(),
  }
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

export function useEscalations(resolved: boolean) {
  return useQuery({
    queryKey: ['admin', 'escalations', resolved],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/admin/escalations', {
          params: { query: resolved ? { state: 'RESOLVED', limit: PAGE } : { limit: PAGE } },
        }),
      ),
    refetchInterval: resolved ? false : REFRESH_MS,
  })
}

export function useEscalation(id: string) {
  return useQuery({
    queryKey: ['admin', 'escalation', id],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/admin/escalations/{escalation_id}', {
          params: { path: { escalation_id: id } },
        }),
      ),
    refetchInterval: REFRESH_MS,
  })
}

export function useAnswerReports(state: ReportState) {
  return useQuery({
    queryKey: ['admin', 'reports', state],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/admin/answer-reports', { params: { query: { state, limit: PAGE } } }),
      ),
    refetchInterval: state === 'NEW' ? REFRESH_MS : false,
  })
}

export type AuditFilters = { action: string; actor: string; entity: string }

export function useAudit(filters: AuditFilters) {
  const pages = useInfiniteQuery({
    queryKey: ['admin', 'audit', filters],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/admin/audit', {
          params: {
            query: {
              action: filters.action || undefined,
              actor: (filters.actor || undefined) as Schemas['Actor'] | undefined,
              entity_id: filters.entity || undefined,
              cursor: pageParam ?? undefined,
              limit: PAGE,
            },
          },
        }),
      ),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
    retry: false,
  })
  return {
    items: pages.data?.pages.flatMap((page) => page.items) ?? [],
    loaded: pages.isSuccess,
    // Nothing yet, and no failure: the list's placeholder is shown (B#43).
    loading: pages.isPending,
    failure: pages.isError ? pages.error : null,
    retry: () => void pages.refetch(),
    hasMore: pages.hasNextPage,
    more: () => void pages.fetchNextPage(),
  }
}

export type ClientsHaving = 'reservation' | 'picked_up' | 'request' | 'look'

export function useAdminClients(status: ClientStatus | null, having: ClientsHaving | null, ref: string) {
  const pages = useInfiniteQuery({
    queryKey: ['admin', 'clients', status, having, ref],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/admin/clients', {
          params: {
            query: {
              status: status ?? undefined,
              having: having ?? undefined,
              ref,
              cursor: pageParam,
              limit: PAGE,
            },
          },
        }),
      ),
    // Who has a reservation or a request changes without anyone pressing a button here.
    refetchInterval: REFRESH_MS * 2,
    initialPageParam: 0,
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
  })
  return {
    items: pages.data?.pages.flatMap((page) => page.items) ?? [],
    loaded: pages.isSuccess,
    // Nothing yet, and no failure: the list's placeholder is shown (B#43).
    loading: pages.isPending,
    // The request failed (after its retries): the page says so, with [Try again].
    failure: pages.isError ? pages.error : null,
    retry: () => void pages.refetch(),
    hasMore: pages.hasNextPage,
    more: () => void pages.fetchNextPage(),
  }
}

export function useAdminClient(id: string) {
  return useQuery({
    queryKey: ['admin', 'client', id],
    queryFn: () =>
      unwrap(api.GET('/api/v1/admin/clients/{client_id}', { params: { path: { client_id: id } } })),
  })
}

export function useCatalog(typed: string) {
  const pages = useInfiniteQuery({
    queryKey: ['admin', 'catalog', typed],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/admin/catalog/products', {
          params: { query: { q: typed, cursor: pageParam, limit: PAGE } },
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
    placeholderData: (before) => before,
  })
  return {
    items: pages.data?.pages.flatMap((page) => page.items) ?? [],
    loaded: pages.isSuccess,
    // Nothing yet, and no failure: the list's placeholder is shown (B#43).
    loading: pages.isPending,
    // The request failed (after its retries): the page says so, with [Try again].
    failure: pages.isError ? pages.error : null,
    retry: () => void pages.refetch(),
    hasMore: pages.hasNextPage,
    more: () => void pages.fetchNextPage(),
  }
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
