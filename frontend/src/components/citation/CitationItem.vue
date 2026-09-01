<script setup lang="ts">
import { computed } from 'vue'

import type { Citation, VersionStatus } from '@/types/chat'

const props = defineProps<{ citation: Citation; index: number }>()

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
</script>

<template>
  <article class="citation-item">
    <div class="citation-item__index">{{ index }}</div>
    <div class="citation-item__content">
      <div class="citation-item__title">
        <strong>{{ citation.sourceFile }}</strong>
        <span :class="`citation-item__status--${versionStatus.className}`">
          {{ versionStatus.label }}
        </span>
      </div>
      <div class="citation-item__meta">
        <span v-if="citation.section">{{ citation.section }}</span>
        <span>{{ pageLabel }}</span>
        <span v-if="citation.version">版本：{{ citation.version }}</span>
      </div>
      <p v-if="citation.snippet" class="citation-item__snippet">{{ citation.snippet }}</p>
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
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 13px;
  border: 1px solid var(--color-border);
  border-radius: 11px;
  background: #fbfcfe;
}
.citation-item__index {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 7px;
  color: var(--color-primary);
  background: #eaf2ff;
  font-size: 11px;
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
  gap: 12px;
}
.citation-item__title strong {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.citation-item__title span {
  flex: 0 0 auto;
  padding: 4px 7px;
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
  color: #a16207;
  background: #fef3c7;
}
.citation-item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 7px;
  color: #64748b;
  font-size: 10px;
}
.citation-item__snippet {
  margin: 9px 0 0;
  color: #52647f;
  font-size: 11px;
  line-height: 1.65;
}
.citation-item__images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
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
</style>
