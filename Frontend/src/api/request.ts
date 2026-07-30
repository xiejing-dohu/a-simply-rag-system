import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const request = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000
})

let refreshPromise: Promise<string> | null = null

export const refreshAccessToken = async (): Promise<string> => {
  if (refreshPromise) return refreshPromise
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) throw new Error('登录已过期')

  refreshPromise = axios
    .post<{ access_token: string }>(`${API_BASE_URL}/auth/refresh`, {
      refresh_token: refreshToken
    })
    .then(response => {
      localStorage.setItem('token', response.data.access_token)
      return response.data.access_token
    })
    .finally(() => {
      refreshPromise = null
    })
  return refreshPromise
}

const clearSession = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('refresh_token')
}

request.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

request.interceptors.response.use(
  response => response,
  async (error: AxiosError) => {
    const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
    const url = config?.url || ''
    const isAuthRequest = url.includes('/auth/token') || url.includes('/auth/refresh')
    if (error.response?.status === 401 && config && !isAuthRequest && !config._retried) {
      config._retried = true
      try {
        const accessToken = await refreshAccessToken()
        config.headers.Authorization = `Bearer ${accessToken}`
        return request(config)
      } catch {
        clearSession()
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default request
