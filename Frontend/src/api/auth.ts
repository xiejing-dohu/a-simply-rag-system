import request from './request'
import type { LoginForm, RegisterForm, TokenResponse, User } from '../types'

export const login = (data: LoginForm) => {
  // 注意，登录通常使用 form-data 格式传递 oauth2
  const formData = new FormData()
  formData.append('username', data.username)
  formData.append('password', data.password)
  return request.post<TokenResponse>('/auth/token', formData)
}

export const register = (data: RegisterForm) => {
  return request.post<User>('/auth/register', data)
}

export const getMe = () => {
  return request.get<User>('/auth/me')
}

export const logout = (refreshToken: string) => {
  return request.post('/auth/logout', { refresh_token: refreshToken })
}

export const getUsers = () => {
  return request.get<User[]>('/auth/users')
}

export const updateUser = (id: number, data: Partial<User>) => {
  return request.put<User>(`/auth/users/${id}`, data)
}

export type TokenUsageResetScope = 'five_hour' | 'weekly' | 'all'

export const resetTokenUsage = (id: number, scope: TokenUsageResetScope) => {
  return request.post<User>(`/auth/users/${id}/token-usage/reset`, { scope })
}
