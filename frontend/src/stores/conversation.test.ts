import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useConversationStore } from './conversation'

describe('conversation store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('creates, selects and reloads a conversation', async () => {
    const store = useConversationStore()
    const created = await store.createConversation('user-1')

    expect(store.items).toHaveLength(1)
    expect(store.currentId).toBe(created.id)
    await store.nameConversationFromQuery(created.id, '如何排查 ZRDDS 通信失败？')
    expect(store.currentConversation?.title).toBe('如何排查 ZRDDS 通信失败？')
    await store.renameConversation(created.id, '手动修改的标题')
    expect(store.currentConversation?.title).toBe('手动修改的标题')

    store.reset()
    await store.loadConversations('user-1')

    expect(store.currentConversation?.id).toBe(created.id)
    expect(store.currentConversation?.title).toBe('手动修改的标题')

    await store.deleteConversation(created.id, 'user-1')
    expect(store.items).toHaveLength(0)
    expect(store.currentId).toBeNull()
  })
})
