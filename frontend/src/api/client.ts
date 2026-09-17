import axios from 'axios'

export const apiClient = axios.create({
  baseURL: '/api',
})

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    return error.message
  }
  return String(error)
}
