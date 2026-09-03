<script setup lang="ts">
import { computed, ref } from 'vue'

import type { Citation } from '@/types/chat'
import CitationItem from './CitationItem.vue'

const props = defineProps<{ citations: Citation[] }>()
const showAll = ref(false)
const visibleCitations = computed(() =>
  showAll.value ? props.citations : props.citations.slice(0, 3),
)
const hiddenCount = computed(() => Math.max(0, props.citations.length - 3))
</script>

<template>
  <details class="citation-list" open>
    <summary>
      <span>参考来源</span>
      <small>{{ citations.length }} 条证据</small>
    </summary>
    <div class="citation-list__items">
      <CitationItem
        v-for="(citation, index) in visibleCitations"
        :key="`${citation.documentId || citation.sourceFile}-${index}`"
        :citation="citation"
        :index="index + 1"
      />
    </div>
    <button
      v-if="hiddenCount"
      class="citation-list__more"
      type="button"
      :aria-expanded="showAll"
      @click="showAll = !showAll"
    >
      {{ showAll ? '收起额外依据' : `查看另外 ${hiddenCount} 条依据` }}
      <span aria-hidden="true">{{ showAll ? '↑' : '↓' }}</span>
    </button>
  </details>
</template>

<style scoped>
.citation-list {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border);
}
.citation-list summary {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #475569;
  cursor: pointer;
  list-style: none;
  font-size: 12px;
  font-weight: 800;
}
.citation-list summary::-webkit-details-marker {
  display: none;
}
.citation-list summary::before {
  content: '▾';
  color: #94a3b8;
  transition: transform 0.2s ease;
}
.citation-list:not([open]) summary::before {
  transform: rotate(-90deg);
}
.citation-list summary small {
  padding: 3px 7px;
  border-radius: 999px;
  color: #64748b;
  background: #f1f5f9;
  font-size: 10px;
}
.citation-list__items {
  display: grid;
  gap: 14px;
  margin-top: 14px;
}
.citation-list__more {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin-top: 12px;
  padding: 10px 14px;
  border: 1px dashed #c9d7e7;
  border-radius: 9px;
  color: #315f9f;
  background: #f8fbff;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: 0.18s ease;
}
.citation-list__more:hover,
.citation-list__more:focus-visible {
  border-color: #93b4e8;
  background: #eff6ff;
  outline: none;
}
</style>
