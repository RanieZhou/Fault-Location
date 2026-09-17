import { apiClient } from './client'

export interface LineModel {
  line_model_id: string
  line_type: string
  model_name: string
  r_ohm_per_km: number
  x_ohm_per_km: number
  c_nf_per_km: number
  source: 'preset' | 'custom'
  enabled: boolean
  remark: string | null
}

export interface LineModelCreatePayload {
  line_type: string
  model_name: string
  r_ohm_per_km: number
  x_ohm_per_km: number
  c_nf_per_km: number
  remark?: string | null
}

export interface LineModelUpdatePayload {
  model_name?: string
  r_ohm_per_km?: number
  x_ohm_per_km?: number
  c_nf_per_km?: number
  enabled?: boolean
  remark?: string | null
}

export async function listLineModels(params?: { enabled_only?: boolean; line_type?: string }): Promise<LineModel[]> {
  const { data } = await apiClient.get<LineModel[]>('/line-models', { params })
  return data
}

export async function createLineModel(payload: LineModelCreatePayload): Promise<LineModel> {
  const { data } = await apiClient.post<LineModel>('/line-models', payload)
  return data
}

export async function updateLineModel(id: string, payload: LineModelUpdatePayload): Promise<LineModel> {
  const { data } = await apiClient.patch<LineModel>(`/line-models/${id}`, payload)
  return data
}

export async function deleteLineModel(id: string): Promise<void> {
  await apiClient.delete(`/line-models/${id}`)
}
