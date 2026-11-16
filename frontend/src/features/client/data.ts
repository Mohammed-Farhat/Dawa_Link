import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '../../api/client'

// What several screens of the client's portal read from the API.

export function usePublicConfig() {
  return useQuery({
    queryKey: ['config'],
    queryFn: () => unwrap(api.GET('/api/v1/config/public')),
    staleTime: 5 * 60_000,
  })
}

export function useDistricts() {
  return useQuery({
    queryKey: ['districts'],
    queryFn: () => unwrap(api.GET('/api/v1/districts')),
    staleTime: Infinity,
  })
}

export function useReservations(view: 'active' | 'history') {
  return useQuery({
    queryKey: ['reservations', view],
    queryFn: () => unwrap(api.GET('/api/v1/reservations', { params: { query: { view } } })),
  })
}

export function useReservation(id: string) {
  return useQuery({
    queryKey: ['reservation', id],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/reservations/{reservation_id}', {
          params: { path: { reservation_id: id } },
        }),
      ),
    retry: false,
  })
}

/** The offers waiting for the client's tap. Asked again often: an offer lasts two hours. */
export function useOffers() {
  return useQuery({
    queryKey: ['offers'],
    queryFn: () => unwrap(api.GET('/api/v1/offers')),
    refetchInterval: 10_000,
  })
}

export function useRequests(state: 'open' | 'closed') {
  return useQuery({
    queryKey: ['requests', state],
    queryFn: () => unwrap(api.GET('/api/v1/requests', { params: { query: { state } } })),
    refetchInterval: state === 'open' ? 10_000 : false,
  })
}
