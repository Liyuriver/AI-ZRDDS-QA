<script setup lang="ts">
import { computed } from 'vue'

import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ content: string }>()
const html = computed(() => renderMarkdown(props.content))

async function handleClick(event: MouseEvent): Promise<void> {
  const target = event.target
  if (!(target instanceof HTMLElement) || !target.matches('[data-copy-code]')) return
  const code = target.parentElement?.querySelector('code')?.textContent || ''
  if (!code || !navigator.clipboard) return
  await navigator.clipboard.writeText(code)
  target.textContent = '已复制'
  window.setTimeout(() => {
    target.textContent = '复制代码'
  }, 1200)
}
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div class="markdown-content" @click="handleClick" v-html="html" />
</template>

<style scoped>
.markdown-content {
  color: var(--color-text);
  font-size: 14px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}
.markdown-content :deep(> :first-child) {
  margin-top: 0;
}
.markdown-content :deep(> :last-child) {
  margin-bottom: 0;
}
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  margin: 1.4em 0 0.65em;
  line-height: 1.35;
}
.markdown-content :deep(h2) {
  font-size: 18px;
}
.markdown-content :deep(h3) {
  font-size: 16px;
}
.markdown-content :deep(p),
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin: 0.75em 0;
}
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  padding-left: 1.5em;
}
.markdown-content :deep(code) {
  padding: 0.15em 0.38em;
  border-radius: 5px;
  color: #be123c;
  background: #f1f5f9;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 0.9em;
}
.markdown-content :deep(.code-block) {
  position: relative;
  margin: 1em 0;
  padding-top: 34px;
  overflow: hidden;
  border: 1px solid #263244;
  border-radius: 10px;
  background: #111827;
}
.markdown-content :deep(.code-block__language) {
  position: absolute;
  top: 9px;
  left: 13px;
  color: #94a3b8;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 10px;
}
.markdown-content :deep(.code-copy-button) {
  position: absolute;
  top: 6px;
  right: 8px;
  padding: 4px 8px;
  border: 1px solid #475569;
  border-radius: 6px;
  color: #cbd5e1;
  background: #1e293b;
  font-size: 10px;
  cursor: pointer;
}
.markdown-content :deep(.code-copy-button:hover) {
  color: #fff;
  border-color: #64748b;
}
.markdown-content :deep(pre) {
  margin: 1em 0;
  padding: 16px;
  overflow-x: auto;
  border: 0;
  border-radius: 0;
  background: #111827;
}
.markdown-content :deep(.code-block pre) {
  margin: 0;
}
.markdown-content :deep(pre code) {
  padding: 0;
  color: #dbeafe;
  background: transparent;
  line-height: 1.65;
}
.markdown-content :deep(.hljs-keyword),
.markdown-content :deep(.hljs-selector-tag) {
  color: #c4b5fd;
}
.markdown-content :deep(.hljs-string),
.markdown-content :deep(.hljs-attr) {
  color: #86efac;
}
.markdown-content :deep(.hljs-comment) {
  color: #94a3b8;
}
.markdown-content :deep(table) {
  width: 100%;
  margin: 1em 0;
  border-spacing: 0;
  border-collapse: separate;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 9px;
}
.markdown-content :deep(th),
.markdown-content :deep(td) {
  padding: 9px 12px;
  border-right: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}
.markdown-content :deep(th) {
  background: #f8fafc;
  font-weight: 700;
}
.markdown-content :deep(tr:last-child td) {
  border-bottom: 0;
}
.markdown-content :deep(th:last-child),
.markdown-content :deep(td:last-child) {
  border-right: 0;
}
.markdown-content :deep(blockquote) {
  margin: 1em 0;
  padding: 10px 14px;
  border-left: 3px solid #93c5fd;
  color: #52647f;
  background: #f8fbff;
}
.markdown-content :deep(a) {
  color: var(--color-primary);
  text-decoration: none;
}
.markdown-content :deep(a:hover) {
  text-decoration: underline;
}
</style>
