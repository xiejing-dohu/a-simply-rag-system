<!-- 管理员控制台页面组件：提供账号管理、角色与激活状态切换、Token 限额配置及手动一键重置 -->
<template>
  <div class="admin-container">
    <div class="header">
      <h1 class="text-gradient">用户管理</h1>
    </div>

    <!-- 用户列表表格 -->
    <div class="table-wrapper glass-card slide-up">
      <el-table :data="users" style="width: 100%" class="custom-table">
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="email" label="邮箱" />
        <el-table-column prop="role" label="角色">
          <template #default="scope">
            <el-tag :type="scope.row.role === 'admin' ? 'danger' : 'info'" effect="dark">
              {{ scope.row.is_root_admin ? '系统管理员' : scope.row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态">
          <template #default="scope">
            <el-switch
              v-model="scope.row.is_active"
              :disabled="scope.row.is_root_admin"
              @change="handleStatusChange(scope.row.id, $event)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间">
          <template #default="scope">
            {{ new Date(scope.row.created_at).toLocaleString() }}
          </template>
        </el-table-column>
        <el-table-column label="Token 用量" min-width="280">
          <template #default="scope">
            <div class="usage-cell">
              <span>累计：{{ formatTokens(scope.row.total_tokens_used) }}</span>
              <small>输入 {{ formatTokens(scope.row.input_tokens_used) }} / 输出 {{ formatTokens(scope.row.output_tokens_used) }}</small>
              <small>5 小时：{{ formatQuota(scope.row.five_hour_tokens_used, scope.row.five_hour_token_limit) }}</small>
              <small>本周：{{ formatQuota(scope.row.weekly_tokens_used, scope.row.weekly_token_limit) }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230">
          <template #default="scope">
            <div class="action-buttons">
              <el-dropdown
                v-if="authStore.user?.is_root_admin && !scope.row.is_root_admin"
                trigger="click"
                @command="(cmd: string) => handleRoleChange(scope.row.id, cmd)"
              >
                <el-button type="primary" link>修改角色<el-icon class="el-icon--right"><arrow-down /></el-icon></el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="admin">管理员</el-dropdown-item>
                    <el-dropdown-item command="employee">普通用户</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <span v-else class="locked-role">
                {{ scope.row.is_root_admin ? '身份不可修改' : '无身份修改权限' }}
              </span>
              <el-button type="primary" link @click="openQuotaDialog(scope.row)">Token 配额</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Token 额度编辑与重置弹窗 -->
    <el-dialog v-model="quotaVisible" :title="`Token 配额 · ${quotaUser?.username || ''}`" width="560px">
      <div v-if="quotaUser" class="quota-dialog">
        <div class="usage-overview">
          <div><span>累计 Token</span><strong>{{ formatTokens(quotaUser.total_tokens_used) }}</strong></div>
          <div><span>输入 / 输出</span><strong>{{ formatTokens(quotaUser.input_tokens_used) }} / {{ formatTokens(quotaUser.output_tokens_used) }}</strong></div>
        </div>

        <div class="quota-section">
          <div class="quota-heading">
            <div>
              <h3>5 小时限制</h3>
              <p>已用 {{ formatTokens(quotaUser.five_hour_tokens_used) }}，{{ formatResetTime(quotaUser.five_hour_resets_at) }}重置</p>
            </div>
            <el-button type="warning" plain size="small" @click="handleResetUsage('five_hour')">立即重置</el-button>
          </div>
          <el-switch v-model="fiveHourUnlimited" active-text="无上限" inactive-text="具体数值" />
          <el-input-number
            v-if="!fiveHourUnlimited"
            v-model="quotaForm.five_hour_token_limit"
            :min="1"
            :step="1000"
            controls-position="right"
          />
        </div>

        <div class="quota-section">
          <div class="quota-heading">
            <div>
              <h3>周限制（7 天）</h3>
              <p>已用 {{ formatTokens(quotaUser.weekly_tokens_used) }}，{{ formatResetTime(quotaUser.weekly_resets_at) }}重置</p>
            </div>
            <el-button type="warning" plain size="small" @click="handleResetUsage('weekly')">立即重置</el-button>
          </div>
          <el-switch v-model="weeklyUnlimited" active-text="无上限" inactive-text="具体数值" />
          <el-input-number
            v-if="!weeklyUnlimited"
            v-model="quotaForm.weekly_token_limit"
            :min="1"
            :step="10000"
            controls-position="right"
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="quotaVisible = false">取消</el-button>
        <el-button type="primary" :loading="quotaSaving" @click="saveQuota">保存配额</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { getUsers, resetTokenUsage, updateUser } from '../api/auth'
import type { TokenUsageResetScope } from '../api/auth'
import type { User } from '../types'
import { ElMessage } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const users = ref<User[]>([])
const quotaVisible = ref(false)
const quotaSaving = ref(false)
const quotaUser = ref<User | null>(null)
const fiveHourUnlimited = ref(true)
const weeklyUnlimited = ref(true)
const quotaForm = reactive({
  five_hour_token_limit: 100000 as number | null,
  weekly_token_limit: 1000000 as number | null
})

const tokenFormatter = new Intl.NumberFormat('zh-CN')
const formatTokens = (value: number) => tokenFormatter.format(value || 0)
const formatQuota = (used: number, limit: number | null) => {
  return `${formatTokens(used)} / ${limit === null ? '无限' : formatTokens(limit)}`
}
const formatResetTime = (value: string) => new Date(value).toLocaleString()

const replaceUser = (updated: User) => {
  const index = users.value.findIndex(user => user.id === updated.id)
  if (index >= 0) users.value[index] = updated
  if (quotaUser.value?.id === updated.id) quotaUser.value = updated
}

/** 加载用户列表 */
const fetchUsers = async () => {
  try {
    const res = await getUsers()
    users.value = res.data
  } catch (e) {
    ElMessage.error('获取用户列表失败')
  }
}

onMounted(() => {
  fetchUsers()
})

/** 修改用户激活状态开关回调 */
const handleStatusChange = async (id: number, val: string | number | boolean) => {
  try {
    await updateUser(id, { is_active: Boolean(val) })
    ElMessage.success('状态已更新')
  } catch (e) {
    ElMessage.error('更新失败')
    fetchUsers()
  }
}

/** 修改用户角色回调 */
const handleRoleChange = async (id: number, role: string) => {
  try {
    await updateUser(id, { role: role as 'admin' | 'employee' })
    ElMessage.success('角色已更新')
    fetchUsers()
  } catch (e) {
    ElMessage.error('更新失败')
  }
}

/** 打开 Token 配额配置对话框 */
const openQuotaDialog = (user: User) => {
  quotaUser.value = user
  fiveHourUnlimited.value = user.five_hour_token_limit === null
  weeklyUnlimited.value = user.weekly_token_limit === null
  quotaForm.five_hour_token_limit = user.five_hour_token_limit ?? 100000
  quotaForm.weekly_token_limit = user.weekly_token_limit ?? 1000000
  quotaVisible.value = true
}

/** 保存更新后的 Token 配额限制 */
const saveQuota = async () => {
  if (!quotaUser.value) return
  quotaSaving.value = true
  try {
    const res = await updateUser(quotaUser.value.id, {
      five_hour_token_limit: fiveHourUnlimited.value ? null : quotaForm.five_hour_token_limit,
      weekly_token_limit: weeklyUnlimited.value ? null : quotaForm.weekly_token_limit
    })
    replaceUser(res.data)
    quotaVisible.value = false
    ElMessage.success('Token 配额已保存')
  } catch {
    ElMessage.error('Token 配额保存失败')
  } finally {
    quotaSaving.value = false
  }
}

/** 管理员重置指定用户的 Token 消耗 */
const handleResetUsage = async (scope: TokenUsageResetScope) => {
  if (!quotaUser.value) return
  try {
    const res = await resetTokenUsage(quotaUser.value.id, scope)
    replaceUser(res.data)
    ElMessage.success(scope === 'five_hour' ? '5 小时用量已重置' : '周用量已重置')
  } catch {
    ElMessage.error('Token 用量重置失败')
  }
}
</script>

<style scoped>
.admin-container {
  padding: 40px;
  height: 100%;
  overflow-y: auto;
}

.header {
  margin-bottom: 32px;
}

.header h1 {
  font-size: 24px;
  margin: 0;
}

.table-wrapper {
  padding: 24px;
}

.usage-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.usage-cell small,
.quota-heading p {
  color: var(--text-secondary);
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 12px;
}

.locked-role {
  color: var(--text-secondary);
  font-size: 12px;
}

.quota-dialog,
.quota-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.usage-overview {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.usage-overview > div,
.quota-section {
  padding: 16px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
}

.usage-overview span,
.usage-overview strong {
  display: block;
}

.usage-overview span {
  color: var(--text-secondary);
  font-size: 12px;
  margin-bottom: 6px;
}

.quota-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.quota-heading h3,
.quota-heading p {
  margin: 0;
}

.quota-heading p {
  margin-top: 5px;
  font-size: 12px;
}

::v-deep(.el-table) {
  background-color: transparent !important;
  --el-table-border-color: var(--border-color);
  --el-table-header-bg-color: rgba(255, 255, 255, 0.02);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.05);
}

::v-deep(.el-table th.el-table__cell),
::v-deep(.el-table tr) {
  background-color: transparent !important;
}

::v-deep(.el-table td.el-table__cell),
::v-deep(.el-table th.el-table__cell.is-leaf) {
  border-bottom: 1px solid var(--border-color);
}
</style>
