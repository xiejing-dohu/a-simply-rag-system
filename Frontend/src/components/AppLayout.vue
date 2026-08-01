<!-- 全局应用顶层布局组件：顶部导航栏 + 侧边与中心内容区 -->
<template>
  <div class="app-layout">
    <nav class="navbar glass-card">
      <div class="nav-left">
        <div class="logo text-gradient">
          <el-icon><Monitor /></el-icon>
          智能 RAG 系统
        </div>
        <div class="nav-links">
          <router-link to="/chat" class="nav-link" active-class="active">聊天</router-link>
          <router-link to="/knowledge" class="nav-link" active-class="active">知识库</router-link>
          <router-link v-if="authStore.isAdmin" to="/admin" class="nav-link" active-class="active">管理员</router-link>
        </div>
      </div>
      <div class="nav-right">
        <!-- Token 消费面板 -->
        <TokenUsagePopover />
        <div class="user-info">
          <el-avatar :size="32" src="https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png" />
          <span class="username">{{ authStore.user?.username || 'User' }}</span>
        </div>
        <el-button type="danger" plain size="small" @click="handleLogout">退出登录</el-button>
      </div>
    </nav>
    <main class="main-content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from '../stores/auth'
import { useRouter } from 'vue-router'
import { onMounted } from 'vue'
import { Monitor } from '@element-plus/icons-vue'
import TokenUsagePopover from './TokenUsagePopover.vue'

const authStore = useAuthStore()
const router = useRouter()

// 组件挂载时拉取最新用户信息及 Token 限额
onMounted(() => authStore.fetchUser())

/** 退出登录按钮句柄 */
const handleLogout = () => {
  authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-layout {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.navbar {
  height: 60px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-radius: 0;
  border-left: none;
  border-right: none;
  border-top: none;
  z-index: 100;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 40px;
}

.logo {
  font-size: 20px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-links {
  display: flex;
  gap: 20px;
}

.nav-link {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: var(--transition-fast);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
}

.nav-link:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.nav-link.active {
  color: var(--color-primary-strong);
  background: var(--bg-active);
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 24px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.username {
  font-size: 14px;
  color: var(--text-primary);
}

.main-content {
  flex: 1;
  overflow: hidden;
  position: relative;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
