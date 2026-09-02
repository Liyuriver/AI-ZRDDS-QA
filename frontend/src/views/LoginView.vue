<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AuthLayout from '@/components/layout/AuthLayout.vue'
import { useUserStore } from '@/stores/user'

interface LoginForm {
  username: string
  password: string
  email: string
  remember: boolean
}

const formRef = ref<FormInstance>()
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const form = reactive<LoginForm>({
  username: '',
  password: '',
  email: '',
  remember: false,
})

const rules: FormRules<LoginForm> = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)

  if (valid) {
    try {
      await userStore.login(
        { username: form.username, password: form.password, email: form.email },
        form.remember,
      )
      ElMessage.success('登录成功')
      const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/chat'
      await router.replace(redirect)
    } catch {
      ElMessage.error(userStore.error || '登录失败，请稍后重试')
    }
  }
}
</script>

<template>
  <AuthLayout>
    <header class="auth-form__header">
      <p>欢迎回来</p>
      <h2>登录 AI-ZRDDS-QA</h2>
      <span>使用项目账号继续访问知识问答系统</span>
    </header>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large">
      <el-form-item label="用户名" prop="username">
        <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名" />
      </el-form-item>
      <el-form-item label="密码" prop="password">
        <el-input
          v-model="form.password"
          autocomplete="current-password"
          placeholder="请输入密码"
          show-password
          type="password"
          @keyup.enter="handleSubmit"
        />
      </el-form-item>

      <div class="auth-form__options">
        <el-checkbox v-model="form.remember">记住登录状态</el-checkbox>
        <span>忘记密码请联系项目管理员</span>
      </div>

      <div class="auth-form__demo">
        {{ '演示环境账号：123 / 87654321；真实环境请使用已注册账号' }}
      </div>

      <el-button
        class="auth-form__submit"
        :loading="userStore.loading"
        type="primary"
        @click="handleSubmit"
      >
        登录
      </el-button>
    </el-form>

    <p class="auth-form__footer">
      还没有账号？
      <RouterLink to="/register">创建账号</RouterLink>
    </p>
  </AuthLayout>
</template>

<style scoped>
.auth-form__header {
  margin-bottom: 34px;
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

.auth-form__options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 24px;
  color: #98a2b3;
  font-size: 12px;
}

.auth-form__submit {
  width: 100%;
}

.auth-form__demo {
  margin: -10px 0 18px;
  padding: 9px 12px;
  border-radius: 8px;
  color: #52709d;
  background: #f2f7ff;
  font-size: 12px;
}

.auth-form__footer {
  margin: 28px 0 0;
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
