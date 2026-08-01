/** 用户身份验证与额度控制 Pinia 状态管理模块 */

import { defineStore } from 'pinia'
import { login, getMe, logout } from '../api/auth'
import type { LoginForm, User } from '../types'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  // 当前登录的用户信息对象
  const user = ref<User | null>(null)
  // 本地持久化的 Access Token
  const token = ref<string | null>(localStorage.getItem('token'))
  // 计算属性：是否处于登录状态
  const isLoggedIn = computed(() => !!token.value)
  // 计算属性：是否为管理员角色
  const isAdmin = computed(() => user.value?.role === 'admin')
  
  /** 执行用户登录 */
  const loginAction = async (data: LoginForm) => {
    const res = await login(data)
    token.value = res.data.access_token
    user.value = res.data.user
    localStorage.setItem('token', res.data.access_token)
    localStorage.setItem('refresh_token', res.data.refresh_token)
  }

  /** 执行退出登录 */
  const logoutAction = () => {
    const refreshToken = localStorage.getItem('refresh_token')
    user.value = null
    token.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('refresh_token')
    if (refreshToken) void logout(refreshToken).catch(() => undefined)
  }

  /** 重新获取最新用户信息及当前 Token 消费进度 */
  const fetchUser = async () => {
    if (!token.value) return
    try {
      const res = await getMe()
      user.value = res.data
    } catch (e) {
      logoutAction()
    }
  }

  return {
    user,
    token,
    isLoggedIn,
    isAdmin,
    login: loginAction,
    logout: logoutAction,
    fetchUser
  }
})
