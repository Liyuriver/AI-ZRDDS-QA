import type { AuthSession, LoginRequest, RegisterRequest, User } from '@/types/user'
import { readJson, writeJson } from '@/utils/storage'

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
  if (accounts.length) return accounts
  const demo: MockAccount = {
    user: {
      id: 'mock-user-demo',
      username: 'demo',
      displayName: '演示用户',
      email: 'demo@example.com',
    },
    passwordHash: await hashPassword('demo123'),
  }
  writeJson(MOCK_ACCOUNTS_KEY, [demo])
  return [demo]
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
