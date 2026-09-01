import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  createConversation as apiCreateConversation,
  deleteConversation as apiDeleteConversation,
  fetchConversations,
  updateConversationTitle,
} from '@/api/conversation'
import type { Conversation } from '@/types/conversation'
import { getErrorMessage } from '@/utils/error'

const selectionKey = (userId: string) => `zrdss_qa_current_conversation:${userId}`

export const useConversationStore = defineStore('conversation', () => {
  const items = ref<Conversation[]>([])
  const currentId = ref<string | null>(null)
  const loading = ref(false)
  const creating = ref(false)
  const error = ref<string | null>(null)
  const currentConversation = computed(
    () => items.value.find((item) => item.id === currentId.value) ?? null,
  )

  function selectConversation(id: string, userId: string): void {
    if (!items.value.some((item) => item.id === id)) return
    currentId.value = id
    localStorage.setItem(selectionKey(userId), id)
  }

  async function loadConversations(userId: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      items.value = await fetchConversations(userId)
      const savedId = localStorage.getItem(selectionKey(userId))
      const nextId = items.value.some((item) => item.id === savedId)
        ? savedId
        : (items.value[0]?.id ?? null)
      currentId.value = nextId
      if (nextId) localStorage.setItem(selectionKey(userId), nextId)
    } catch (reason) {
      error.value = getErrorMessage(reason, '会话操作失败，请稍后重试')
    } finally {
      loading.value = false
    }
  }

  async function createConversation(userId: string): Promise<Conversation> {
    creating.value = true
    error.value = null
    try {
      const conversation = await apiCreateConversation(userId)
      items.value.unshift(conversation)
      selectConversation(conversation.id, userId)
      return conversation
    } catch (reason) {
      error.value = getErrorMessage(reason, '会话操作失败，请稍后重试')
      throw reason
    } finally {
      creating.value = false
    }
  }

  async function nameConversationFromQuery(id: string, query: string): Promise<void> {
    const current = items.value.find((item) => item.id === id)
    if (!current || current.title !== '新的知识问答') return
    const title = query.trim().replace(/\s+/g, ' ').slice(0, 24) || current.title
    current.title = title
    current.updatedAt = new Date().toISOString()
    try {
      await updateConversationTitle(id, title)
    } catch (reason) {
      error.value = getErrorMessage(reason, '会话操作失败，请稍后重试')
    }
  }

  async function renameConversation(id: string, title: string): Promise<void> {
    const current = items.value.find((item) => item.id === id)
    const normalized = title.trim().replace(/\s+/g, ' ')
    if (!current || !normalized || current.title === normalized) return
    const previousTitle = current.title
    current.title = normalized
    current.updatedAt = new Date().toISOString()
    error.value = null
    try {
      await updateConversationTitle(id, normalized)
    } catch (reason) {
      current.title = previousTitle
      error.value = getErrorMessage(reason, '会话重命名失败，请稍后重试')
      throw reason
    }
  }

  async function deleteConversation(id: string, userId: string): Promise<string | null> {
    const index = items.value.findIndex((item) => item.id === id)
    if (index < 0) return currentId.value
    error.value = null
    try {
      await apiDeleteConversation(id)
      items.value.splice(index, 1)
      if (currentId.value === id) {
        currentId.value = items.value[index]?.id ?? items.value[index - 1]?.id ?? null
        if (currentId.value) localStorage.setItem(selectionKey(userId), currentId.value)
        else localStorage.removeItem(selectionKey(userId))
      }
      return currentId.value
    } catch (reason) {
      error.value = getErrorMessage(reason, '会话删除失败，请稍后重试')
      throw reason
    }
  }

  function reset(): void {
    items.value = []
    currentId.value = null
    error.value = null
  }

  return {
    items,
    currentId,
    loading,
    creating,
    error,
    currentConversation,
    loadConversations,
    createConversation,
    deleteConversation,
    nameConversationFromQuery,
    renameConversation,
    selectConversation,
    reset,
  }
})
