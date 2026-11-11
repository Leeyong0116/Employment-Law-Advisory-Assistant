import type { Region } from '@/api/types'

// Values the API accepts; labels use the exact jurisdiction names (core contribution 4).
export const REGIONS: { value: Region; label: string }[] = [
  { value: 'peninsular', label: 'Peninsular Malaysia and Labuan' },
  { value: 'sabah', label: 'Sabah' },
  { value: 'sarawak', label: 'Sarawak' },
]

export function regionLabel(region: Region): string {
  return REGIONS.find((r) => r.value === region)?.label ?? region
}
