import { mockLogin, mockRegister } from '@/api/mock/user'
import { appConfig } from '@/config/app'
import type { AuthSession, LoginRequest, RegisterRequest, User } from '@/types/user'
import { http } from './http'

interface BackendUser {
  id: string
  username: string
  email: string
  created_at: string
  updated_at: string
}

const mapUser = (user: BackendUser): User => ({
  id: user.id,
  username: user.username,
  displayName: user.username,
  email: user.email,
})

const createSession = (user: User): AuthSession => ({ token: `backend-user-${user.id}`, user })

export async function login(payload: LoginRequest): Promise<AuthSession> {
  if (appConfig.useMock) return mockLogin(payload)
  const { data } = await http.get<BackendUser[]>('/users')
  const user = data.find(
    (item) =>
      item.username.toLowerCase() === payload.username.trim().toLowerCase() &&
      item.email.toLowerCase() === payload.email?.trim().toLowerCase(),
  )
  if (!user) throw new Error('用户名或邮箱不匹配')
  return createSession(mapUser(user))
}

export async function register(payload: RegisterRequest): Promise<AuthSession> {
  if (appConfig.useMock) return mockRegister(payload)
  const { data } = await http.post<BackendUser>('/users', {
    username: payload.username.trim(),
    email: payload.email.trim(),
  })
  return createSession(mapUser(data))
}
