<script setup lang="ts">
import type { ChatMessage } from '@/types/chat'

defineProps<{ message: ChatMessage }>()
defineEmits<{ retry: [id: string] }>()

const formatTime = (value: string) =>
  new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
</script>

<template>
  <article class="user-message">
    <div class="user-message__body">{{ message.content }}</div>
    <div class="user-message__meta">
      <span>{{ formatTime(message.createdAt) }}</span>
      <span v-if="message.status === 'sending'">正在发送…</span>
      <button v-if="message.status === 'error'" type="button" @click="$emit('retry', message.id)">
        {{ message.errorMessage || '发送失败' }}，点击重试
      </button>
    </div>
  </article>
</template>

<style scoped>
.user-message {
  display: grid;
  justify-items: end;
}
.user-message__body {
  max-width: min(680px, 78%);
  padding: 13px 17px;
  border-radius: 16px 16px 4px;
  color: #fff;
  background: linear-gradient(135deg, #3b9b72, var(--color-primary-dark));
  line-height: 1.75;
  white-space: pre-wrap;
  box-shadow: 0 9px 24px rgb(31 111 80 / 19%);
}
.user-message__meta {
  display: flex;
  gap: 10px;
  margin-top: 7px;
  color: #98a2b3;
  font-size: 10px;
}
.user-message__meta button {
  padding: 0;
  border: 0;
  color: #dc2626;
  background: transparent;
  cursor: pointer;
}
</style>
