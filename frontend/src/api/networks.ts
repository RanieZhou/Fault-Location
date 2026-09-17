import { apiClient } from './client'
import type { MappingImportResult, NetworkGraph, NetworkOut, TopologyValidationSummary } from './types'

export async function createNetwork(payload: {
  name: string
  voltage_kv?: number | null
  frequency_hz?: number
}): Promise<NetworkOut> {
  const { data } = await apiClient.post<NetworkOut>('/networks', payload)
  return data
}

export async function getNetwork(networkId: string): Promise<NetworkOut> {
  const { data } = await apiClient.get<NetworkOut>(`/networks/${networkId}`)
  return data
}

export async function importMapping(
  networkId: string,
  file: File,
  sheetName: string,
): Promise<MappingImportResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('sheet_name', sheetName)
  const { data } = await apiClient.post<MappingImportResult>(
    `/networks/${networkId}/mapping/import`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

export async function getGraph(networkId: string): Promise<NetworkGraph> {
  const { data } = await apiClient.get<NetworkGraph>(`/networks/${networkId}/graph`)
  return data
}

export async function setSource(networkId: string, nodeId: string): Promise<NetworkOut> {
  const { data } = await apiClient.post<NetworkOut>(`/networks/${networkId}/source`, { node_id: nodeId })
  return data
}

export async function getValidation(networkId: string): Promise<TopologyValidationSummary> {
  const { data } = await apiClient.get<TopologyValidationSummary>(`/networks/${networkId}/validation`)
  return data
}
