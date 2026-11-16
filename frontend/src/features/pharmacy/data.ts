import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '../../api/client'

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
