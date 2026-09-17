import { apiClient } from './client'

export interface FieldMappingOut {
  network_id: string
  mapping: Record<string, string>
}

export interface MeasurementImportResult {
  network_id: string
  total_rows: number
  matched: number
  unmatched: number
  unmatched_names: string[]
}

export interface UnmatchedNameRow {
  monitor_name_raw: string
  count: number
}

export interface ResolveUnmatchedResult {
  monitor_name_raw: string
  updated_records: number
  status: string
}

export async function getFieldMapping(networkId: string): Promise<FieldMappingOut> {
  const { data } = await apiClient.get<FieldMappingOut>(`/networks/${networkId}/measurements/mapping`)
  return data
}

export async function setFieldMapping(networkId: string, mapping: Record<string, string>): Promise<FieldMappingOut> {
  const { data } = await apiClient.post<FieldMappingOut>(`/networks/${networkId}/measurements/mapping`, { mapping })
  return data
}

export async function importMeasurements(
  networkId: string,
  file: File,
  sheetName?: string,
): Promise<MeasurementImportResult> {
  const form = new FormData()
  form.append('file', file)
  if (sheetName) form.append('sheet_name', sheetName)
  const { data } = await apiClient.post<MeasurementImportResult>(
    `/networks/${networkId}/measurements/import`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

export async function listUnmatchedNames(networkId: string): Promise<UnmatchedNameRow[]> {
  const { data } = await apiClient.get<UnmatchedNameRow[]>(`/networks/${networkId}/measurements/unmatched`)
  return data
}

export async function resolveUnmatched(
  networkId: string,
  payload: { monitor_name_raw: string; monitor_id?: string; ignore?: boolean },
): Promise<ResolveUnmatchedResult> {
  const { data } = await apiClient.post<ResolveUnmatchedResult>(`/networks/${networkId}/measurements/resolve`, payload)
  return data
}
