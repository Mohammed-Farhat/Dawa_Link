import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/health')
      if (error || !data) throw new Error('The health check failed')
      return data
    },
    retry: false,
  })
}
