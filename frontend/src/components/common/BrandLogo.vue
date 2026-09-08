<script setup lang="ts">
import aiLogo from '@/assets/ai-logo.jpg'

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
    <span class="brand__mark">
      <img :src="aiLogo" alt="ZRDDS QA" />
    </span>
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
  display: block;
  width: 76px;
  height: 76px;
  overflow: hidden;
  border: 1px solid #c9e5d5;
  border-radius: 50%;
  background: #f1fbf5;
  box-shadow: 0 7px 20px rgb(36 113 80 / 18%);
}

.brand__mark img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.brand__copy {
  display: grid;
  gap: 2px;
}

.brand__copy strong {
  color: var(--color-text);
  font-size: 16px;
  letter-spacing: -0.025em;
}

.brand__copy small {
  color: var(--color-text-secondary);
  font-size: 12px;
}

.brand--compact .brand__mark {
  width: 50px;
  height: 50px;
}

@media (max-width: 640px) {
  .brand__mark {
    width: 64px;
    height: 64px;
  }

  .brand--compact .brand__mark {
    width: 42px;
    height: 42px;
  }
}
</style>
