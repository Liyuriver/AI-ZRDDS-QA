import { ref } from 'vue'
import { defineStore } from 'pinia'

import { fetchMessages, sendMessage as apiSendMessage } from '@/api/chat'
import type { ChatMessage } from '@/types/chat'
import { getErrorMessage } from '@/utils/error'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const historyLoading = ref(false)
  const sending = ref(false)
  const error = ref<string | null>(null)
  let requestVersion = 0

  async function loadMessages(conversationId: string): Promise<void> {
    const version = ++requestVersion
    historyLoading.value = true
    error.value = null
    messages.value = []
    try {
      const loaded = await fetchMessages(conversationId)
      if (version === requestVersion) messages.value = loaded
    } catch (reason) {
      error.value = getErrorMessage(reason, '历史消息加载失败，请稍后重试')
      if (version === requestVersion) messages.value = []
    } finally {
      if (version === requestVersion) historyLoading.value = false
    }
  }

  async function submitUserMessage(userMessage: ChatMessage, userId: string): Promise<void> {
    sending.value = true
    error.value = null
    userMessage.errorMessage = undefined
    try {
      const assistant = await apiSendMessage({
        conversationId: userMessage.conversationId,
        userMessage,
        userId,
      })
      userMessage.status = 'success'
      messages.value.push(assistant)
    } catch (reason) {
      userMessage.status = 'error'
      error.value = getErrorMessage(reason, '消息发送失败，请稍后重试')
      userMessage.errorMessage = error.value
    } finally {
      sending.value = false
    }
  }

  async function sendMessage(conversationId: string, userId: string, query: string): Promise<void> {
    if (sending.value || !query.trim()) return
    requestVersion += 1
    historyLoading.value = false
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      conversationId,
      role: 'user',
      content: query.trim(),
      status: 'sending',
      createdAt: new Date().toISOString(),
    }
    messages.value.push(userMessage)
    await submitUserMessage(userMessage, userId)
  }

  async function retryMessage(messageId: string, userId: string): Promise<void> {
    if (sending.value) return
    const message = messages.value.find(
      (item) => item.id === messageId && item.role === 'user' && item.status === 'error',
    )
    if (!message) return
    message.status = 'sending'
    message.errorMessage = undefined
    await submitUserMessage(message, userId)
  }

  function reset(): void {
    requestVersion += 1
    messages.value = []
    error.value = null
  }

  return {
    messages,
    historyLoading,
    sending,
    error,
    loadMessages,
    sendMessage,
    retryMessage,
    reset,
  }
})
