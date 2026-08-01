/** 用户认证与权限接口请求模块 */

import request from './request'
import type { LoginForm, RegisterForm, TokenResponse, User } from '../types'

/**
 * 用户登录
 * @param {LoginForm} data 登录参数
 */
export const login = (data: LoginForm) => {
  const formData = new FormData()
  formData.append('username', data.username)
  formData.append('password', data.password)
  return request.post<TokenResponse>('/auth/token', formData)
}

/**
 * 用户注册
 * @param {RegisterForm} data 注册参数
 */
export const register = (data: RegisterForm) => {
  return request.post<User>('/auth/register', data)
}

/** 获取当前登录用户信息 */
export const getMe = () => {
  return request.get<User>('/auth/me')
}

/**
 * 退出登录
 * @param {string} refreshToken 刷新令牌
 */
export const logout = (refreshToken: string) => {
  return request.post('/auth/logout', { refresh_token: refreshToken })
}

/** 管理员获取系统用户列表 */
export const getUsers = () => {
  return request.get<User[]>('/auth/users')
}

/**
 * 管理员更新用户信息
 * @param {number} id 用户 ID
 * @param {Partial<User>} data 变更信息
 */
export const updateUser = (id: number, data: Partial<User>) => {
  return request.put<User>(`/auth/users/${id}`, data)
}

/** Token 重置范围类型 */
export type TokenUsageResetScope = 'five_hour' | 'weekly' | 'all'

/**
 * 管理员重置用户 Token 额度使用量
 * @param {number} id 用户 ID
 * @param {TokenUsageResetScope} scope 重置范围
 */
export const resetTokenUsage = (id: number, scope: TokenUsageResetScope) => {
  return request.post<User>(`/auth/users/${id}/token-usage/reset`, { scope })
}
