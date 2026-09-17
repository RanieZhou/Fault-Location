import { apiClient } from './client'

export interface BaselineBuildResult {
  network_id: string
  monitors_with_baseline: number
  baseline_rows: number
}

export interface BaselineStatOut {
  monitor_id: string
  canonical_name: string
  signal: string
  count: number
  mean: number | null
  std: number | null
  median: number | null
  start_time: string | null
  end_time: string | null
}

export interface ReadinessItem {
  key: string
  label: string
  passed: boolean
  detail: string | null
}

export interface NetworkReadiness {
  network_id: string
  ready: boolean
  items: ReadinessItem[]
}

export async function buildBaseline(networkId: string): Promise<BaselineBuildResult> {
  const { data } = await apiClient.post<BaselineBuildResult>(`/networks/${networkId}/baseline/build`)
  return data
}

export async function getBaseline(networkId: string): Promise<BaselineStatOut[]> {
  const { data } = await apiClient.get<BaselineStatOut[]>(`/networks/${networkId}/baseline`)
  return data
}

export async function getReadiness(networkId: string): Promise<NetworkReadiness> {
  const { data } = await apiClient.get<NetworkReadiness>(`/networks/${networkId}/readiness`)
  return data
}
