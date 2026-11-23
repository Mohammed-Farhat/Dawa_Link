import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api, type Schemas, unwrap } from '../../api/client'
import { PAGE_ROWS } from '../../components/usePage'

// What the pharmacy's screens read. The counter's lists ask again every few seconds:
// a new reservation must appear without anyone pressing a button.

const REFRESH_MS = 10_000

export function usePharmacy() {
  return useQuery({
    queryKey: ['pharmacy', 'me'],
    queryFn: () => unwrap(api.GET('/api/v1/pharmacy/me')),
    refetchInterval: 60_000,
  })
}

export function useDashboard(enabled: boolean) {
  return useQuery({
    queryKey: ['pharmacy', 'dashboard'],
    queryFn: () => unwrap(api.GET('/api/v1/pharmacy/dashboard')),
    enabled,
    refetchInterval: REFRESH_MS,
  })
}

/** One page of the Reservations tab: `offset` is the paging's (`offsetOf(page)`). */
export function usePharmacyReservations(view: 'active' | 'history', offset: number) {
  return useQuery({
    queryKey: ['pharmacy', 'reservations', view, offset],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/pharmacy/reservations', {
          params: { query: { view, cursor: offset, limit: PAGE_ROWS } },
        }),
      ),
    refetchInterval: view === 'active' ? REFRESH_MS : false,
    // The rows, and the pager under them, stay while the next page comes.
    placeholderData: keepPreviousData,
  })
}

/** The most reservations Today shows at once: the API's own most (docs/04 N-31). More
 * are said as "N more on Reservations". */
export const TODAY_ROWS = 50

/** What is waiting to be handed over, the soonest deadline first, for Today. */
export function useDueReservations() {
  return useQuery({
    queryKey: ['pharmacy', 'reservations', 'today'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/pharmacy/reservations', {
          params: { query: { view: 'active', limit: TODAY_ROWS } },
        }),
      ),
    refetchInterval: REFRESH_MS,
  })
}

/** The reservation with the number typed at the counter. Empty while nothing is typed. */
export function useReservationByNumber(typed: string) {
  return useQuery({
    queryKey: ['pharmacy', 'reservations', 'number', typed],
    queryFn: () =>
      unwrap(api.GET('/api/v1/pharmacy/reservations', { params: { query: { q: typed } } })),
    enabled: typed.length > 0,
  })
}

export function useAsks(enabled: boolean) {
  return useQuery({
    queryKey: ['pharmacy', 'asks'],
    queryFn: () =>
      unwrap(api.GET('/api/v1/pharmacy/early-release-asks', { params: { query: { view: 'open' } } })),
    enabled,
    refetchInterval: REFRESH_MS,
  })
}

/** How many answered asks Today shows under the open ones. */
export const ASKS_ANSWERED_SHOWN = 5

/** The asks the pharmacy answered, or that ended, the newest first (PS-9). */
export function useAnsweredAsks(enabled: boolean) {
  return useQuery({
    queryKey: ['pharmacy', 'asks', 'history'],
    queryFn: () =>
      unwrap(api.GET('/api/v1/pharmacy/early-release-asks', { params: { query: { view: 'history' } } })),
    enabled,
    refetchInterval: REFRESH_MS,
    select: (answer) => answer.items.slice(0, ASKS_ANSWERED_SHOWN),
  })
}

// --- The stock (docs/03 PS-6, PS-7) -------------------------------------------------------

export type Zone = 'NEAR_EXPIRY' | 'EARLY_RELEASE' | 'PRIVATE' | 'EXPIRED'

/** The orders of the stock's list: the soonest expiry first, or one medicine's boxes
 * side by side (`sort` of GET /pharmacy/inventory). */
export const STOCK_SORTS = ['expiry', 'medicine'] as const
export type StockSort = (typeof STOCK_SORTS)[number]

/** The longest search the API takes (`q` of /pharmacy/inventory and /catalog/products):
 * a longer one is refused, and the list would go blank. */
export const SEARCH_MAX = 100

/**
 * One page of the pharmacy's boxes. `zone: 'NEAR_EXPIRY'` is its listings; `offset` is
 * the paging's (`offsetOf(page)`).
 */
export function useStock(zone: Zone | null, typed: string, sort: StockSort, offset: number) {
  const page = useQuery({
    queryKey: ['pharmacy', 'stock', zone, typed, sort, offset],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/pharmacy/inventory', {
          params: {
            query: { q: typed, zone: zone ?? undefined, sort, cursor: offset, limit: PAGE_ROWS },
          },
        }),
      ),
    // While another page or search is fetched the rows already shown stay on the screen.
    placeholderData: keepPreviousData,
  })
  return {
    items: page.data?.items ?? [],
    total: page.data?.total,
    loaded: page.isSuccess,
    // The answer shown is the one for these choices, not the one kept while it comes.
    settled: page.isSuccess && !page.isPlaceholderData,
    // The first page is still coming: nothing to show yet, not even an earlier search.
    pending: page.isPending,
  }
}

/** The stock file that was read and waits for [Apply] or [Discard], if there is one. */
export function useWaitingUpload() {
  return useQuery({
    queryKey: ['pharmacy', 'upload'],
    queryFn: () => unwrap(api.GET('/api/v1/pharmacy/inventory/uploads/waiting')),
  })
}

export function sendStockFile(file: File): Promise<Schemas['StockUpload']> {
  return unwrap(
    api.POST('/api/v1/pharmacy/inventory/uploads', {
      // The generated type calls the file a string; a browser sends the file itself.
      body: { file: file as unknown as string },
      bodySerializer: () => {
        const form = new FormData()
        form.append('file', file)
        return form
      },
    }),
  )
}

/**
 * Saves a file the API answers with. A plain link can't do it: the login travels in a
 * header that only our own calls carry (docs/06 §2.1).
 */
export async function saveFile(
  path: '/api/v1/pharmacy/inventory/template' | '/api/v1/pharmacy/inventory/uploads/{upload_id}/errors.csv',
  name: string,
  uploadId = '',
): Promise<void> {
  const file =
    path === '/api/v1/pharmacy/inventory/template'
      ? await unwrap(api.GET(path, { parseAs: 'blob' }))
      : await unwrap(
          api.GET(path, { params: { path: { upload_id: uploadId } }, parseAs: 'blob' }),
        )
  const address = URL.createObjectURL(file as Blob)
  const link = document.createElement('a')
  link.href = address
  link.download = name
  link.click()
  URL.revokeObjectURL(address)
}
