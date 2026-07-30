<template>
  <el-popover placement="bottom-end" :width="380" trigger="click" @show="authStore.fetchUser">
    <template #reference>
      <el-button class="usage-trigger" plain size="small">
        <el-icon><DataAnalysis /></el-icon>
        我的 Token
      </el-button>
    </template>

    <div v-if="user" class="usage-panel">
      <div class="panel-header">
        <div>
          <h3>Token 用量</h3>
          <p>累计 {{ formatTokens(user.total_tokens_used) }} Token</p>
        </div>
        <el-tag effect="dark" type="info">{{ overallMode }}</el-tag>
      </div>

      <div class="lifetime-grid">
        <div>
          <span>累计输入</span>
          <strong>{{ formatTokens(user.input_tokens_used) }}</strong>
        </div>
        <div>
          <span>累计输出</span>
          <strong>{{ formatTokens(user.output_tokens_used) }}</strong>
        </div>
      </div>

      <section class="window-section">
        <div class="window-header">
          <div>
            <h4>5 小时用量</h4>
            <span>{{ formatQuota(user.five_hour_tokens_used, user.five_hour_token_limit) }}</span>
          </div>
          <el-tag :type="user.five_hour_token_limit === null ? 'success' : 'warning'" size="small">
            {{ user.five_hour_token_limit === null ? '无限模式' : '限额模式' }}
          </el-tag>
        </div>
        <el-progress
          v-if="user.five_hour_token_limit !== null"
          :percentage="quotaPercent(user.five_hour_tokens_used, user.five_hour_token_limit)"
          :status="quotaStatus(user.five_hour_tokens_used, user.five_hour_token_limit)"
          :stroke-width="8"
        />
        <p>重置时间：{{ formatTime(user.five_hour_resets_at) }}</p>
      </section>

      <section class="window-section">
        <div class="window-header">
          <div>
            <h4>周用量（7 天）</h4>
            <span>{{ formatQuota(user.weekly_tokens_used, user.weekly_token_limit) }}</span>
          </div>
          <el-tag :type="user.weekly_token_limit === null ? 'success' : 'warning'" size="small">
            {{ user.weekly_token_limit === null ? '无限模式' : '限额模式' }}
          </el-tag>
        </div>
        <el-progress
          v-if="user.weekly_token_limit !== null"
          :percentage="quotaPercent(user.weekly_tokens_used, user.weekly_token_limit)"
          :status="quotaStatus(user.weekly_tokens_used, user.weekly_token_limit)"
          :stroke-width="8"
        />
        <p>重置时间：{{ formatTime(user.weekly_resets_at) }}</p>
      </section>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { DataAnalysis } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const user = computed(() => authStore.user)
const tokenFormatter = new Intl.NumberFormat('zh-CN')

const formatTokens = (value: number) => tokenFormatter.format(value || 0)
const formatQuota = (used: number, limit: number | null) => {
  return limit === null
    ? `${formatTokens(used)} / 无限`
    : `${formatTokens(used)} / ${formatTokens(limit)}`
}
const formatTime = (value: string) => new Date(value).toLocaleString()
const quotaPercent = (used: number, limit: number) => {
  if (limit <= 0) return 100
  return Math.min(100, Math.round((used / limit) * 100))
}
const quotaStatus = (used: number, limit: number) => used >= limit ? 'exception' : undefined
const overallMode = computed(() => {
  if (!user.value) return ''
  return user.value.five_hour_token_limit === null && user.value.weekly_token_limit === null
    ? '全部无限'
    : '管理员限额'
})
</script>

<style scoped>
.usage-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.usage-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-header,
.window-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.panel-header h3,
.panel-header p,
.window-header h4,
.window-section p {
  margin: 0;
}

.panel-header p,
.window-section p,
.window-header span,
.lifetime-grid span {
  color: var(--text-secondary);
  font-size: 12px;
}

.panel-header p,
.window-section p {
  margin-top: 4px;
}

.lifetime-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.lifetime-grid > div,
.window-section {
  padding: 14px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
}

.lifetime-grid span,
.lifetime-grid strong {
  display: block;
}

.lifetime-grid strong {
  margin-top: 5px;
  font-size: 18px;
}

.window-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>
