<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ sending?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ send: [query: string] }>()
const query = ref('')

function handleSend(): void {
  const value = query.value.trim()
  if (value) {
    emit('send', value)
    query.value = ''
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <footer class="chat-composer">
    <div class="chat-composer__box">
      <textarea
        v-model="query"
        aria-label="问题输入框"
        :disabled="disabled || sending"
        maxlength="2000"
        placeholder="请输入关于 ZRDDS 的问题……"
        rows="2"
        @keydown="handleKeydown"
      />
      <el-button
        :disabled="disabled || !query.trim()"
        :loading="sending"
        type="primary"
        @click="handleSend"
        >发送</el-button
      >
    </div>
    <p>Enter 发送，Shift + Enter 换行 · 回答内容请以引用文档为准</p>
  </footer>
</template>

<style scoped>
.chat-composer {
  width: min(900px, calc(100% - 64px));
  margin: 0 auto;
  padding: 18px 0 16px;
}
.chat-composer__box {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  padding: 12px 12px 12px 18px;
  border: 1px solid #d7deea;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 12px 34px rgb(15 23 42 / 9%);
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.chat-composer__box:focus-within {
  border-color: #93b4f5;
  box-shadow: 0 12px 36px rgb(37 99 235 / 13%);
}
.chat-composer textarea {
  min-height: 48px;
  max-height: 150px;
  flex: 1;
  padding: 10px 0;
  resize: none;
  border: 0;
  outline: 0;
  color: var(--color-text);
  background: transparent;
  line-height: 1.6;
}
.chat-composer textarea::placeholder {
  color: #a5adba;
}
.chat-composer__box .el-button {
  min-width: 76px;
  height: 42px;
  border-radius: 11px;
}
.chat-composer > p {
  margin: 9px 0 0;
  color: #98a2b3;
  text-align: center;
  font-size: 11px;
}
</style>
