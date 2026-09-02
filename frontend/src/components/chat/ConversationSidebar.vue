<script setup lang="ts">
import type { Conversation } from '@/types/conversation'

defineProps<{
  conversations: Conversation[]
  currentId: string | null
  loading: boolean
  creating: boolean
}>()

defineEmits<{
  create: []
  select: [id: string]
  rename: [conversation: Conversation]
  delete: [conversation: Conversation]
}>()

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(
    new Date(value),
  )
}
</script>

<template>
  <aside class="conversation-sidebar">
    <div class="conversation-sidebar__heading">
      <div>
        <p>工作区</p>
        <h2>历史会话</h2>
      </div>
      <span class="conversation-sidebar__count">{{ conversations.length }}</span>
    </div>

    <el-button
      class="conversation-sidebar__create"
      :loading="creating"
      type="primary"
      @click="$emit('create')"
    >
      <span aria-hidden="true">＋</span>
      新建会话
    </el-button>

    <div v-loading="loading" class="conversation-sidebar__list">
      <div
        v-for="conversation in conversations"
        :key="conversation.id"
        class="conversation-sidebar__item"
        :class="{ 'conversation-sidebar__item--active': conversation.id === currentId }"
      >
        <button
          :aria-current="conversation.id === currentId ? 'page' : undefined"
          class="conversation-sidebar__select"
          :title="conversation.title"
          type="button"
          @click="$emit('select', conversation.id)"
        >
          <span class="conversation-sidebar__item-mark" aria-hidden="true">问</span>
          <span class="conversation-sidebar__item-copy">
            <strong>{{ conversation.title }}</strong>
            <small>{{ formatTime(conversation.updatedAt) }}</small>
          </span>
        </button>
        <span class="conversation-sidebar__actions">
          <button
            class="conversation-sidebar__rename"
            type="button"
            title="重命名会话"
            aria-label="重命名会话"
            @click="$emit('rename', conversation)"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path d="M4 20h4l10.5-10.5a2.8 2.8 0 0 0-4-4L4 16v4Z" />
              <path d="m13.5 6.5 4 4" />
            </svg>
          </button>
          <button
            class="conversation-sidebar__delete"
            type="button"
            title="删除会话"
            aria-label="删除会话"
            @click="$emit('delete', conversation)"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7" />
              <path d="M10 11v5m4-5v5" />
            </svg>
          </button>
        </span>
      </div>

      <div v-if="!loading && conversations.length === 0" class="conversation-sidebar__empty">
        <span class="conversation-sidebar__empty-icon" aria-hidden="true">⌁</span>
        <strong>暂无历史会话</strong>
        <p>开始第一次提问后，会话将显示在这里。</p>
      </div>
    </div>

    <div class="conversation-sidebar__footer">
      <span class="conversation-sidebar__indicator" />
      <span>知识库问答服务</span>
    </div>
  </aside>
</template>

<style scoped>
.conversation-sidebar {
  display: flex;
  min-height: 0;
  flex-direction: column;
  padding: 24px 18px 18px;
  border-right: 1px solid var(--color-border);
  background: #f8fafc;
}

.conversation-sidebar__heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding: 0 6px;
}

.conversation-sidebar__heading p {
  margin: 0 0 5px;
  color: #98a2b3;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}

.conversation-sidebar__heading h2 {
  margin: 0;
  font-size: 18px;
}

.conversation-sidebar__count {
  min-width: 24px;
  padding: 4px 7px;
  border-radius: 999px;
  color: #64748b;
  background: #e9eef5;
  text-align: center;
  font-size: 11px;
  font-weight: 700;
}

.conversation-sidebar__create {
  width: 100%;
  margin-top: 22px;
}

.conversation-sidebar__create span {
  margin-right: 4px;
  font-size: 18px;
}

.conversation-sidebar__list {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
}

.conversation-sidebar__item {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  padding: 5px;
  border: 1px solid transparent;
  border-radius: 11px;
  color: var(--color-text);
  background: transparent;
}

.conversation-sidebar__item:hover {
  background: #fff;
}

.conversation-sidebar__item--active {
  border-color: #dbeafe;
  background: #fff;
  box-shadow: 0 5px 16px rgb(15 23 42 / 5%);
}

.conversation-sidebar__select {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 10px;
  padding: 6px;
  border: 0;
  color: inherit;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.conversation-sidebar__actions {
  display: flex;
  flex: 0 0 auto;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.conversation-sidebar__item:hover .conversation-sidebar__actions,
.conversation-sidebar__item:focus-within .conversation-sidebar__actions {
  opacity: 1;
}

.conversation-sidebar__actions button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 7px;
  color: #64748b;
  background: transparent;
  cursor: pointer;
  transition:
    color 0.16s ease,
    background 0.16s ease,
    transform 0.16s ease;
}

.conversation-sidebar__actions button:hover,
.conversation-sidebar__actions button:focus-visible {
  color: var(--color-primary);
  background: #eff6ff;
  transform: translateY(-1px);
  outline: none;
}

.conversation-sidebar__actions svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentcolor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.conversation-sidebar__actions .conversation-sidebar__delete:hover,
.conversation-sidebar__actions .conversation-sidebar__delete:focus-visible {
  color: #dc2626;
  background: #fee2e2;
}

.conversation-sidebar__item-mark {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 9px;
  color: var(--color-primary);
  background: #eff6ff;
  font-size: 11px;
  font-weight: 800;
}

.conversation-sidebar__item-copy {
  display: grid;
  min-width: 0;
  flex: 1;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.conversation-sidebar__item-copy strong {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-sidebar__item-copy small {
  color: #98a2b3;
  font-size: 10px;
}

.conversation-sidebar__empty {
  display: grid;
  justify-items: center;
  margin-top: 64px;
  padding: 0 18px;
  color: #98a2b3;
  text-align: center;
}

.conversation-sidebar__empty-icon {
  display: grid;
  width: 42px;
  height: 42px;
  margin-bottom: 14px;
  place-items: center;
  border: 1px dashed #cbd5e1;
  border-radius: 13px;
  background: #fff;
  font-size: 22px;
}

.conversation-sidebar__empty strong {
  color: #64748b;
  font-size: 13px;
}

.conversation-sidebar__empty p {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.65;
}

.conversation-sidebar__footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 15px 8px 2px;
  border-top: 1px solid var(--color-border);
  color: #98a2b3;
  font-size: 11px;
}

.conversation-sidebar__indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
}
</style>
