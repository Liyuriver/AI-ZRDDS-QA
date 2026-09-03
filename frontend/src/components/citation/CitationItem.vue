<script setup lang="ts">
import { computed, ref } from 'vue'

import type { Citation, VersionStatus } from '@/types/chat'

const props = defineProps<{ citation: Citation; index: number }>()
const expanded = ref(false)

const statusMap: Record<VersionStatus, { label: string; className: string }> = {
  compatible: { label: '版本适用', className: 'compatible' },
  incompatible: { label: '版本不适用', className: 'incompatible' },
  unknown: { label: '版本适用性未知', className: 'unknown' },
}

const versionStatus = computed(() => statusMap[props.citation.versionStatus])
const pageLabel = computed(() => {
  if (props.citation.page) return `第 ${props.citation.page} 页`
  if (props.citation.pageStart && props.citation.pageEnd) {
    return props.citation.pageStart === props.citation.pageEnd
      ? `第 ${props.citation.pageStart} 页`
      : `第 ${props.citation.pageStart}–${props.citation.pageEnd} 页`
  }
  return '页码未提供'
})
const versionLabel = computed(() => props.citation.version || '版本未知')
const displaySnippet = computed(() => cleanMarkdownArtifacts(props.citation.snippet || ''))
const canExpand = computed(() => {
  const snippet = displaySnippet.value
  return snippet.length > 180 || snippet.split(/\r?\n/).length > 4
})

function cleanMarkdownArtifacts(value: string): string {
  return value
    .replace(/\r\n?/g, '\n')
    .replace(/^\s{0,3}#{1,6}[\t ]+/gm, '')
    .replace(/^\s*>[\t ]?/gm, '')
    .replace(/^\s*[*+-][\t ]+/gm, '')
    .replace(/^\s*[-*_]{3,}\s*$/gm, '')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/__([^_\n]+)__/g, '$1')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
</script>

<template>
  <article class="citation-item">
    <div class="citation-item__index">
      <span>依据</span><strong>{{ index }}</strong>
    </div>
    <div class="citation-item__content">
      <div class="citation-item__title">
        <strong>{{ citation.sourceFile }}</strong>
        <span
          class="citation-item__status"
          :class="`citation-item__status--${versionStatus.className}`"
        >
          {{ versionStatus.label }}
        </span>
      </div>
      <div class="citation-item__meta">
        <span v-if="citation.section">{{ citation.section }}</span>
        <span>{{ pageLabel }}</span>
        <span :class="{ 'citation-item__version--unknown': !citation.version }">
          {{ versionLabel }}
        </span>
      </div>
      <div v-if="citation.snippet" class="citation-item__excerpt">
        <p class="citation-item__snippet" :class="{ 'is-expanded': expanded }">
          {{ displaySnippet }}
        </p>
        <button
          v-if="canExpand"
          type="button"
          :aria-expanded="expanded"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起' : '展开全文' }}
          <span aria-hidden="true">{{ expanded ? '↑' : '↓' }}</span>
        </button>
      </div>
      <div v-if="citation.images?.length" class="citation-item__images">
        <el-image
          v-for="image in citation.images"
          :key="image"
          :src="image"
          :preview-src-list="citation.images"
          fit="cover"
          hide-on-click-modal
          preview-teleported
        >
          <template #error>
            <div class="citation-item__image-error">图片暂不可用</div>
          </template>
        </el-image>
      </div>
      <small v-if="citation.documentId">文档 ID：{{ citation.documentId }}</small>
    </div>
  </article>
</template>

<style scoped>
.citation-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px 16px 15px;
  overflow: hidden;
  border: 1px solid #dce4ee;
  border-radius: 12px;
  background: #fbfdff;
  box-shadow: 0 4px 16px rgb(38 64 99 / 4%);
}
.citation-item__index {
  display: flex;
  width: 38px;
  min-height: 48px;
  flex: 0 0 auto;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  border-radius: 9px;
  color: var(--color-primary);
  background: #eaf2ff;
}
.citation-item__index span {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.citation-item__index strong {
  margin-top: 1px;
  font-size: 15px;
  font-weight: 800;
}
.citation-item__content {
  min-width: 0;
  flex: 1;
}
.citation-item__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.citation-item__title strong {
  min-width: 0;
  overflow: hidden;
  color: #172033;
  font-size: 13px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.citation-item__status {
  flex: 0 0 auto;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 800;
}
.citation-item__status--compatible {
  color: #15803d;
  background: #dcfce7;
}
.citation-item__status--incompatible {
  color: #b91c1c;
  background: #fee2e2;
}
.citation-item__status--unknown {
  color: #7c6841;
  background: #f4f1e9;
}
.citation-item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 0;
  margin-top: 8px;
  color: #64748b;
  font-size: 10px;
}
.citation-item__meta span {
  min-width: 0;
  overflow-wrap: anywhere;
}
.citation-item__meta span:not(:last-child)::after {
  margin: 0 8px;
  color: #b6c2ce;
  content: '·';
}
.citation-item__version--unknown {
  color: #98a2b3;
}
.citation-item__excerpt {
  margin-top: 12px;
  padding-top: 11px;
  border-top: 1px solid #e8edf3;
}
.citation-item__snippet {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: #52647f;
  font-size: 12px;
  line-height: 1.75;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  word-break: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
}
.citation-item__snippet.is-expanded {
  display: block;
  overflow: visible;
  -webkit-line-clamp: unset;
}
.citation-item__excerpt button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 9px;
  padding: 0;
  border: 0;
  color: var(--color-primary);
  background: transparent;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
}
.citation-item__excerpt button:hover,
.citation-item__excerpt button:focus-visible {
  color: var(--color-primary-dark);
  text-decoration: underline;
  outline: none;
}
.citation-item__images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.citation-item__images :deep(.el-image) {
  width: 112px;
  height: 76px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #f1f5f9;
  cursor: zoom-in;
}
.citation-item__image-error {
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
  padding: 8px;
  color: #94a3b8;
  text-align: center;
  font-size: 10px;
}
.citation-item small {
  display: block;
  margin-top: 7px;
  color: #a1aab8;
  font-size: 9px;
}
@media (max-width: 560px) {
  .citation-item {
    gap: 10px;
    padding: 13px 12px;
  }
  .citation-item__index {
    width: 34px;
  }
  .citation-item__title {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }
  .citation-item__title strong {
    width: 100%;
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .citation-item__images :deep(.el-image) {
    width: 96px;
    height: 68px;
  }
}
</style>
