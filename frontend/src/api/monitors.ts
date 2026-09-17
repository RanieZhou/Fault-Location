import { apiClient } from './client'

export interface Monitor {
  monitor_id: string
  network_id: string
  node_id: string
  canonical_name: string
  aliases: string[]
  enabled: boolean
}

export async function listMonitors(networkId: string): Promise<Monitor[]> {
  const { data } = await apiClient.get<Monitor[]>(`/networks/${networkId}/monitors`)
  return data
}

export async function createMonitor(
  networkId: string,
  payload: { node_id: string; canonical_name: string; aliases: string[] },
): Promise<Monitor> {
  const { data } = await apiClient.post<Monitor>(`/networks/${networkId}/monitors`, payload)
  return data
}

export async function updateMonitor(
  monitorId: string,
  payload: { canonical_name?: string; aliases?: string[]; enabled?: boolean },
): Promise<Monitor> {
  const { data } = await apiClient.patch<Monitor>(`/monitors/${monitorId}`, payload)
  return data
}

export async function deleteMonitor(monitorId: string): Promise<void> {
  await apiClient.delete(`/monitors/${monitorId}`)
}
