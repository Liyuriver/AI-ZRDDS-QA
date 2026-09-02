<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { Conversation } from '@/types/conversation'

const props = defineProps<{
  modelValue: boolean
  mode: 'rename' | 'delete'
  conversation: Conversation | null
  loading?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [title?: string]
}>()
const title = ref('')
const error = ref('')
const isDelete = computed(() => props.mode === 'delete')

watch(
  () => [props.modelValue, props.conversation] as const,
  () => {
    if (!props.modelValue) return
    title.value = props.conversation?.title || ''
    error.value = ''
  },
  { immediate: true },
)

function confirm(): void {
  if (isDelete.value) {
    emit('confirm')
    return
  }
  const normalized = title.value.trim().replace(/\s+/g, ' ')
  if (!normalized) {
    error.value = '会话标题不能为空'
    return
  }
  if (normalized.length > 255) {
    error.value = '会话标题不能超过 255 个字符'
    return
  }
  emit('confirm', normalized)
}
</script>

<template>
  <el-dialog
    align-center
    append-to-body
    :close-on-click-modal="false"
    :model-value="modelValue"
    :show-close="!loading"
    :title="isDelete ? '删除会话' : '重命名会话'"
    width="440px"
    @closed="error = ''"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="conversation-modal__header" :class="{ 'is-delete': isDelete }">
        <span class="conversation-modal__icon" aria-hidden="true">
          <svg v-if="isDelete" viewBox="0 0 24 24">
            <path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7" />
            <path d="M10 11v5m4-5v5" />
          </svg>
          <svg v-else viewBox="0 0 24 24">
            <path d="M4 20h4l10.5-10.5a2.8 2.8 0 0 0-4-4L4 16v4Z" />
            <path d="m13.5 6.5 4 4" />
          </svg>
        </span>
        <div>
          <h3>{{ isDelete ? '删除会话' : '重命名会话' }}</h3>
          <p>{{ isDelete ? '此操作无法撤销' : '使用清晰的标题方便以后查找' }}</p>
        </div>
      </div>
    </template>

    <div v-if="isDelete" class="conversation-modal__delete-copy">
      确定删除“<strong>{{ conversation?.title }}</strong
      >”及其全部消息吗？
    </div>
    <label v-else class="conversation-modal__field">
      <span>会话标题</span>
      <el-input
        v-model="title"
        autofocus
        maxlength="255"
        placeholder="输入便于识别的会话名称"
        show-word-limit
        @keyup.enter="confirm"
      />
      <small v-if="error" role="alert">{{ error }}</small>
    </label>

    <template #footer>
      <el-button :disabled="loading" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button :loading="loading" :type="isDelete ? 'danger' : 'primary'" @click="confirm">
        {{ isDelete ? '确认删除' : '保存修改' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
:global(.el-dialog:has(.conversation-modal__header)) {
  overflow: hidden;
  padding: 0;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  box-shadow: 0 24px 70px rgb(15 23 42 / 22%);
}
:global(.el-dialog:has(.conversation-modal__header) .el-dialog__header) {
  margin: 0;
  padding: 24px 24px 16px;
}
:global(.el-dialog:has(.conversation-modal__header) .el-dialog__body) {
  padding: 8px 24px 24px;
}
:global(.el-dialog:has(.conversation-modal__header) .el-dialog__footer) {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px 22px;
  border-top: 1px solid #edf0f4;
  background: #fafbfc;
}
:global(.el-dialog:has(.conversation-modal__header) .el-dialog__footer .el-button) {
  min-width: 94px;
  height: 40px;
  margin: 0;
  border-radius: 9px;
  font-weight: 650;
}
.conversation-modal__header {
  display: flex;
  align-items: center;
  gap: 13px;
}
.conversation-modal__icon {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 12px;
  color: var(--color-primary);
  background: #eff6ff;
}
.conversation-modal__header.is-delete .conversation-modal__icon {
  color: #dc2626;
  background: #fef2f2;
}
.conversation-modal__icon svg {
  width: 20px;
  fill: none;
  stroke: currentcolor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}
.conversation-modal__header h3,
.conversation-modal__header p {
  margin: 0;
}
.conversation-modal__header h3 {
  color: #172033;
  font-size: 18px;
}
.conversation-modal__header p {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 12px;
}
.conversation-modal__delete-copy {
  padding: 14px 16px;
  border: 1px solid #fee2e2;
  border-radius: 11px;
  color: #475569;
  background: #fff8f8;
  line-height: 1.75;
}
.conversation-modal__delete-copy strong {
  color: #172033;
}
.conversation-modal__field {
  display: grid;
  gap: 8px;
}
.conversation-modal__field > span {
  color: #475569;
  font-size: 13px;
  font-weight: 650;
}
.conversation-modal__field small {
  color: #dc2626;
  font-size: 12px;
}
</style>
