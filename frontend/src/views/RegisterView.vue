<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import AuthLayout from '@/components/layout/AuthLayout.vue'
import { appConfig } from '@/config/app'
import { useUserStore } from '@/stores/user'

interface RegisterForm {
  username: string
  email: string
  password: string
  confirmPassword: string
}

const formRef = ref<FormInstance>()
const router = useRouter()
const userStore = useUserStore()
const form = reactive<RegisterForm>({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
})

const rules: FormRules<RegisterForm> = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '用户名长度应为 3 到 32 个字符', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
  ...(appConfig.useMock
    ? {
        password: [
          { required: true, message: '请输入密码', trigger: 'blur' },
          { min: 6, message: '密码长度不能少于 6 位', trigger: 'blur' },
        ],
        confirmPassword: [
          { required: true, message: '请再次输入密码', trigger: 'blur' },
          {
            validator: (_rule, value, callback) => {
              if (value !== form.password) {
                callback(new Error('两次输入的密码不一致'))
                return
              }
              callback()
            },
            trigger: 'blur',
          },
        ],
      }
    : {}),
}

async function handleSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)

  if (valid) {
    try {
      await userStore.register({
        username: form.username,
        email: form.email,
        password: form.password,
      })
      ElMessage.success('注册成功')
      await router.replace('/chat')
    } catch {
      ElMessage.error(userStore.error || '注册失败，请稍后重试')
    }
  }
}
</script>

<template>
  <AuthLayout>
    <header class="auth-form__header">
      <p>创建账号</p>
      <h2>加入 AI-ZRDDS-QA</h2>
      <span>注册后即可保存会话并查询 ZRDDS 知识库</span>
    </header>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large">
      <el-form-item label="用户名" prop="username">
        <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名" />
      </el-form-item>
      <el-form-item label="邮箱" prop="email">
        <el-input v-model="form.email" autocomplete="email" placeholder="请输入邮箱" />
      </el-form-item>
      <el-form-item v-if="appConfig.useMock" label="密码" prop="password">
        <el-input
          v-model="form.password"
          autocomplete="new-password"
          placeholder="请输入至少 6 位密码"
          show-password
          type="password"
        />
      </el-form-item>
      <el-form-item v-if="appConfig.useMock" label="确认密码" prop="confirmPassword">
        <el-input
          v-model="form.confirmPassword"
          autocomplete="new-password"
          placeholder="请再次输入密码"
          show-password
          type="password"
          @keyup.enter="handleSubmit"
        />
      </el-form-item>

      <div v-if="!appConfig.useMock" class="auth-form__backend-note">
        当前后端用户模型不包含密码字段，注册后将直接进入系统。
      </div>

      <el-button
        class="auth-form__submit"
        :loading="userStore.loading"
        type="primary"
        @click="handleSubmit"
      >
        创建账号
      </el-button>
    </el-form>

    <p class="auth-form__footer">
      已有账号？
      <RouterLink to="/login">返回登录</RouterLink>
    </p>
  </AuthLayout>
</template>

<style scoped>
.auth-form__header {
  margin-bottom: 30px;
}

.auth-form__header p {
  margin: 0 0 8px;
  color: var(--color-primary);
  font-size: 14px;
  font-weight: 700;
}

.auth-form__header h2 {
  margin: 0;
  color: var(--color-text);
  font-size: 30px;
  letter-spacing: -0.03em;
}

.auth-form__header span {
  display: block;
  margin-top: 12px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.auth-form__submit {
  width: 100%;
  margin-top: 6px;
}

.auth-form__backend-note {
  margin: 2px 0 16px;
  padding: 10px 12px;
  border-radius: 8px;
  color: #52647f;
  background: #f8fafc;
  font-size: 12px;
}

.auth-form__footer {
  margin: 24px 0 0;
  color: var(--color-text-secondary);
  text-align: center;
  font-size: 14px;
}

.auth-form__footer a {
  color: var(--color-primary);
  font-weight: 700;
  text-decoration: none;
}
</style>
