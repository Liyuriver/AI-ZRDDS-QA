<script setup lang="ts">
import BrandLogo from '@/components/common/BrandLogo.vue'
</script>

<template>
  <main class="auth-layout">
    <section class="auth-layout__intro">
      <BrandLogo />
      <div class="auth-layout__message">
        <p class="auth-layout__eyebrow">可靠 · 可追溯 · 版本感知</p>
        <h1>让每一个 ZRDDS 问题，都能找到可靠依据。</h1>
        <p>面向开发、配置与故障排查场景，统一呈现知识库回答、文档来源、章节页码和版本状态。</p>
      </div>
      <div class="auth-layout__feature-list" aria-label="系统特点">
        <span>知识问答</span>
        <span>证据引用</span>
        <span>历史会话</span>
      </div>
    </section>

    <section class="auth-layout__panel">
      <div class="auth-layout__card">
        <slot />
      </div>
      <p class="auth-layout__notice">本系统仅用于 ZRDDS 项目知识查询与辅助排障</p>
    </section>
  </main>
</template>

<style scoped>
.auth-layout {
  display: grid;
  min-height: 100vh;
  grid-template-columns: minmax(500px, 1.1fr) minmax(480px, 0.9fr);
  background: var(--color-surface);
}

.auth-layout__intro {
  display: flex;
  min-height: 100vh;
  flex-direction: column;
  justify-content: space-between;
  padding: 48px clamp(48px, 6vw, 96px);
  overflow: hidden;
  background:
    radial-gradient(circle at 85% 15%, rgb(96 165 250 / 28%), transparent 28%),
    radial-gradient(circle at 15% 90%, rgb(99 102 241 / 20%), transparent 32%), #eff6ff;
}

.auth-layout__message {
  max-width: 640px;
}

.auth-layout__eyebrow {
  margin: 0 0 18px;
  color: var(--color-primary);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.auth-layout__message h1 {
  max-width: 620px;
  margin: 0;
  color: #14213d;
  font-size: clamp(40px, 4vw, 62px);
  line-height: 1.14;
  letter-spacing: -0.045em;
}

.auth-layout__message > p:last-child {
  max-width: 570px;
  margin: 28px 0 0;
  color: #53627c;
  font-size: 17px;
  line-height: 1.9;
}

.auth-layout__feature-list {
  display: flex;
  gap: 12px;
}

.auth-layout__feature-list span {
  padding: 9px 14px;
  border: 1px solid rgb(37 99 235 / 14%);
  border-radius: 999px;
  color: #31517f;
  background: rgb(255 255 255 / 68%);
  font-size: 13px;
  font-weight: 600;
}

.auth-layout__panel {
  display: grid;
  min-height: 100vh;
  align-content: center;
  justify-items: center;
  padding: 48px 64px;
}

.auth-layout__card {
  width: min(440px, 100%);
}

.auth-layout__notice {
  margin: 30px 0 0;
  color: #98a2b3;
  font-size: 12px;
}
</style>
