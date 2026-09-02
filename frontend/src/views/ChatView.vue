<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatWelcome from '@/components/chat/ChatWelcome.vue'
import ConversationSidebar from '@/components/chat/ConversationSidebar.vue'
import ConversationDialog from '@/components/chat/ConversationDialog.vue'
import MessageList from '@/components/chat/MessageList.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import ProfileDialog from '@/components/profile/ProfileDialog.vue'
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
const {
  messages,
  historyLoading,
  sending,
  error: chatError,
  missingConversationId,
} = storeToRefs(chatStore)
const profileVisible = ref(false)
const isOnline = ref(navigator.onLine)
const composerRef = ref<InstanceType<typeof ChatComposer>>()
const conversationDialogVisible = ref(false)
const conversationDialogMode = ref<'rename' | 'delete'>('rename')
const pendingConversation = ref<Conversation | null>(null)
const conversationActionLoading = ref(false)

function updateNetworkState(): void {
  const restored = !isOnline.value && navigator.onLine
  isOnline.value = navigator.onLine
  if (restored) ElMessage.success('网络已恢复，可以继续提问')
}

function focusComposerShortcut(event: KeyboardEvent): void {
  const target = event.target
  const editing =
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  if (event.key === '/' && !editing) {
    event.preventDefault()
    composerRef.value?.focus()
  }
}
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

function handleRename(conversation: Conversation): void {
  pendingConversation.value = conversation
  conversationDialogMode.value = 'rename'
  conversationDialogVisible.value = true
}

function handleDelete(conversation: Conversation): void {
  pendingConversation.value = conversation
  conversationDialogMode.value = 'delete'
  conversationDialogVisible.value = true
}

async function confirmConversationAction(title?: string): Promise<void> {
  const conversation = pendingConversation.value
  if (!conversation || conversationActionLoading.value) return
  conversationActionLoading.value = true
  try {
    if (conversationDialogMode.value === 'rename' && title) {
      await conversationStore.renameConversation(conversation.id, title)
      ElMessage.success('会话标题已保存')
    } else if (conversationDialogMode.value === 'delete' && currentUser.value) {
      const nextId = await conversationStore.deleteConversation(
        conversation.id,
        currentUser.value.id,
      )
      await router.replace(
        nextId ? { name: 'chat', params: { conversationId: nextId } } : { name: 'chat' },
      )
      ElMessage.success('会话已删除')
    }
    conversationDialogVisible.value = false
    pendingConversation.value = null
  } catch {
    ElMessage.error(
      conversationStore.error ||
        (conversationDialogMode.value === 'delete' ? '会话删除失败' : '会话重命名失败'),
    )
  } finally {
    conversationActionLoading.value = false
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
  if (!isOnline.value) {
    ElMessage.warning('网络连接已断开，请恢复网络后重试')
    return
  }
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
  window.addEventListener('online', updateNetworkState)
  window.addEventListener('offline', updateNetworkState)
  window.addEventListener('keydown', focusComposerShortcut)
  if (!currentUser.value) {
    await router.replace('/login')
    return
  }
  await conversationStore.loadConversations(currentUser.value.id)
  await syncRouteWithSelection()
})

onBeforeUnmount(() => {
  window.removeEventListener('online', updateNetworkState)
  window.removeEventListener('offline', updateNetworkState)
  window.removeEventListener('keydown', focusComposerShortcut)
})

watch(() => route.params.conversationId, syncRouteWithSelection)
watch(currentId, async (id) => {
  if (id) await chatStore.loadMessages(id)
  else chatStore.reset()
})
watch(missingConversationId, async (id) => {
  if (!id || !currentUser.value) return
  ElMessage.warning('当前会话已不存在，已为你刷新会话列表')
  await conversationStore.loadConversations(currentUser.value.id)
  await syncRouteWithSelection()
})
</script>

<template>
  <main class="chat-page">
    <AppHeader
      :avatar-url="currentUser?.avatarUrl"
      :username="currentUser?.displayName || '当前用户'"
      @logout="handleLogout"
      @profile="profileVisible = true"
    />
    <ProfileDialog v-model="profileVisible" :user="currentUser" />
    <ConversationDialog
      v-model="conversationDialogVisible"
      :conversation="pendingConversation"
      :loading="conversationActionLoading"
      :mode="conversationDialogMode"
      @confirm="confirmConversationAction"
    />
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
        <div v-if="!isOnline" class="chat-page__offline" role="alert">
          网络连接已断开，请恢复网络后继续提问。
        </div>
        <header class="chat-page__titlebar">
          <div>
            <p>当前会话</p>
            <h1 :title="currentConversation?.title || '新的知识问答'">
              {{ currentConversation?.title || '新的知识问答' }}
            </h1>
          </div>
          <span>{{ currentConversation ? '已保存' : '未开始' }}</span>
        </header>
        <div class="chat-page__messages">
          <ChatWelcome
            v-if="!historyLoading && messages.length === 0 && !sending"
            @suggest="handleSend"
          />
          <MessageList
            v-else
            :loading="historyLoading"
            :messages="messages"
            :sending="sending"
            :error="chatError"
            @retry="chatStore.retryMessage($event, currentUser?.id || '')"
          />
        </div>
        <ChatComposer
          ref="composerRef"
          :disabled="!isOnline"
          :sending="sending"
          @send="handleSend"
        />
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
  max-width: min(60vw, 720px);
  overflow: hidden;
  margin: 0;
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
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
.chat-page__offline {
  position: absolute;
  z-index: 2;
  top: 74px;
  left: 50%;
  padding: 9px 16px;
  transform: translateX(-50%);
  border: 1px solid #fed7aa;
  border-radius: 10px;
  color: #9a3412;
  background: #fff7ed;
  box-shadow: 0 8px 24px rgb(154 52 18 / 10%);
  font-size: 13px;
}
</style>
