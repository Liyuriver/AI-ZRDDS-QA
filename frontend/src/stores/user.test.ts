import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useUserStore } from './user'

describe('user store', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    setActivePinia(createPinia())
  })

  it('logs in with the default Mock account and persists the session', async () => {
    const store = useUserStore()

    await store.login({ username: 'demo', password: 'demo123' }, true)

    expect(store.isAuthenticated).toBe(true)
    expect(store.currentUser?.displayName).toBe('演示用户')
    expect(localStorage.getItem('zrdss_qa_auth_session')).toBeTruthy()

    store.logout()
    expect(store.isAuthenticated).toBe(false)
  })
})
