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
  background: #fbfefc;
}

.auth-layout__intro {
  position: relative;
  display: flex;
  min-height: 100vh;
  flex-direction: column;
  justify-content: space-between;
  padding: 48px clamp(48px, 6vw, 96px);
  overflow: hidden;
  isolation: isolate;
  background:
    radial-gradient(circle at 82% 18%, rgb(168 220 193 / 72%), transparent 29%),
    radial-gradient(circle at 8% 92%, rgb(211 238 222 / 90%), transparent 34%), #edf8f1;
}

.auth-layout__intro::before,
.auth-layout__intro::after {
  position: absolute;
  z-index: -1;
  border: 1px solid rgb(47 143 104 / 16%);
  border-radius: 50%;
  content: '';
  pointer-events: none;
}

.auth-layout__intro::before {
  top: 14%;
  right: -12%;
  width: 420px;
  height: 420px;
  animation: knowledge-orbit 18s ease-in-out infinite alternate;
}

.auth-layout__intro::after {
  right: 18%;
  bottom: -16%;
  width: 310px;
  height: 310px;
  box-shadow: 0 0 0 38px rgb(255 255 255 / 22%);
  animation: knowledge-orbit 14s ease-in-out -5s infinite alternate-reverse;
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
  color: #163a2d;
  font-size: clamp(40px, 4vw, 62px);
  line-height: 1.14;
  letter-spacing: -0.045em;
}

.auth-layout__message > p:last-child {
  max-width: 570px;
  margin: 28px 0 0;
  color: #527064;
  font-size: 17px;
  line-height: 1.9;
}

.auth-layout__feature-list {
  display: flex;
  gap: 12px;
}

.auth-layout__feature-list span {
  padding: 9px 14px;
  border: 1px solid rgb(47 143 104 / 18%);
  border-radius: 999px;
  color: #315f4c;
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
  background:
    linear-gradient(90deg, rgb(47 143 104 / 4%) 1px, transparent 1px),
    linear-gradient(rgb(47 143 104 / 4%) 1px, transparent 1px);
  background-size: 32px 32px;
}

.auth-layout__card {
  width: min(440px, 100%);
}

.auth-layout__notice {
  margin: 30px 0 0;
  color: #98a2b3;
  font-size: 12px;
}

@keyframes knowledge-orbit {
  from {
    transform: translate3d(0, 0, 0) rotate(0);
  }
  to {
    transform: translate3d(-26px, 18px, 0) rotate(8deg);
  }
}

@media (max-width: 900px) {
  .auth-layout {
    grid-template-columns: 1fr;
  }
  .auth-layout__intro {
    min-height: 320px;
    padding: 32px;
  }
  .auth-layout__message h1 {
    font-size: clamp(34px, 8vw, 50px);
  }
  .auth-layout__message > p:last-child {
    margin-top: 18px;
  }
  .auth-layout__feature-list {
    margin-top: 28px;
  }
  .auth-layout__panel {
    min-height: auto;
    padding: 54px 24px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .auth-layout__intro::before,
  .auth-layout__intro::after {
    animation: none;
  }
}
</style>
