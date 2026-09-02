import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useChatStore } from './chat'

describe('chat store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('sends and reloads persisted Mock messages', async () => {
    const store = useChatStore()

    await store.sendMessage('conversation-1', 'user-1', '如何排查构建错误？')
    expect(store.messages).toHaveLength(2)
    expect(store.messages[1]?.role).toBe('assistant')
    expect(store.messages[1]?.citations).toHaveLength(2)

    store.reset()
    await store.loadMessages('conversation-1')
    expect(store.messages.map((item) => item.role)).toEqual(['user', 'assistant'])
  })

  it('marks a failed Mock request for retry', async () => {
    const store = useChatStore()

    await store.sendMessage('conversation-2', 'user-1', '/error')

    expect(store.messages[0]?.status).toBe('error')
    expect(store.error).toBe('Mock 请求失败，请点击重试')
    expect(store.messages[0]?.errorMessage).toBe('Mock 请求失败，请点击重试')

    await store.retryMessage(store.messages[0]!.id, 'user-1')
    expect(store.messages[0]?.status).toBe('success')
    expect(store.messages[0]?.errorMessage).toBeUndefined()
    expect(store.messages[1]?.role).toBe('assistant')
  })

  it('returns an explicit no-answer result without citations', async () => {
    const store = useChatStore()
    await store.sendMessage('conversation-3', 'user-1', '/no-answer')

    expect(store.messages[1]?.answerStatus).toBe('no_answer')
    expect(store.messages[1]?.citations).toEqual([])
  })

  it('does not append a late answer after switching conversations', async () => {
    const store = useChatStore()
    const pending = store.sendMessage('old-conversation', 'user-1', '旧会话问题')

    await store.loadMessages('new-conversation')
    await pending

    expect(store.messages.every((item) => item.conversationId === 'new-conversation')).toBe(true)
    expect(store.sending).toBe(false)
  })
})
