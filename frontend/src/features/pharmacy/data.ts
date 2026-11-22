import { useInfiniteQuery, useQuery } from '@tanstack/react-query'

import { api, type Schemas, unwrap } from '../../api/client'

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

export function usePharmacyReservations(view: 'active' | 'history', enabled = true) {
  return useQuery({
    queryKey: ['pharmacy', 'reservations', view],
    queryFn: () =>
      unwrap(api.GET('/api/v1/pharmacy/reservations', { params: { query: { view } } })),
    enabled,
    refetchInterval: view === 'active' ? REFRESH_MS : false,
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

// --- The stock (docs/03 PS-6, PS-7) -------------------------------------------------------

export type Zone = 'NEAR_EXPIRY' | 'EARLY_RELEASE' | 'PRIVATE' | 'EXPIRED'

const STOCK_PAGE = 50 // the most the API gives at once (docs/04 N-31)

/**
 * The pharmacy's boxes, soonest expiry first, one page at a time: [Show more] asks for
 * the next one. `zone: 'NEAR_EXPIRY'` is its listings.
 */
/** The longest search the API takes (`q` of /pharmacy/inventory and /catalog/products):
 * a longer one is refused, and the list would go blank. */
export const SEARCH_MAX = 100

export function useStock(zone: Zone | null, typed: string) {
  const pages = useInfiniteQuery({
    queryKey: ['pharmacy', 'stock', zone, typed],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/pharmacy/inventory', {
          params: {
            query: { q: typed, zone: zone ?? undefined, cursor: pageParam, limit: STOCK_PAGE },
          },
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
    // While another search is fetched the rows already shown stay on the screen.
    placeholderData: (before) => before,
  })
  return {
    items: pages.data?.pages.flatMap((page) => page.items) ?? [],
    loaded: pages.isSuccess,
    // The first page is still coming: nothing to show yet, not even an earlier search.
    pending: pages.isPending,
    hasMore: pages.hasNextPage,
    more: () => void pages.fetchNextPage(),
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
