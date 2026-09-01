<script setup lang="ts">
withDefaults(
  defineProps<{
    compact?: boolean
  }>(),
  {
    compact: false,
  },
)
</script>

<template>
  <div class="brand" :class="{ 'brand--compact': compact }">
    <span class="brand__mark" aria-hidden="true">AI</span>
    <span class="brand__copy">
      <strong>AI-ZRDDS-QA</strong>
      <small v-if="!compact">ZRDDS 智能知识库</small>
    </span>
  </div>
</template>

<style scoped>
.brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.brand__mark {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 13px;
  color: #fff;
  background: linear-gradient(145deg, var(--color-primary), #4f46e5);
  box-shadow: 0 8px 20px rgb(37 99 235 / 24%);
  font-size: 14px;
  font-weight: 800;
}

.brand__copy {
  display: grid;
  gap: 2px;
}

.brand__copy strong {
  color: var(--color-text);
  font-size: 16px;
  letter-spacing: -0.01em;
}

.brand__copy small {
  color: var(--color-text-secondary);
  font-size: 12px;
}

.brand--compact .brand__mark {
  width: 36px;
  height: 36px;
  border-radius: 11px;
}
</style>
