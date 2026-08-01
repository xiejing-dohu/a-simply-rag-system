/** 前端 Vue Router 路由配置与全局导航守卫模块 */

import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue')
    },
    {
      path: '/',
      component: () => import('../components/AppLayout.vue'),
      redirect: '/chat',
      children: [
        {
          path: 'chat',
          name: 'chat',
          component: () => import('../views/ChatView.vue'),
          meta: { requiresAuth: true }
        },
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('../views/KnowledgeView.vue'),
          meta: { requiresAuth: true }
        },
        {
          path: 'admin',
          name: 'admin',
          component: () => import('../views/AdminView.vue'),
          meta: { requiresAuth: true, requiresAdmin: true }
        }
      ]
    }
  ]
})

// 全局路由守卫：校验登录权限与管理员角色
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  
  if (to.meta.requiresAuth && !authStore.isLoggedIn) {
    next({ name: 'login' })
  } else if (to.meta.requiresAdmin && !authStore.isAdmin) {
    next({ name: 'chat' }) // 无管理员权限时重定向至聊天页
  } else {
    next()
  }
})

export default router
