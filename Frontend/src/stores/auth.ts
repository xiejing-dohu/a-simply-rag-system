import { defineStore } from 'pinia'
import { login, getMe, logout } from '../api/auth'
import type { LoginForm, User } from '../types'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(localStorage.getItem('token'))
  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  
  const loginAction = async (data: LoginForm) => {
    const res = await login(data)
    token.value = res.data.access_token
    user.value = res.data.user
    localStorage.setItem('token', res.data.access_token)
    localStorage.setItem('refresh_token', res.data.refresh_token)
  }

  const logoutAction = () => {
    const refreshToken = localStorage.getItem('refresh_token')
    user.value = null
    token.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('refresh_token')
    if (refreshToken) void logout(refreshToken).catch(() => undefined)
  }

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
