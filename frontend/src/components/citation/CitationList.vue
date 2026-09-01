<script setup lang="ts">
import type { Citation } from '@/types/chat'
import CitationItem from './CitationItem.vue'

defineProps<{ citations: Citation[] }>()
</script>

<template>
  <details class="citation-list" open>
    <summary>
      <span>参考来源</span>
      <small>{{ citations.length }} 条证据</small>
    </summary>
    <div class="citation-list__items">
      <CitationItem
        v-for="(citation, index) in citations"
        :key="`${citation.documentId || citation.sourceFile}-${index}`"
        :citation="citation"
        :index="index + 1"
      />
    </div>
  </details>
</template>

<style scoped>
.citation-list {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border);
}
.citation-list summary {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #475569;
  cursor: pointer;
  list-style: none;
  font-size: 11px;
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
  font-size: 9px;
}
.citation-list__items {
  display: grid;
  gap: 9px;
  margin-top: 11px;
}
</style>
