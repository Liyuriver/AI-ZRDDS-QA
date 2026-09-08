<script setup lang="ts">
defineEmits<{ suggest: [question: string] }>()

const suggestions = [
  {
    title: '开发问题',
    description: '查询依赖、配置和构建相关知识',
    question: 'ZRDDS 开发环境需要哪些依赖和配置？',
  },
  {
    title: '故障排查',
    description: '根据错误信息定位可能原因',
    question: 'ZRDDS 构建失败时应该如何排查？',
  },
  {
    title: '使用指南',
    description: '了解常见功能与操作流程',
    question: '请介绍 ZRDDS 的主要功能和基本使用流程。',
  },
]
</script>

<template>
  <section class="chat-welcome">
    <div class="chat-welcome__icon" aria-hidden="true">Z</div>
    <p class="chat-welcome__eyebrow">ZRDDS Knowledge Assistant</p>
    <h2>今天想了解什么？</h2>
    <p class="chat-welcome__description">
      请输入关于 ZRDDS 开发、配置或故障排查的问题。回答将同时展示可追溯的文档依据。
    </p>
    <div class="chat-welcome__suggestions">
      <button
        v-for="suggestion in suggestions"
        :key="suggestion.title"
        type="button"
        @click="$emit('suggest', suggestion.question)"
      >
        <strong>{{ suggestion.title }}</strong
        ><span>{{ suggestion.description }}</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.chat-welcome {
  width: min(760px, 100%);
  margin: auto;
  text-align: center;
}
.chat-welcome__icon {
  position: relative;
  display: grid;
  width: 58px;
  height: 58px;
  margin: 0 auto 20px;
  place-items: center;
  border-radius: 50% 50% 48% 52% / 42% 48% 52% 58%;
  color: #fff;
  background: linear-gradient(145deg, #72c69e, var(--color-primary-dark));
  box-shadow: 0 14px 34px rgb(36 113 80 / 22%);
  font-size: 22px;
  font-weight: 800;
}
.chat-welcome__icon::after {
  position: absolute;
  right: -5px;
  bottom: 3px;
  width: 13px;
  height: 20px;
  border-radius: 100% 0;
  background: #bce6ce;
  content: '';
  transform: rotate(20deg);
}
.chat-welcome__eyebrow {
  margin: 0 0 8px;
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.chat-welcome h2 {
  margin: 0;
  font-size: 31px;
  letter-spacing: -0.035em;
}
.chat-welcome__description {
  max-width: 610px;
  margin: 16px auto 0;
  color: var(--color-text-secondary);
  line-height: 1.8;
}
.chat-welcome__suggestions {
  display: grid;
  margin-top: 38px;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  text-align: left;
}
.chat-welcome__suggestions button {
  padding: 18px;
  border: 1px solid var(--color-border);
  border-radius: 14px;
  background: rgb(255 255 255 / 78%);
  box-shadow: 0 8px 28px rgb(31 90 65 / 5%);
  backdrop-filter: blur(10px);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    transform 0.2s ease,
    box-shadow 0.2s ease;
}
.chat-welcome__suggestions button:hover,
.chat-welcome__suggestions button:focus-visible {
  border-color: #9fd5b8;
  box-shadow: 0 14px 30px rgb(36 113 80 / 12%);
  transform: translateY(-3px) rotate(-0.25deg);
  outline: none;
}

@media (max-width: 760px) {
  .chat-welcome__suggestions {
    grid-template-columns: 1fr;
    margin-top: 26px;
  }
  .chat-welcome {
    text-align: left;
  }
  .chat-welcome__icon {
    margin-left: 0;
  }
  .chat-welcome__description {
    margin-left: 0;
  }
}
.chat-welcome__suggestions strong,
.chat-welcome__suggestions span {
  display: block;
}
.chat-welcome__suggestions strong {
  margin-bottom: 7px;
  font-size: 13px;
}
.chat-welcome__suggestions span {
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.6;
}
</style>
