<template>
  <div class="login-container">
    <div class="login-box glass-card fade-in">
      <div class="header">
        <h1 class="text-gradient">智能 RAG 系统</h1>
        <p>登入您的账户</p>
      </div>

      <el-form :model="form" :rules="rules" ref="formRef" class="login-form">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" prefix-icon="User" size="large" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" prefix-icon="Lock" show-password size="large" />
        </el-form-item>
        <el-button type="primary" class="submit-btn" size="large" :loading="loading" @click="handleLogin">
          登录
        </el-button>
      </el-form>

      <div class="footer">
        还没有账户？ <a href="#" @click.prevent="showRegister">立即注册</a>
      </div>
    </div>

    <el-dialog
      v-model="registerVisible"
      title="注册普通用户"
      width="420px"
      :close-on-click-modal="false"
      @closed="resetRegisterForm"
    >
      <el-form
        ref="registerFormRef"
        :model="registerForm"
        :rules="registerRules"
        label-position="top"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="registerForm.username" placeholder="2–50 个字符" maxlength="50" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="registerForm.email" placeholder="name@example.com" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="registerForm.password"
            type="password"
            placeholder="至少 6 个字符"
            show-password
          />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="registerForm.confirmPassword"
            type="password"
            placeholder="再次输入密码"
            show-password
            @keyup.enter="handleRegister"
          />
        </el-form-item>
        <p class="register-tip">注册账户默认为普通用户，不具备管理权限。</p>
      </el-form>
      <template #footer>
        <el-button @click="registerVisible = false">取消</el-button>
        <el-button type="primary" :loading="registerLoading" @click="handleRegister">
          注册
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { register as registerUser } from '../api/auth'
import { ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'
import { isAxiosError } from 'axios'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const registerVisible = ref(false)
const registerLoading = ref(false)
const registerFormRef = ref<FormInstance>()

const form = reactive({
  username: '',
  password: ''
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const registerForm = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: ''
})

const validatePasswordConfirmation = (
  _rule: unknown,
  value: string,
  callback: (error?: Error) => void
) => {
  if (!value) callback(new Error('请再次输入密码'))
  else if (value !== registerForm.password) callback(new Error('两次输入的密码不一致'))
  else callback()
}

const registerRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 50, message: '用户名长度应为 2–50 个字符', trigger: 'blur' }
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效邮箱', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少需要 6 个字符', trigger: 'blur' }
  ],
  confirmPassword: [{ validator: validatePasswordConfirmation, trigger: 'blur' }]
}

const handleLogin = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        await authStore.login(form)
        ElMessage.success('登录成功')
        router.push('/chat')
      } catch (error) {
        const detail = isAxiosError(error) ? error.response?.data?.detail : null
        ElMessage.error(typeof detail === 'string' ? detail : '登录失败，请稍后重试')
      } finally {
        loading.value = false
      }
    }
  })
}

const showRegister = () => {
  registerVisible.value = true
}

const resetRegisterForm = () => {
  registerFormRef.value?.resetFields()
  registerForm.username = ''
  registerForm.email = ''
  registerForm.password = ''
  registerForm.confirmPassword = ''
}

const handleRegister = async () => {
  if (!registerFormRef.value || registerLoading.value) return
  try {
    await registerFormRef.value.validate()
  } catch {
    return
  }

  registerLoading.value = true
  try {
    await registerUser({
      username: registerForm.username.trim(),
      email: registerForm.email.trim(),
      password: registerForm.password
    })
    form.username = registerForm.username.trim()
    form.password = ''
    registerVisible.value = false
    ElMessage.success('注册成功，请使用新账户登录')
  } catch (error) {
    const detail = isAxiosError(error) ? error.response?.data?.detail : null
    ElMessage.error(typeof detail === 'string' ? detail : '注册失败，请稍后重试')
  } finally {
    registerLoading.value = false
  }
}
</script>

<style scoped>
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle at top right, rgba(118, 75, 162, 0.2), transparent 40%),
              radial-gradient(circle at bottom left, rgba(102, 126, 234, 0.2), transparent 40%),
              var(--bg-dark);
}

.login-box {
  width: 400px;
  padding: 40px;
  box-shadow: var(--shadow-lg);
}

.header {
  text-align: center;
  margin-bottom: 32px;
}

.header h1 {
  font-size: 28px;
  margin-bottom: 8px;
}

.header p {
  color: var(--text-secondary);
  font-size: 14px;
}

.submit-btn {
  width: 100%;
  margin-top: 16px;
  font-size: 16px;
  font-weight: 500;
}

.footer {
  margin-top: 24px;
  text-align: center;
  font-size: 14px;
  color: var(--text-secondary);
}

.footer a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
  transition: var(--transition-fast);
}

.footer a:hover {
  opacity: 0.8;
}

.register-tip {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}
</style>
