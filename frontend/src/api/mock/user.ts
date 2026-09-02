import type { AuthSession, LoginRequest, RegisterRequest, User } from '@/types/user'
import { readJson, writeJson } from '@/utils/storage'
import { readAuthSession } from '@/utils/auth'

interface MockAccount {
  user: User
  passwordHash: string
}
const MOCK_ACCOUNTS_KEY = 'zrdss_qa_mock_accounts'

const wait = () => new Promise<void>((resolve) => window.setTimeout(resolve, 220))

async function hashPassword(password: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(password))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

async function getAccounts(): Promise<MockAccount[]> {
  const accounts = readJson<MockAccount[]>(MOCK_ACCOUNTS_KEY, [])
  const demo: MockAccount = {
    user: {
      id: 'mock-user-demo',
      username: '123',
      displayName: '演示用户',
      email: '123@example.com',
    },
    passwordHash: await hashPassword('87654321'),
  }
  const existingDemo = accounts.findIndex((item) => item.user.id === demo.user.id)
  if (existingDemo >= 0) accounts[existingDemo] = demo
  else accounts.unshift(demo)
  writeJson(MOCK_ACCOUNTS_KEY, accounts)
  return accounts
}

const createSession = (user: User): AuthSession => ({ token: `mock-${crypto.randomUUID()}`, user })

export async function mockLogin(payload: LoginRequest): Promise<AuthSession> {
  await wait()
  const accounts = await getAccounts()
  const passwordHash = await hashPassword(payload.password)
  const account = accounts.find(
    (item) =>
      item.user.username.toLowerCase() === payload.username.trim().toLowerCase() &&
      item.passwordHash === passwordHash,
  )
  if (!account) throw new Error('用户名或密码错误')
  return createSession(account.user)
}

export async function mockRegister(payload: RegisterRequest): Promise<AuthSession> {
  await wait()
  const accounts = await getAccounts()
  const username = payload.username.trim()
  if (accounts.some((item) => item.user.username.toLowerCase() === username.toLowerCase()))
    throw new Error('该用户名已存在')
  const user: User = {
    id: crypto.randomUUID(),
    username,
    displayName: username,
    email: payload.email,
  }
  accounts.push({ user, passwordHash: await hashPassword(payload.password) })
  writeJson(MOCK_ACCOUNTS_KEY, accounts)
  return createSession(user)
}

export async function mockUpdateProfile(payload: {
  username: string
  email: string
  currentPassword: string
}): Promise<User> {
  const accounts = await getAccounts()
  const userId = readAuthSession()?.user.id
  const account = accounts.find((item) => item.user.id === userId)
  if (!account || account.passwordHash !== (await hashPassword(payload.currentPassword)))
    throw new Error('当前密码错误')
  if (
    accounts.some(
      (item) =>
        item.user.id !== userId &&
        item.user.username.toLowerCase() === payload.username.trim().toLowerCase(),
    )
  )
    throw new Error('该用户名已存在')
  account.user = {
    ...account.user,
    username: payload.username.trim(),
    displayName: payload.username.trim(),
    email: payload.email.trim(),
  }
  writeJson(MOCK_ACCOUNTS_KEY, accounts)
  return account.user
}

export async function mockUpdatePassword(payload: {
  currentPassword: string
  newPassword: string
}): Promise<void> {
  const accounts = await getAccounts()
  const userId = readAuthSession()?.user.id
  const account = accounts.find((item) => item.user.id === userId)
  if (!account || account.passwordHash !== (await hashPassword(payload.currentPassword)))
    throw new Error('当前密码错误')
  account.passwordHash = await hashPassword(payload.newPassword)
  writeJson(MOCK_ACCOUNTS_KEY, accounts)
}

export async function mockUpdateAvatar(dataUrl: string): Promise<User> {
  const accounts = await getAccounts()
  const userId = readAuthSession()?.user.id
  const account = accounts.find((item) => item.user.id === userId)
  if (!account) throw new Error('用户不存在')
  account.user = { ...account.user, avatarUrl: dataUrl }
  writeJson(MOCK_ACCOUNTS_KEY, accounts)
  return account.user
}
