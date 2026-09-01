import type { AuthSession } from '@/types/user'

export const AUTH_SESSION_KEY = 'zrdss_qa_auth_session'

function parseSession(value: string | null): AuthSession | null {
  if (!value) return null
  try {
    return JSON.parse(value) as AuthSession
  } catch {
    return null
  }
}

export function readAuthSession(): AuthSession | null {
  return (
    parseSession(sessionStorage.getItem(AUTH_SESSION_KEY)) ||
    parseSession(localStorage.getItem(AUTH_SESSION_KEY))
  )
}

export function writeAuthSession(session: AuthSession, remember: boolean): void {
  clearAuthSession()
  const target = remember ? localStorage : sessionStorage
  target.setItem(AUTH_SESSION_KEY, JSON.stringify(session))
}

export function clearAuthSession(): void {
  localStorage.removeItem(AUTH_SESSION_KEY)
  sessionStorage.removeItem(AUTH_SESSION_KEY)
}

export function hasAuthSession(): boolean {
  return Boolean(readAuthSession()?.token)
}
