import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  login as apiLogin,
  register as apiRegister,
  updateAvatar as apiUpdateAvatar,
  updatePassword as apiUpdatePassword,
  updateProfile as apiUpdateProfile,
} from '@/api/user'
import type { LoginRequest, RegisterRequest, User } from '@/types/user'
import { clearAuthSession, readAuthSession, writeAuthSession } from '@/utils/auth'
import { getErrorMessage } from '@/utils/error'

export const useUserStore = defineStore('user', () => {
  const currentUser = ref<User | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const isAuthenticated = computed(() => Boolean(currentUser.value))

  function restoreSession(): void {
    currentUser.value = readAuthSession()?.user ?? null
  }

  async function login(payload: LoginRequest, remember: boolean): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const session = await apiLogin(payload)
      writeAuthSession(session, remember)
      currentUser.value = session.user
    } catch (reason) {
      error.value = getErrorMessage(reason, '操作失败，请稍后重试')
      throw reason
    } finally {
      loading.value = false
    }
  }

  async function register(payload: RegisterRequest): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const session = await apiRegister(payload)
      writeAuthSession(session, true)
      currentUser.value = session.user
    } catch (reason) {
      error.value = getErrorMessage(reason, '操作失败，请稍后重试')
      throw reason
    } finally {
      loading.value = false
    }
  }

  async function updateProfile(payload: {
    username: string
    email: string
    currentPassword: string
  }): Promise<void> {
    const user = await apiUpdateProfile(payload)
    const session = readAuthSession()
    if (session)
      writeAuthSession({ ...session, user }, Boolean(localStorage.getItem('zrdss_qa_auth_session')))
    currentUser.value = user
  }

  async function updatePassword(payload: {
    currentPassword: string
    newPassword: string
  }): Promise<void> {
    await apiUpdatePassword(payload)
  }

  async function updateAvatar(dataUrl: string): Promise<void> {
    const user = await apiUpdateAvatar(dataUrl)
    const session = readAuthSession()
    if (session)
      writeAuthSession({ ...session, user }, Boolean(localStorage.getItem('zrdss_qa_auth_session')))
    currentUser.value = user
  }

  function logout(): void {
    clearAuthSession()
    currentUser.value = null
    error.value = null
  }

  return {
    currentUser,
    loading,
    error,
    isAuthenticated,
    restoreSession,
    login,
    register,
    updateProfile,
    updatePassword,
    updateAvatar,
    logout,
  }
})
