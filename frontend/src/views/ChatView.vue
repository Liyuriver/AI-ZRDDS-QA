<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatWelcome from '@/components/chat/ChatWelcome.vue'
import ConversationSidebar from '@/components/chat/ConversationSidebar.vue'
import MessageList from '@/components/chat/MessageList.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import { useChatStore } from '@/stores/chat'
import { useConversationStore } from '@/stores/conversation'
import { useUserStore } from '@/stores/user'
import type { Conversation } from '@/types/conversation'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const conversationStore = useConversationStore()
const chatStore = useChatStore()
const { currentUser } = storeToRefs(userStore)
const { items, currentId, currentConversation, loading, creating } = storeToRefs(conversationStore)
const { messages, historyLoading, sending, error: chatError } = storeToRefs(chatStore)
async function syncRouteWithSelection(): Promise<void> {
  const routeId =
    typeof route.params.conversationId === 'string' ? route.params.conversationId : null
  if (routeId && items.value.some((item) => item.id === routeId) && currentUser.value) {
    conversationStore.selectConversation(routeId, currentUser.value.id)
    return
  }
  if (currentId.value && routeId !== currentId.value) {
    await router.replace({ name: 'chat', params: { conversationId: currentId.value } })
  }
}

async function handleCreate(): Promise<void> {
  if (!currentUser.value) return
  try {
    const conversation = await conversationStore.createConversation(currentUser.value.id)
    await router.push({ name: 'chat', params: { conversationId: conversation.id } })
  } catch {
    ElMessage.error(conversationStore.error || '创建会话失败')
  }
}

async function handleSelect(id: string): Promise<void> {
  if (!currentUser.value || id === currentId.value) return
  conversationStore.selectConversation(id, currentUser.value.id)
  await router.push({ name: 'chat', params: { conversationId: id } })
}

async function handleRename(conversation: Conversation): Promise<void> {
  let submitted = false
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话标题', '重命名会话', {
      inputValue: conversation.title,
      inputPattern: /\S+/,
      inputErrorMessage: '会话标题不能为空',
      inputValidator: (title) => title.trim().length <= 255 || '会话标题不能超过 255 个字符',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    submitted = true
    await conversationStore.renameConversation(conversation.id, value)
    ElMessage.success('会话标题已保存')
  } catch {
    if (submitted) ElMessage.error(conversationStore.error || '会话重命名失败')
  }
}

async function handleDelete(conversation: Conversation): Promise<void> {
  let confirmed = false
  try {
    await ElMessageBox.confirm(`删除“${conversation.title}”及其全部消息？`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
    confirmed = true
    if (!currentUser.value) return
    const nextId = await conversationStore.deleteConversation(conversation.id, currentUser.value.id)
    await router.replace(
      nextId ? { name: 'chat', params: { conversationId: nextId } } : { name: 'chat' },
    )
    ElMessage.success('会话已删除')
  } catch {
    if (confirmed) ElMessage.error(conversationStore.error || '会话删除失败')
  }
}

async function handleLogout(): Promise<void> {
  userStore.logout()
  conversationStore.reset()
  chatStore.reset()
  await router.replace('/login')
  ElMessage.success('已退出登录')
}

async function handleSend(query: string): Promise<void> {
  if (!currentUser.value) return
  let conversationId = currentId.value
  if (!conversationId) {
    const conversation = await conversationStore.createConversation(currentUser.value.id)
    conversationId = conversation.id
    await router.push({ name: 'chat', params: { conversationId } })
  }
  await conversationStore.nameConversationFromQuery(conversationId, query)
  await chatStore.sendMessage(conversationId, currentUser.value.id, query)
}

onMounted(async () => {
  if (!currentUser.value) {
    await router.replace('/login')
    return
  }
  await conversationStore.loadConversations(currentUser.value.id)
  await syncRouteWithSelection()
})

watch(() => route.params.conversationId, syncRouteWithSelection)
watch(currentId, async (id) => {
  if (id) await chatStore.loadMessages(id)
  else chatStore.reset()
})
</script>

<template>
  <main class="chat-page">
    <AppHeader :username="currentUser?.displayName || '当前用户'" @logout="handleLogout" />
    <section class="chat-page__workspace">
      <ConversationSidebar
        :conversations="items"
        :creating="creating"
        :current-id="currentId"
        :loading="loading"
        @create="handleCreate"
        @delete="handleDelete"
        @rename="handleRename"
        @select="handleSelect"
      />
      <section class="chat-page__main">
        <header class="chat-page__titlebar">
          <div>
            <p>当前会话</p>
            <h1>{{ currentConversation?.title || '新的知识问答' }}</h1>
          </div>
          <span>{{ currentConversation ? '已保存' : '未开始' }}</span>
        </header>
        <div class="chat-page__messages">
          <ChatWelcome v-if="!historyLoading && messages.length === 0 && !sending" />
          <MessageList
            v-else
            :loading="historyLoading"
            :messages="messages"
            :sending="sending"
            :error="chatError"
            @retry="chatStore.retryMessage($event, currentUser?.id || '')"
          />
        </div>
        <ChatComposer :sending="sending" @send="handleSend" />
      </section>
    </section>
  </main>
</template>

<style scoped>
.chat-page {
  height: 100vh;
  overflow: hidden;
  background: var(--color-surface);
}
.chat-page__workspace {
  display: grid;
  height: calc(100vh - var(--header-height));
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
}
.chat-page__main {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: 66px minmax(0, 1fr) auto;
  background: #fbfcfe;
}
.chat-page__titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 30px;
  border-bottom: 1px solid var(--color-border);
  background: #fff;
}
.chat-page__titlebar p {
  margin: 0 0 3px;
  color: #98a2b3;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.chat-page__titlebar h1 {
  margin: 0;
  font-size: 15px;
}
.chat-page__titlebar > span {
  padding: 6px 10px;
  border-radius: 999px;
  color: #64748b;
  background: #f1f5f9;
  font-size: 11px;
  font-weight: 700;
}
.chat-page__messages {
  display: grid;
  min-height: 0;
  overflow-y: auto;
  padding: 48px 48px 24px;
}
</style>
