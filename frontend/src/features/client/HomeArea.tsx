import { NativeSelect } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '../../api/client'
import { strings } from '../../strings/en'
import { useDistricts } from './data'

const s = strings.signUp

export type HomeAreaValue = {
  governorate: string
  /** A district's ID as text, or '' while none is chosen. */
  district: string
  /** A town's ID as text, or '' for the whole district. */
  town: string
}

/** The towns and neighbourhoods of a district, from DawaLink's own list of places. */
function usePlaces(districtId: string) {
  return useQuery({
    queryKey: ['places', districtId],
    queryFn: () =>
      unwrap(api.GET('/api/v1/places', { params: { query: { district_id: Number(districtId) } } })),
    enabled: districtId !== '',
    staleTime: Infinity,
  })
}

/**
 * Where a client lives, as three lists that follow each other: the governorate, its
 * districts, and the towns of the district (decision log BLD-D40). A choice above empties
 * the ones under it: a town belongs to its district.
 */
export function HomeArea({
  value,
  onChange,
  problems = {},
}: {
  value: HomeAreaValue
  onChange: (next: HomeAreaValue) => void
  problems?: { governorate?: string | null | false; district?: string | null | false }
}) {
  const districts = useDistricts()
  const rows = districts.data ?? []
  const governorates = [...new Set(rows.map((row) => row.governorate))].sort()
  const inGovernorate = rows.filter((row) => row.governorate === value.governorate)
  const places = usePlaces(value.district)

  return (
    <div className="auth__form-row auth__form-row--three">
      <NativeSelect
        label={s.governorate}
        size="md"
        value={value.governorate}
        onChange={(event) => onChange({ governorate: event.currentTarget.value, district: '', town: '' })}
        error={problems.governorate}
        data={[{ value: '', label: s.choose }, ...governorates]}
      />
      <NativeSelect
        label={s.district}
        size="md"
        value={value.district}
        disabled={!value.governorate}
        onChange={(event) => onChange({ ...value, district: event.currentTarget.value, town: '' })}
        error={problems.district}
        data={[
          { value: '', label: s.choose },
          ...inGovernorate.map((row) => ({ value: String(row.id), label: row.name })),
        ]}
      />
      <NativeSelect
        label={s.town}
        size="md"
        value={value.town}
        disabled={!value.district}
        onChange={(event) => onChange({ ...value, town: event.currentTarget.value })}
        data={[
          { value: '', label: s.townNone },
          ...(places.data ?? []).map((row) => ({ value: String(row.id), label: row.name })),
        ]}
      />
    </div>
  )
}
