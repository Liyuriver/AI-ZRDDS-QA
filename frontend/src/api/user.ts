import {
  mockLogin,
  mockRegister,
  mockUpdateAvatar,
  mockUpdatePassword,
  mockUpdateProfile,
} from '@/api/mock/user'
import { appConfig } from '@/config/app'
import type { AuthSession, LoginRequest, RegisterRequest, User } from '@/types/user'
import { http } from './http'

interface BackendUser {
  id: string
  username: string
  email: string
  created_at: string
  updated_at: string
  avatar_url?: string | null
}

const mapUser = (user: BackendUser): User => ({
  id: user.id,
  username: user.username,
  displayName: user.username,
  email: user.email,
  avatarUrl: user.avatar_url || undefined,
})

export async function login(payload: LoginRequest): Promise<AuthSession> {
  if (appConfig.useMock) return mockLogin(payload)
  const { data } = await http.post<{ token: string; user: BackendUser }>('/auth/login', {
    username: payload.username.trim(),
    password: payload.password,
  })
  return { token: data.token, user: mapUser(data.user) }
}

export async function register(payload: RegisterRequest): Promise<AuthSession> {
  if (appConfig.useMock) return mockRegister(payload)
  const { data } = await http.post<{ token: string; user: BackendUser }>('/auth/register', {
    username: payload.username.trim(),
    email: payload.email.trim(),
    password: payload.password,
  })
  return { token: data.token, user: mapUser(data.user) }
}

export async function updateProfile(payload: {
  username: string
  email: string
  currentPassword: string
}): Promise<User> {
  if (appConfig.useMock) return mockUpdateProfile(payload)
  const { data } = await http.patch<BackendUser>('/auth/me', {
    username: payload.username.trim(),
    email: payload.email.trim(),
    current_password: payload.currentPassword,
  })
  return mapUser(data)
}

export async function updatePassword(payload: {
  currentPassword: string
  newPassword: string
}): Promise<void> {
  if (appConfig.useMock) return mockUpdatePassword(payload)
  await http.patch('/auth/password', {
    current_password: payload.currentPassword,
    new_password: payload.newPassword,
  })
}

export async function updateAvatar(dataUrl: string): Promise<User> {
  if (appConfig.useMock) return mockUpdateAvatar(dataUrl)
  const { data } = await http.put<BackendUser>('/auth/avatar', { data_url: dataUrl })
  return mapUser(data)
}
