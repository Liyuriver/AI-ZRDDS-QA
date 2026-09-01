<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { ChatMessage } from '@/types/chat'
import AssistantMessage from './AssistantMessage.vue'
import UserMessage from './UserMessage.vue'

const props = defineProps<{
  messages: ChatMessage[]
  loading: boolean
  sending: boolean
  error?: string | null
}>()
defineEmits<{ retry: [id: string] }>()

const endRef = ref<HTMLElement>()
const elapsedSeconds = ref(0)
let timer: number | undefined

const thinkingText = computed(() => {
  if (elapsedSeconds.value <= 8) return '正在检索知识库…'
  if (elapsedSeconds.value <= 25) return '正在整理检索证据…'
  return '正在生成回答，知识库问答可能需要一些时间…'
})

function stopTimer(): void {
  if (timer !== undefined) window.clearInterval(timer)
  timer = undefined
}

watch(
  () => props.sending,
  (sending) => {
    stopTimer()
    elapsedSeconds.value = 0
    if (sending) {
      timer = window.setInterval(() => {
        elapsedSeconds.value += 1
      }, 1000)
    }
  },
  { immediate: true },
)

onBeforeUnmount(stopTimer)

watch(
  () => [props.messages.length, props.messages.at(-1)?.status, props.sending],
  async () => {
    await nextTick()
    endRef.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  },
)
</script>

<template>
  <div v-loading="loading" class="message-list">
    <template v-for="message in messages" :key="message.id">
      <UserMessage
        v-if="message.role === 'user'"
        :message="message"
        @retry="$emit('retry', $event)"
      />
      <AssistantMessage v-else :message="message" />
    </template>

    <article v-if="sending" class="message-list__thinking">
      <span class="message-list__avatar">AI</span>
      <div aria-live="polite">
        <i /><i /><i />
        <span>{{ thinkingText }}</span>
        <small>已等待 {{ elapsedSeconds }} 秒</small>
      </div>
    </article>
    <div v-if="error && !sending" class="message-list__error" role="alert">
      <strong>本次回答未完成</strong>
      <span>{{ error }}</span>
    </div>
    <span ref="endRef" aria-hidden="true" />
  </div>
</template>

<style scoped>
.message-list {
  display: grid;
  width: min(920px, 100%);
  min-height: 100%;
  margin: 0 auto;
  align-content: start;
  gap: 24px;
}
.message-list__thinking {
  display: flex;
  align-items: center;
  gap: 12px;
}
.message-list__avatar {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 10px;
  color: #fff;
  background: #475569;
  font-size: 10px;
  font-weight: 800;
}
.message-list__thinking div {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 14px 17px;
  border: 1px solid var(--color-border);
  border-radius: 4px 14px 14px;
  background: #fff;
}
.message-list__thinking i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #94a3b8;
  animation: pulse 1.2s infinite ease-in-out;
}
.message-list__thinking i:nth-child(2) {
  animation-delay: 0.15s;
}
.message-list__thinking i:nth-child(3) {
  animation-delay: 0.3s;
}
.message-list__thinking span {
  margin-left: 5px;
  color: #64748b;
  font-size: 11px;
}
.message-list__thinking small {
  margin-left: 6px;
  color: #a1aab8;
  font-size: 10px;
}
.message-list__error {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: 46px;
  padding: 10px 13px;
  border: 1px solid #fecaca;
  border-radius: 10px;
  color: #991b1b;
  background: #fef2f2;
  font-size: 11px;
}
.message-list__error strong {
  flex: 0 0 auto;
}
.message-list__error span {
  color: #b91c1c;
}
@keyframes pulse {
  0%,
  80%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-3px);
  }
}
</style>
