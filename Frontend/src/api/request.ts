/** Axios HTTP 请求客户端与拦截器封装模块

包含请求 Authorization Token 自动注入、401 自动无感刷新 Access Token、
以及刷新失败自动清理 Session 重定向登录页逻辑。
*/

import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { API_BASE_URL } from '../config/runtime'

export { API_BASE_URL }

// 创建全局 Axios 实例
const request = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000
})

// 并发刷新 Token 锁 Promise
let refreshPromise: Promise<string> | null = null

/**
 * 刷新 Access Token
 * @returns {Promise<string>} 返回最新 Access Token
 */
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

/** 清理本地登录会话状态 */
const clearSession = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('refresh_token')
}

// 请求拦截器：向 Authorization 请求头注入 Bearer Token
request.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截器：处理 401 未授权自动刷新 Token 与无感重试
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
