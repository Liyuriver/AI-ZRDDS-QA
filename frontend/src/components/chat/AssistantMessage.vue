<script setup lang="ts">
import { ElMessage } from 'element-plus'

import aiLogo from '@/assets/ai-logo.jpg'
import type { ChatMessage } from '@/types/chat'
import CitationList from '@/components/citation/CitationList.vue'
import MarkdownContent from '@/components/common/MarkdownContent.vue'

const props = defineProps<{ message: ChatMessage }>()

const formatTime = (value: string) =>
  new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(value))

async function copyAnswer(): Promise<void> {
  if (!navigator.clipboard) {
    ElMessage.warning('当前浏览器不支持剪贴板功能')
    return
  }
  await navigator.clipboard.writeText(props.message.content)
  ElMessage.success('回答已复制')
}
</script>

<template>
  <article class="assistant-message">
    <div class="assistant-message__avatar">
      <img :src="aiLogo" alt="ZRDDS QA 助手" />
    </div>
    <div class="assistant-message__content">
      <div class="assistant-message__heading">
        <strong>AI 助手</strong><span>{{ formatTime(message.createdAt) }}</span>
        <button type="button" aria-label="复制回答" title="复制回答" @click="copyAnswer">
          复制
        </button>
      </div>
      <div class="assistant-message__body">
        <div v-if="message.answerStatus === 'partial'" class="assistant-message__partial">
          <strong>部分回答</strong>
          <span>已回答有证据支持的部分，其余结论请结合现场信息确认</span>
        </div>
        <div v-if="message.answerStatus === 'no_answer'" class="assistant-message__no-answer">
          <strong>依据不足</strong>
          <span>系统未生成推测性回答</span>
        </div>
        <MarkdownContent :content="message.content" />
        <CitationList v-if="message.citations?.length" :citations="message.citations" />
      </div>
    </div>
  </article>
</template>

<style scoped>
.assistant-message {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.assistant-message__avatar {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  overflow: hidden;
  border: 1px solid #c9e5d5;
  border-radius: 50%;
  background: #f1fbf5;
  box-shadow: 0 4px 12px rgb(49 94 75 / 14%);
}
.assistant-message__avatar img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.assistant-message__content {
  max-width: min(760px, 82%);
}
.assistant-message__heading {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 8px;
}
.assistant-message__heading strong {
  font-size: 12px;
}
.assistant-message__heading span {
  color: #98a2b3;
  font-size: 10px;
}
.assistant-message__heading button {
  margin-left: auto;
  padding: 3px 8px;
  border: 1px solid #d5e7dd;
  border-radius: 6px;
  color: #587469;
  background: #fcfffd;
  font-size: 10px;
  cursor: pointer;
}
.assistant-message__heading button:hover {
  color: var(--color-primary);
  border-color: #add8c0;
  background: #eaf7f0;
}
.assistant-message__body {
  padding: 16px 18px;
  border: 1px solid var(--color-border);
  border-radius: 4px 16px 16px;
  background: rgb(255 255 255 / 90%);
  box-shadow: 0 9px 26px rgb(31 90 65 / 6%);
}
.assistant-message__no-answer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 13px;
  padding: 10px 12px;
  border: 1px solid #fde68a;
  border-radius: 9px;
  color: #92400e;
  background: #fffbeb;
}
.assistant-message__partial {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 13px;
  padding: 10px 12px;
  border: 1px solid #bfdbfe;
  border-radius: 9px;
  color: #1e3a8a;
  background: #eff6ff;
}
.assistant-message__partial strong {
  font-size: 12px;
}
.assistant-message__partial span {
  color: #1d4ed8;
  font-size: 10px;
}
.assistant-message__no-answer strong {
  font-size: 12px;
}
.assistant-message__no-answer span {
  color: #a16207;
  font-size: 10px;
}
</style>
