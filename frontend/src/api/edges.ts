import { apiClient } from './client'
import type { GraphEdge } from './types'

export interface EdgeTableRow {
  edge_id: string
  edge_key: string | null
  node_a_key: string
  node_b_key: string
  status: 'closed' | 'open'
  line_model_id: string | null
  line_type: string | null
  model_name: string | null
  length_km: number | null
  configured: boolean
}

export async function updateEdgeConfig(
  edgeId: string,
  payload: { line_model_id: string | null; length_km: number | null },
): Promise<GraphEdge> {
  const { data } = await apiClient.patch<GraphEdge>(`/edges/${edgeId}`, payload)
  return data
}

export async function batchConfigEdges(payload: {
  edge_ids: string[]
  line_model_id: string
  apply_length?: boolean
  length_km?: number | null
}): Promise<GraphEdge[]> {
  const { data } = await apiClient.post<GraphEdge[]>('/edges/batch-config', payload)
  return data
}

export async function getEdgesTable(networkId: string): Promise<EdgeTableRow[]> {
  const { data } = await apiClient.get<EdgeTableRow[]>(`/networks/${networkId}/edges`)
  return data
}
