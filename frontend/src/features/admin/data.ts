import { useInfiniteQuery, useQuery } from '@tanstack/react-query'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'

// What the admin's screens read. The lists that hold work to do ask again by themselves:
// a new escalation must appear without anyone pressing a button.

const REFRESH_MS = 15_000
const PAGE = 50 // the most the API gives at once (docs/04 N-31)

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

export function useAnswerReport(id: string) {
  return useQuery({
    queryKey: ['admin', 'report', id],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/admin/answer-reports/{report_id}', {
          params: { path: { report_id: id } },
        }),
      ),
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
    failed: pages.isError,
    hasMore: pages.hasNextPage,
    more: () => void pages.fetchNextPage(),
  }
}

export function useAdminClients(status: ClientStatus | null, ref: string) {
  const pages = useInfiniteQuery({
    queryKey: ['admin', 'clients', status, ref],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/admin/clients', {
          params: { query: { status: status ?? undefined, ref, cursor: pageParam, limit: PAGE } },
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
  })
  return {
    items: pages.data?.pages.flatMap((page) => page.items) ?? [],
    loaded: pages.isSuccess,
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

export function useFlags() {
  return useQuery({
    queryKey: ['admin', 'flags'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/abuse-flags', { params: { query: { limit: PAGE } } })),
    refetchInterval: REFRESH_MS,
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

/** Saves text the browser already has as a file: the regression cases. */
export function saveText(text: string, name: string, type: string): void {
  const address = URL.createObjectURL(new Blob([text], { type }))
  const link = document.createElement('a')
  link.href = address
  link.download = name
  link.click()
  URL.revokeObjectURL(address)
}
